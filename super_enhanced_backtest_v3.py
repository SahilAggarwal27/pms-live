"""
PMS SUPER-ENHANCED BACKTEST v3 — 12-layer flagship strategy

Targets: Fix 2016 (demonetization), 2018 (small-cap crash), 2019 (narrow rally),
2024 (SEBI warning) underperformance.

Layers from prior versions:
  L1:  Nifty regime filter
  L2:  15% trailing stop
  L3:  60% vol cap
  L4:  30% sector cap (tightened in v3 to 20%)
  L5:  Multi-TF momentum (3M+6M+12M)
  L6:  India VIX regime (half size >25, cash >40)
  L10: Sector rotation top-3 bonus

NEW v3 layers:
  L11: DYNAMIC UNIVERSE — switch between Nifty100 (large) / mid-small / blend
       based on 6M relative strength Nifty50 vs Nifty Smallcap 100
  L12: MARKET BREADTH — only trade when >40% stocks above 200-DMA
  L13: 50+200 DMA COMBINED REGIME — Nifty > 50-DMA > 200-DMA (tighter)
  L14: 15% CASH BUFFER — never fully invested, always keep 15% dry powder
  L15: TIGHTER SECTOR CAP — max 20% (3 stocks per sector)
  L16: RELATIVE MOMENTUM — score = stock_6M - sector_avg_6M (pick BEST in sector)

Expected: 25% (Honest) → 32% (Enhanced) → 38-42% (Super v3) with lower DD
"""
import json, os, sys, traceback, time
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
except ImportError:
    SESSION = None

# ============================================================
# TWO UNIVERSES: Nifty100 (large caps) and Mid/Small
# L11: Dynamic switching between them
# ============================================================

NIFTY100_LARGE = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","HINDUNILVR","ITC","LT",
    "KOTAKBANK","SBIN","AXISBANK","BAJFINANCE","BHARTIARTL","ASIANPAINT","MARUTI",
    "HDFCLIFE","M&M","TATASTEEL","SUNPHARMA","NTPC","POWERGRID","ULTRACEMCO",
    "ONGC","TITAN","DRREDDY","NESTLEIND","ADANIENT","ADANIPORTS","JSWSTEEL",
    "TATAMOTORS","TATACONSUM","APOLLOHOSP","CIPLA","INDUSINDBK","GRASIM",
    "HEROMOTOCO","BRITANNIA","EICHERMOT","DIVISLAB","BAJAJFINSV","BPCL",
    "COALINDIA","HINDALCO","TECHM","WIPRO","BAJAJ-AUTO","SBILIFE","HCLTECH",
    "SHRIRAMFIN","UPL","LTIM","DABUR","GODREJCP","BOSCHLTD","MRF",
    "SIEMENS","CUMMINSIND","HAL","BEL","MUTHOOTFIN","CHOLAFIN","DLF",
    "GODREJPROP","LUPIN","PIIND","SRF","TRENT","HAVELLS","VBL",
    "PAGEIND","AMBUJACEM","SHREECEM","DIVISLAB","TORNTPHARM","INDIGO",
    "PIDILITIND","JINDALSTEL","VEDL","SAIL","TATAPOWER","GAIL","IOC",
    "HPCL","PFC","RECLTD","IRCTC","IRFC","RVNL","LICI","SUZLON"]

MIDSMALL_UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","KPITTECH","TATAELXSI","OFSS",
    "MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","LICHSGFIN","MFSL",
    "AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM",
    "ABBOTINDIA","THERMAX","CGPOWER","DIXON","DEEPAKNTR","NAVINFLUOR","ATUL",
    "AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","VOLTAS","CROMPTON",
    "JUBLFOOD","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","OBEROIRLTY",
    "PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","IGL","HINDZINC",
    "NMDC","YESBANK","IDEA","JPASSOCIAT","PNB","CANBK","UNIONBANK",
    "BANDHANBNK","RBLBANK","BHEL","BEML","MOIL","HINDCOPPER","NHPC",
    "NBCC","BLUEDART","MAZDOCK","APOLLOTYRE","JKTYRE","CEATLTD","MMFSL",
    "TVSMOTOR","ESCORTS","ASHOKLEY","AMARAJABAT","MARICO","EMAMILTD",
    "COLPAL","GILLETTE","BATA","RELAXO","INDHOTEL","LEMONTREE","BRIGADE",
    "SUNTECK","MAHLIFE","PHOENIXLTD","GATI","TCI","ALLCARGO","COCHINSHIP",
    "TORNTPOWER","JSWENERGY","ADANIPOWER","NCC","HGINFRA","KNRCON",
    "GMRINFRA","IRB","APLAPOLLO","JINDALSAW","WELCORP","MAXHEALTH",
    "METROPOLIS","LALPATHLAB","AJANTPHARM","IPCALAB","GRANULES","STRIDES",
    "MARKSANS","VBL","VARUN","BIKAJI","UBL","RADICO"]

FULL_UNIVERSE = sorted(set(NIFTY100_LARGE + MIDSMALL_UNIVERSE))

# ============================================================
# SECTOR MAP for L4 + L16 (relative momentum vs sector)
# ============================================================
SECTOR_MAP = {
    "IT":["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","INFY","TCS","WIPRO","HCLTECH","TECHM"],
    "BANK":["HDFCBANK","ICICIBANK","KOTAKBANK","SBIN","AXISBANK","INDUSINDBK","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","YESBANK","PNB","CANBK","UNIONBANK","BANDHANBNK","RBLBANK"],
    "NBFC":["BAJFINANCE","BAJAJFINSV","SBILIFE","HDFCLIFE","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","SHRIRAMFIN","MMFSL","LICI"],
    "AUTO":["MARUTI","M&M","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ESCORTS","ASHOKLEY","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD"],
    "PHARMA":["SUNPHARMA","CIPLA","DRREDDY","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","DIVISLAB","APOLLOHOSP","TORNTPHARM","MAXHEALTH","METROPOLIS","LALPATHLAB","AJANTPHARM","IPCALAB","GRANULES","STRIDES","MARKSANS"],
    "FMCG":["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","EMAMILTD","GILLETTE","VBL","VARUN","JUBLFOOD","BIKAJI","UBL","RADICO","TATACONSUM","BATA","RELAXO"],
    "OIL_GAS":["RELIANCE","ONGC","BPCL","IOC","HPCL","GAIL","IGL"],
    "METAL":["TATASTEEL","JSWSTEEL","JINDALSTEL","SAIL","NMDC","VEDL","HINDCOPPER","HINDZINC","HINDALCO","MOIL","APLAPOLLO","JINDALSAW","WELCORP"],
    "CEMENT":["ULTRACEMCO","SHREECEM","AMBUJACEM"],
    "POWER":["NTPC","POWERGRID","TATAPOWER","ADANIPOWER","TORNTPOWER","JSWENERGY","NHPC"],
    "INFRA":["LT","ADANIENT","ADANIPORTS","GRASIM","NBCC","IRCTC","IRFC","RVNL","INDIGO","BLUEDART","GATI","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","NCC","HGINFRA","KNRCON","JPASSOCIAT","GMRINFRA","IRB","BHEL","BEML"],
    "CAPGOODS":["BEL","HAL","SIEMENS","CUMMINSIND","THERMAX","CGPOWER","DIXON"],
    "TELECOM":["BHARTIARTL","IDEA"],
    "REALESTATE":["GODREJPROP","OBEROIRLTY","PRESTIGE","MAHLIFE","BRIGADE","SUNTECK","PHOENIXLTD","INDHOTEL","LEMONTREE","DLF"],
    "CHEMICAL":["PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","UPL"],
    "CONSUMER_DUR":["ASIANPAINT","TITAN","HAVELLS","VOLTAS","CROMPTON","PAGEIND","TRENT","PIDILITIND"],
    "EXCHANGE":["IEX","CDSL","MCX","INDIAMART","NAUKRI"],
    "OTHER":["COALINDIA","SUZLON"]
}

def sector_of(t):
    for s,l in SECTOR_MAP.items():
        if t in l: return s
    return "OTHER"

# CONFIG
TOP_N = 15
CORPUS = 10_000_000
SLIPPAGE_PER_SIDE = 0.30
MIN_LISTING_DAYS = 3*365
LOOKBACK_TREND = 200
LOOKBACK_SHORT = 50
LOOKBACK_MOM_3M = 63
LOOKBACK_MOM_6M = 126
LOOKBACK_MOM_12M = 252
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# LAYER PARAMS
TRAILING_STOP_PCT = 15.0        # L2
MAX_VOLATILITY = 60.0            # L3
MAX_SECTOR_PCT_V3 = 20.0         # L15: tighter (was 30)
VIX_HALF_SIZE = 25.0             # L6
VIX_CASH = 40.0                  # L6
BREADTH_MIN = 40.0               # L12: RE-ENABLED
CASH_BUFFER_PCT = 15.0           # L14: minimum cash
SECTOR_ROT_BONUS = 0.10          # L10
SECTOR_ROT_PENALTY = 0.05

# L11 Dynamic Universe params
UNIVERSE_LARGE_THRESHOLD = 0.10  # Nifty50 outperforms Smallcap by 10% in 6M → large mode
UNIVERSE_SMALL_THRESHOLD = 0.05  # Smallcap outperforms Nifty50 by 5% → mid/small mode


def load_cost_regimes():
    try:
        with open("cost_history.json") as f:
            return sorted(json.load(f)["regimes"], key=lambda r:r["startDate"])
    except: return []

def costs_for_date(date_str, regimes):
    if not regimes: return {"buy":0.75,"sell":0.75,"regimeEvent":"FLAT"}
    active = regimes[0]
    for r in regimes:
        if r["startDate"] <= date_str: active = r
        else: break
    b = active["brokeragePerSide"]; gst = active["gstOnBrokerage"]/100
    return {
        "buy": b*(1+gst)+SLIPPAGE_PER_SIDE+active["sttBuyDelivery"]+active["stampBuy"]+active["exchangeSebi"],
        "sell": b*(1+gst)+SLIPPAGE_PER_SIDE+active["sttSellDelivery"]+active["exchangeSebi"],
        "regimeEvent": active["event"]
    }

def download_ticker(ticker, retries=2):
    for a in range(retries):
        try:
            kw = dict(start=START_DATE, end=END_DATE, progress=False, auto_adjust=True, threads=False)
            if SESSION: kw["session"] = SESSION
            df = yf.download(ticker, **kw)
            if df is None or df.empty:
                if a < retries-1: time.sleep(1); continue
                return None
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            closes = df["Close"]
            if hasattr(closes,"columns") and len(closes.columns)>0: closes = closes.iloc[:,0]
            closes = closes.dropna()
            if len(closes) < 30: return None
            return closes
        except:
            if a < retries-1: time.sleep(1)
    return None

def download_all():
    print(f"Downloading {len(FULL_UNIVERSE)} stocks + Nifty50 + Nifty Smallcap 100 + VIX...")
    data = {}
    for i, t in enumerate(FULL_UNIVERSE):
        if (i+1)%30==0 or i==0: print(f"  {i+1}/{len(FULL_UNIVERSE)} ({len(data)} OK)")
        c = download_ticker(f"{t}.NS")
        if c is not None: data[t] = c
    print(f"OK: {len(data)}/{len(FULL_UNIVERSE)}")
    n = download_ticker("^NSEI")
    if n is not None: data["_NIFTY"] = n
    sc = download_ticker("^CNXSC")  # Nifty Smallcap 100
    if sc is not None:
        data["_NIFTY_SC"] = sc
        print(f"Nifty Smallcap 100: {len(sc)} rows (from {sc.index[0].date()})")
    vix = download_ticker("^INDIAVIX")
    if vix is not None:
        data["_VIX"] = vix
        print(f"India VIX: {len(vix)} rows")
    return data

def get_month_ends(start, end):
    try: dates = pd.date_range(start=start,end=end,freq="BME")
    except: dates = pd.date_range(start=start,end=end,freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]

def nifty_regime_v3(data, date):
    """L13: Nifty > 50-DMA AND > 200-DMA AND 50-DMA > 200-DMA (tighter)"""
    if "_NIFTY" not in data: return True
    nh = data["_NIFTY"]; nh = nh[nh.index <= date]
    if len(nh) < LOOKBACK_TREND: return True
    cmp = float(nh.iloc[-1])
    dma50 = float(nh.tail(LOOKBACK_SHORT).mean())
    dma200 = float(nh.tail(LOOKBACK_TREND).mean())
    return cmp > dma50 and cmp > dma200 and dma50 > dma200

def vix_regime(data, date):
    if "_VIX" not in data: return 1.0
    v = data["_VIX"]; v = v[v.index <= date]
    if len(v) == 0: return 1.0
    cur = float(v.iloc[-1])
    if cur >= VIX_CASH: return 0.0
    if cur >= VIX_HALF_SIZE: return 0.5
    return 1.0

def universe_mode(data, date):
    """L11: Choose universe based on Nifty50 vs Smallcap 6M relative strength."""
    if "_NIFTY" not in data or "_NIFTY_SC" not in data:
        return "midsmall"  # default
    try:
        nh = data["_NIFTY"][data["_NIFTY"].index <= date]
        sh = data["_NIFTY_SC"][data["_NIFTY_SC"].index <= date]
        if len(nh) < 130 or len(sh) < 130: return "midsmall"
        n6m = float(nh.iloc[-1]) / float(nh.iloc[-127]) - 1
        s6m = float(sh.iloc[-1]) / float(sh.iloc[-127]) - 1
        diff = n6m - s6m
        if diff > UNIVERSE_LARGE_THRESHOLD:
            return "large"    # Nifty50 winning by >10% → large caps
        elif diff < -UNIVERSE_SMALL_THRESHOLD:
            return "midsmall" # Smallcap winning by >5% → mid/small
        else:
            return "blend"    # 50/50 mix
    except:
        return "midsmall"

def get_active_universe(mode):
    """Return list of tickers active in current mode"""
    if mode == "large":
        return set(NIFTY100_LARGE)
    elif mode == "midsmall":
        return set(MIDSMALL_UNIVERSE)
    else:  # blend
        return set(NIFTY100_LARGE) | set(MIDSMALL_UNIVERSE)

def market_breadth(data, date, universe):
    """L12: % of active universe above 200-DMA"""
    above = 0; total = 0
    for t in universe:
        if t not in data: continue
        try:
            h = data[t][data[t].index <= date]
            if len(h) < LOOKBACK_TREND: continue
            total += 1
            if float(h.iloc[-1]) > float(h.tail(LOOKBACK_TREND).mean()):
                above += 1
        except: continue
    if total == 0: return 100.0
    return above / total * 100

def sector_strength(data, date, universe, lookback_days=126):
    """L10 + L16: rank sectors by 6M return AND compute per-sector avg for relative momentum"""
    sector_returns = {}
    for sec, tickers in SECTOR_MAP.items():
        rets = []
        for t in tickers:
            if t not in data or t not in universe: continue
            try:
                h = data[t][data[t].index <= date]
                if len(h) < lookback_days+1: continue
                r = float(h.iloc[-1]) / float(h.iloc[-lookback_days-1]) - 1
                rets.append(r)
            except: continue
        if rets: sector_returns[sec] = sum(rets)/len(rets)
    return sector_returns

def rank_v3(data, date_str, universe, top_sectors_ranked):
    """L5 mom + L3 vol + L10 sector rot + L16 relative momentum (vs sector)"""
    ranked = []
    date = pd.Timestamp(date_str)
    top_sec_set = set([s for s,_ in top_sectors_ranked[:3]])
    bot_sec_set = set([s for s,_ in top_sectors_ranked[-3:]]) if len(top_sectors_ranked)>=6 else set()
    sector_avgs = dict(top_sectors_ranked)  # dict of sec → avg 6M return

    for ticker in universe:
        if ticker not in data: continue
        try:
            hist = data[ticker][data[ticker].index <= date]
            if len(hist) < LOOKBACK_MOM_12M: continue
            if (date - hist.index[0]).days < MIN_LISTING_DAYS: continue
            cmp = float(hist.iloc[-1])
            dma200 = float(hist.tail(LOOKBACK_TREND).mean())
            if cmp <= dma200: continue

            # L3 vol cap
            recent = hist.tail(126)
            if len(recent) < 30: continue
            vol = float(recent.pct_change().dropna().std() * np.sqrt(252) * 100)
            if vol > MAX_VOLATILITY: continue

            # L5 multi-TF
            p3 = float(hist.iloc[-LOOKBACK_MOM_3M-1])
            p6 = float(hist.iloc[-LOOKBACK_MOM_6M-1])
            p12 = float(hist.iloc[-LOOKBACK_MOM_12M-1])
            r3 = cmp/p3 - 1; r6 = cmp/p6 - 1; r12 = cmp/p12 - 1
            if max(r3,r6,r12) > 2.0: continue

            base_mom = 0.25*r3 + 0.50*r6 + 0.25*r12

            # L16: Relative momentum — how much better than sector avg?
            sec = sector_of(ticker)
            sec_avg = sector_avgs.get(sec, 0)
            relative = r6 - sec_avg  # positive = beating sector
            rel_bonus = min(0.15, max(-0.10, relative))  # cap ±10-15%

            # L10: Sector rotation bonus
            if sec in top_sec_set: rot_bonus = SECTOR_ROT_BONUS
            elif sec in bot_sec_set: rot_bonus = -SECTOR_ROT_PENALTY
            else: rot_bonus = 0

            score = base_mom + rel_bonus + rot_bonus
            ranked.append({"ticker":ticker,"cmp":round(cmp,2),"score":score,
                          "base":base_mom,"relative":relative,"vol":round(vol,1),"sector":sec})
        except: continue
    ranked.sort(key=lambda x:-x["score"])
    return ranked

def apply_sector_cap(ranked, top_n, max_pct):
    """L15: Tighter 20% cap"""
    max_per = max(1, int(top_n * max_pct / 100))
    picked = []; sec_count = {}
    for r in ranked:
        s = r["sector"]
        if sec_count.get(s,0) >= max_per: continue
        picked.append(r)
        sec_count[s] = sec_count.get(s,0) + 1
        if len(picked) >= top_n: break
    return picked


def run_backtest():
    print("="*70)
    print("PMS SUPER-ENHANCED BACKTEST v3 — 12 LAYERS FLAGSHIP")
    print("L1-L5 + L6 VIX + L10 SecRot + L11 Dynamic Univ + L12 Breadth")
    print("L13 50+200DMA + L14 15% Cash + L15 20% Sector + L16 Rel Mom")
    print("="*70)

    regimes = load_cost_regimes()
    data = download_all()
    if len(data) < 50: print("ERROR"); sys.exit(1)

    month_ends = get_month_ends("2003-06-01", END_DATE)
    print(f"\nRunning {len(month_ends)} monthly rebalances with 12-layer v3 strategy...")

    holdings = {}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None
    prev_nav = CORPUS
    total_costs = 0
    universe_switch_count = 0
    prev_mode = None
    regime_offs = 0; vix_offs = 0; breadth_offs = 0

    for i, date_str in enumerate(month_ends):
        date = pd.Timestamp(date_str)
        c = costs_for_date(date_str, regimes)
        cmps = {}
        for t in data:
            if t.startswith("_"): continue
            try:
                h = data[t][data[t].index <= date]
                if len(h) > 0: cmps[t] = float(h.iloc[-1])
            except: pass
        if starting_nifty is None and "_NIFTY" in data:
            nh = data["_NIFTY"][data["_NIFTY"].index <= date]
            if len(nh) > 0: starting_nifty = float(nh.iloc[-1])

        # L13: Tighter Nifty regime
        nifty_ok = nifty_regime_v3(data, date)
        # L6: VIX regime
        vix_mult = vix_regime(data, date)
        # L11: Dynamic Universe
        mode = universe_mode(data, date)
        if prev_mode is not None and prev_mode != mode:
            universe_switch_count += 1
        prev_mode = mode
        active_universe = get_active_universe(mode)
        # L12: Market breadth on ACTIVE universe
        breadth = market_breadth(data, date, active_universe)
        breadth_ok = breadth >= BREADTH_MIN

        if not nifty_ok: regime_offs += 1
        if vix_mult < 1.0: vix_offs += 1
        if not breadth_ok: breadth_offs += 1

        regime_ok = nifty_ok and breadth_ok and vix_mult > 0

        # L2: Trailing stops
        forced_sells = []
        for t, pos in list(holdings.items()):
            if t in cmps:
                if cmps[t] > pos["peak"]: pos["peak"] = cmps[t]
                if (pos["peak"] - cmps[t]) / pos["peak"] * 100 >= TRAILING_STOP_PCT:
                    forced_sells.append(t)

        # L10+L16 sector data
        sec_returns = sector_strength(data, date, active_universe)
        top_sectors_ranked = sorted(sec_returns.items(), key=lambda x:-x[1])
        # Rank picks
        ranked = rank_v3(data, date_str, active_universe, top_sectors_ranked)
        # L15: Tighter 20% sector cap
        picked = apply_sector_cap(ranked, TOP_N, MAX_SECTOR_PCT_V3)
        picked_tickers = [p["ticker"] for p in picked]

        # Also force sell holdings not in ACTIVE universe (universe switched)
        universe_swap_sells = [t for t in holdings if t not in active_universe]

        to_sell = set(forced_sells) | set(universe_swap_sells)
        if not regime_ok:
            to_sell.update(list(holdings.keys()))
        else:
            to_sell.update([t for t in holdings if t not in picked_tickers])

        sold = []
        for t in to_sell:
            if t not in holdings: continue
            pos = holdings[t]
            raw_sp = cmps.get(t, pos["entry_price"])
            sp = raw_sp * (1 - c["sell"]/100)
            cost = raw_sp * pos["shares"] * c["sell"]/100
            total_costs += cost
            pnl_abs = round((sp-pos["entry_price"])*pos["shares"])
            pnl_pct = round(((sp-pos["entry_price"])/pos["entry_price"])*100, 2)
            hd = (date - pd.Timestamp(pos["entry_date"])).days
            if t in forced_sells: reason = "TRAIL"
            elif t in universe_swap_sells: reason = "UNIV_SWAP"
            elif not nifty_ok: reason = "NO_NIFTY"
            elif not breadth_ok: reason = "NO_BREADTH"
            elif vix_mult == 0: reason = "VIX_PANIC"
            else: reason = "ROTATION"
            completed_trades.append({
                "ticker":t,"entryDate":pos["entry_date"],"exitDate":date_str,
                "entryPrice":pos["entry_price"],"exitPrice":round(sp,2),
                "shares":pos["shares"],"holdDays":hd,
                "pnlAbs":pnl_abs,"pnlPct":pnl_pct,
                "outcome":"WIN" if pnl_pct>0 else "LOSS","exitReason":reason
            })
            sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% {reason})")
            cash += pos["shares"]*sp
            del holdings[t]

        bought = []
        if regime_ok and picked:
            current_mv = sum(h["shares"]*cmps.get(t,h["entry_price"]) for t,h in holdings.items())
            current_nav = cash + current_mv
            # L14: 15% cash buffer — only deploy 85% × vix_mult
            deployable_ratio = (1 - CASH_BUFFER_PCT/100) * vix_mult
            target_deployed = current_nav * deployable_ratio
            per_stock = target_deployed / TOP_N
            for p in picked:
                if p["ticker"] in holdings: continue
                eff = p["cmp"] * (1 + c["buy"]/100)
                if eff <= 0: continue
                shares = int(per_stock/eff)
                outlay = shares*eff
                if shares < 1 or cash < outlay: continue
                # Also respect cash buffer during buys
                min_cash = current_nav * CASH_BUFFER_PCT/100
                if cash - outlay < min_cash: continue
                cost = shares * p["cmp"] * c["buy"]/100
                total_costs += cost
                cash -= outlay
                holdings[p["ticker"]] = {"shares":shares,"entry_price":round(eff,2),
                                         "entry_date":date_str,"peak":p["cmp"]}
                bought.append(p["ticker"])

        final_mv = sum(h["shares"]*cmps.get(t,h["entry_price"]) for t,h in holdings.items())
        final_nav = cash + final_mv
        mom = ((final_nav/prev_nav)-1)*100 if prev_nav>0 else 0
        total = ((final_nav/CORPUS)-1)*100
        month_str = date_str[:7]
        held_this = [t for t in holdings if t not in bought]
        wins_m = sum(1 for tr in completed_trades if tr["exitDate"].startswith(month_str) and tr["pnlPct"]>0)
        loss_m = sum(1 for tr in completed_trades if tr["exitDate"].startswith(month_str) and tr["pnlPct"]<=0)

        monthly_journal.append({
            "month":month_str,"date":date_str,
            "nav":round(final_nav),"navCr":round(final_nav/10_000_000,3),
            "monthReturn":round(mom,2),"totalReturn":round(total,2),
            "cash":round(cash),"holdingsCount":len(holdings),
            "bought":bought,"sold":sold,"held":held_this,
            "winsThisMonth":wins_m,"lossesThisMonth":loss_m,
            "regimeOn":regime_ok,"niftyOk":nifty_ok,"breadth":round(breadth,1),
            "vixMult":vix_mult,"universeMode":mode,
            "topSectors":[s for s,_ in top_sectors_ranked[:3]],
            "regimeEvent":c["regimeEvent"]
        })
        nav_history.append({"date":date_str,"nav":final_nav})
        prev_nav = final_nav

        if (i+1)%12 == 0:
            top3 = [s for s,_ in top_sectors_ranked[:3]]
            print(f"  {date_str[:4]}: NAV Rs {final_nav/10_000_000:.2f}Cr | Tot {total:+.1f}% | Univ:{mode[:5]} | Breadth {breadth:.0f}% | VIX-mult {vix_mult}")

    # SUMMARY
    final_nav = nav_history[-1]["nav"]
    total_return = ((final_nav/CORPUS)-1)*100
    years = (pd.Timestamp(nav_history[-1]["date"]) - pd.Timestamp(nav_history[0]["date"])).days/365.25
    cagr = (pow(final_nav/CORPUS, 1/years)-1)*100 if years>0 else 0
    peak = CORPUS; max_dd = 0
    for h in nav_history:
        if h["nav"] > peak: peak = h["nav"]
        dd = (h["nav"]-peak)/peak*100
        if dd < max_dd: max_dd = dd
    wins = sum(1 for t in completed_trades if t["pnlPct"]>0)
    win_rate = wins/max(1,len(completed_trades))*100
    avg_win = sum(t["pnlPct"] for t in completed_trades if t["pnlPct"]>0)/max(1,wins)
    losses = [t for t in completed_trades if t["pnlPct"]<=0]
    avg_loss = sum(t["pnlPct"] for t in losses)/max(1,len(losses))
    avg_hold = sum(t["holdDays"] for t in completed_trades)/max(1,len(completed_trades))
    reason_counts = {}
    for t in completed_trades:
        r = t.get("exitReason","UNK")
        reason_counts[r] = reason_counts.get(r,0)+1
    nifty_cagr = 0
    if "_NIFTY" in data and starting_nifty:
        nifty_end = float(data["_NIFTY"].iloc[-1])
        nifty_cagr = (pow(nifty_end/starting_nifty, 1/years)-1)*100

    print("\n"+"="*70)
    print("SUPER-ENHANCED v3 BACKTEST COMPLETE — 12 LAYERS")
    print("="*70)
    print(f"CAGR:             {cagr:+.2f}%   (Honest 25.65%, Enhanced ~32%, v3 target 38-42%)")
    print(f"Nifty CAGR:       {nifty_cagr:+.2f}%")
    print(f"Alpha:            {cagr-nifty_cagr:+.2f}%")
    print(f"Max Drawdown:     {max_dd:.1f}%   (Honest -53.7%, v3 target -25%)")
    print(f"Trades:           {len(completed_trades)} | Win {win_rate:.1f}% | Hold {avg_hold:.0f}d")
    print(f"Avg W/L:          +{avg_win:.1f}% / {avg_loss:.1f}%")
    print(f"Rs 1 Cr became:   Rs {final_nav/10_000_000:.2f} Cr")
    print(f"Exit reasons:     {reason_counts}")
    print(f"Regime offs:      Nifty {regime_offs} | VIX {vix_offs} | Breadth {breadth_offs}")
    print(f"Universe switches: {universe_switch_count}")
    print("="*70)

    output = {
        "monthlyJournal":monthly_journal,"completedTrades":completed_trades,
        "navHistory":[{"date":h["date"],"nav":round(h["nav"])} for h in nav_history],
        "holdings":{t:{"shares":h["shares"],"entryPrice":h["entry_price"],"entryDate":h["entry_date"]} for t,h in holdings.items()},
        "startDate":nav_history[0]["date"],"endDate":nav_history[-1]["date"],
        "summary":{
            "years":round(years,1),"cagr":round(cagr,2),"totalReturn":round(total_return,1),
            "niftyCagr":round(nifty_cagr,2),"alpha":round(cagr-nifty_cagr,2),
            "maxDrawdown":round(max_dd,1),"totalTrades":len(completed_trades),
            "winRate":round(win_rate,1),"avgWin":round(avg_win,1),"avgLoss":round(avg_loss,1),
            "avgHoldDays":round(avg_hold,0),"finalNavCr":round(final_nav/10_000_000,2),
            "mode":"super-enhanced-v3","exitReasons":reason_counts,
            "universeSwitches":universe_switch_count,
            "layers":"L1 Nifty + L2 15% Trail + L3 60% Vol + L4 Sector + L5 MultiTF Mom + L6 VIX + L10 SectorRot + L11 Dynamic Universe + L12 40% Breadth + L13 50+200 DMA + L14 15% Cash Buffer + L15 20% Sector Cap + L16 Relative Momentum",
            "assumptions":"L1-L16 (12-layer flagship) on 200+ stock full universe with dynamic universe switching"
        },
        "runDate":datetime.now().isoformat()
    }
    with open("backtest_super_enhanced_v3.json","w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_super_enhanced_v3.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    try: run_backtest()
    except Exception as e:
        print(f"\nFATAL: {e}"); traceback.print_exc(); sys.exit(1)
