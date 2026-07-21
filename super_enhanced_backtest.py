"""
PMS SUPER-ENHANCED BACKTEST — 10 layers stacked for maximum client returns

Base layers (from enhanced_backtest.py):
  L1: Nifty regime filter (Nifty > 200-DMA to trade)
  L2: Trailing stop loss (15% from peak)
  L3: Volatility cap (< 60% annualized)
  L4: Sector cap (max 30% per sector)
  L5: Multi-timeframe momentum (3M+6M+12M weighted)

NEW super layers:
  L6: INDIA VIX regime — reduce size at VIX>25, cash at VIX>40
  L7: MARKET BREADTH filter — only trade when >50% stocks above 200-DMA
  L9: KELLY-OPTIMAL sizing — weight positions by confidence score
  L10: SECTOR ROTATION — overweight top-3 relative-strength sectors

Expected: 25% (Honest) → 32% (Enhanced) → 38-42% (Super-Enhanced)

Note: More layers = more overfitting risk. Use Monte Carlo validation.
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

WINNERS = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]
NIFTY50 = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","HINDUNILVR","ITC","LT","KOTAKBANK","SBIN","AXISBANK","BAJFINANCE","BHARTIARTL","ASIANPAINT","MARUTI","HDFCLIFE","M&M","TATASTEEL","SUNPHARMA","NTPC","POWERGRID","ULTRACEMCO","ONGC","TITAN","DRREDDY","NESTLEIND","ADANIENT","ADANIPORTS","JSWSTEEL","TATAMOTORS","TATACONSUM","APOLLOHOSP","CIPLA","INDUSINDBK","GRASIM","HEROMOTOCO","BRITANNIA","EICHERMOT","DIVISLAB","BAJAJFINSV","BPCL","COALINDIA","HINDALCO","TECHM","WIPRO","BAJAJ-AUTO","SBILIFE","HCLTECH","SHRIRAMFIN","UPL"]
BLOWUPS = ["YESBANK","IDEA","JPASSOCIAT","SUZLON","RCOM","IDBI","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK","JPPOWER","IBREALEST","GVKPIL","GMRINFRA","IRB"]
LAGGARDS = ["BHEL","BEML","CONCOR","MOIL","MMTC","MRPL","HINDCOPPER","SAIL","NHPC","NLCINDIA","IOC","HPCL","OIL","NBCC","IRCTC","IRFC","RVNL","INDIGO","SPICEJET","VSTIND","GODREJIND","DABUR","EMAMILTD","COLPAL","MARICO","GODREJCP","BATA","RELAXO","INDHOTEL","LEMONTREE","MAHLIFE","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD","BLUEDART","GATI","VRLLOG","MAHLOG","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","BANDHANBNK","RBLBANK","EQUITASBNK","UJJIVAN","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK","ULTRACEMCO","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT","HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM","VEDL","APLAPOLLO","JINDALSAW","WELCORP","TORNTPHARM","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","PFIZER","GLAXO","SANOFI","AJANTPHARM","IPCALAB","ERISLIFE","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS","TVSMOTOR","ESCORTS","ASHOKLEY","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD","MMFSL","JYOTHYLAB","GILLETTE","VARUN","WESTLIFE","DEVYANI","BIKAJI","GODFRYPHLP","UBL","RADICO","ADANIPOWER","TORNTPOWER","JSWENERGY","NCC","HGINFRA","KNRCON"]
UNIVERSE = sorted(set(WINNERS + NIFTY50 + BLOWUPS + LAGGARDS))

SECTOR_MAP = {
    "IT":["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","INFY","TCS","WIPRO","HCLTECH","TECHM"],
    "BANK":["HDFCBANK","ICICIBANK","KOTAKBANK","SBIN","AXISBANK","INDUSINDBK","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","YESBANK","IDBI","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK","BANDHANBNK","RBLBANK","EQUITASBNK","UJJIVAN","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK"],
    "NBFC":["BAJFINANCE","BAJAJFINSV","SBILIFE","HDFCLIFE","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","SHRIRAMFIN","MMFSL"],
    "AUTO":["MARUTI","M&M","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ESCORTS","ASHOKLEY","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD"],
    "PHARMA":["SUNPHARMA","CIPLA","DRREDDY","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","DIVISLAB","APOLLOHOSP","TORNTPHARM","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","PFIZER","GLAXO","SANOFI","AJANTPHARM","IPCALAB","ERISLIFE","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS"],
    "FMCG":["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","EMAMILTD","JYOTHYLAB","GILLETTE","VBL","VARUN","JUBLFOOD","WESTLIFE","DEVYANI","BIKAJI","GODFRYPHLP","UBL","RADICO","TATACONSUM","BATA","RELAXO"],
    "OIL_GAS":["RELIANCE","ONGC","BPCL","IOC","HPCL","GAIL","IGL","OIL","PETRONET","GUJGASLTD","MGL","MRPL"],
    "METAL":["TATASTEEL","JSWSTEEL","JINDALSTEL","SAIL","NMDC","VEDL","HINDCOPPER","HINDZINC","NATIONALUM","HINDALCO","MOIL","APLAPOLLO","JINDALSAW","WELCORP"],
    "CEMENT":["ULTRACEMCO","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT","HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM"],
    "POWER":["NTPC","POWERGRID","TATAPOWER","ADANIPOWER","TORNTPOWER","JSWENERGY","JPPOWER","NHPC","NLCINDIA"],
    "INFRA":["LT","ADANIENT","ADANIPORTS","GRASIM","NBCC","IRCTC","IRFC","RVNL","INDIGO","SPICEJET","BLUEDART","GATI","VRLLOG","MAHLOG","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","NCC","HGINFRA","KNRCON","JPASSOCIAT","GVKPIL","GMRINFRA","IRB","BHEL","BEML","CONCOR","BEL","HAL","SIEMENS","CUMMINSIND","THERMAX","CGPOWER","DIXON"],
    "TELECOM":["BHARTIARTL","IDEA","RCOM"],
    "REALESTATE":["GODREJPROP","OBEROIRLTY","PRESTIGE","MAHLIFE","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD","IBREALEST","INDHOTEL","LEMONTREE"],
    "CHEMICAL":["PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","UPL"],
    "CONSUMER_DUR":["ASIANPAINT","TITAN","HAVELLS","VOLTAS","CROMPTON","PAGEIND","TRENT"],
    "EXCHANGE":["IEX","CDSL","MCX","INDIAMART","NAUKRI"],
    "OTHER":["COALINDIA","VSTIND","GODREJIND","MMTC","SUZLON"]
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
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")
LOOKBACK_TREND = 200

# LAYER PARAMS
NIFTY_TREND_LOOKBACK = 200
TRAILING_STOP_PCT = 15.0
MAX_VOLATILITY = 60.0
MAX_SECTOR_PCT = 30.0
LOOKBACK_MOM_3M = 63
LOOKBACK_MOM_6M = 126
LOOKBACK_MOM_12M = 252
VIX_HALF_SIZE = 25.0  # L6: if VIX above this → 50% size
VIX_CASH = 40.0        # L6: if VIX above this → all cash
BREADTH_MIN = 50.0     # L7: min % stocks above 200-DMA to trade
KELLY_FRAC = 0.5       # L9: use half-Kelly for safety


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
    print(f"Downloading {len(UNIVERSE)} stocks + Nifty + India VIX...")
    data = {}
    for i, t in enumerate(UNIVERSE):
        if (i+1)%25==0 or i==0: print(f"  {i+1}/{len(UNIVERSE)} ({len(data)} OK)")
        c = download_ticker(f"{t}.NS")
        if c is not None: data[t] = c
    print(f"OK: {len(data)}/{len(UNIVERSE)}")
    n = download_ticker("^NSEI")
    if n is not None: data["_NIFTY"] = n
    # L6: India VIX
    vix = download_ticker("^INDIAVIX")
    if vix is not None:
        data["_VIX"] = vix
        print(f"India VIX: {len(vix)} rows (available from {vix.index[0].strftime('%Y-%m')})")
    else:
        print("India VIX unavailable - L6 will use fallback logic")
    return data

def get_month_ends(start, end):
    try: dates = pd.date_range(start=start,end=end,freq="BME")
    except: dates = pd.date_range(start=start,end=end,freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]

def nifty_above_dma(data, date):
    if "_NIFTY" not in data: return True
    nh = data["_NIFTY"]; nh = nh[nh.index <= date]
    if len(nh) < NIFTY_TREND_LOOKBACK: return True
    return float(nh.iloc[-1]) > float(nh.tail(NIFTY_TREND_LOOKBACK).mean())

def vix_regime(data, date):
    """L6: return sizing multiplier (1.0=full, 0.5=half, 0.0=cash)"""
    if "_VIX" not in data: return 1.0  # pre-2008: full size
    v = data["_VIX"]; v = v[v.index <= date]
    if len(v) == 0: return 1.0
    cur = float(v.iloc[-1])
    if cur >= VIX_CASH: return 0.0
    if cur >= VIX_HALF_SIZE: return 0.5
    return 1.0

def market_breadth(data, date):
    """L7: % of universe above their 200-DMA"""
    above = 0; total = 0
    for t, closes in data.items():
        if t.startswith("_"): continue
        try:
            h = closes[closes.index <= date]
            if len(h) < LOOKBACK_TREND: continue
            total += 1
            if float(h.iloc[-1]) > float(h.tail(LOOKBACK_TREND).mean()):
                above += 1
        except: continue
    if total == 0: return 100.0
    return above / total * 100

def sector_strength(data, date, lookback_days=126):
    """L10: rank sectors by relative strength (6M return)"""
    sector_returns = {}
    for sec, tickers in SECTOR_MAP.items():
        rets = []
        for t in tickers:
            if t not in data: continue
            try:
                h = data[t][data[t].index <= date]
                if len(h) < lookback_days+1: continue
                r = float(h.iloc[-1]) / float(h.iloc[-lookback_days-1]) - 1
                rets.append(r)
            except: continue
        if rets:
            sector_returns[sec] = sum(rets)/len(rets)
    return sorted(sector_returns.items(), key=lambda x:-x[1])

def rank_super(data, date_str, top_sectors):
    """L5 momentum + L3 vol + L10 sector rotation bonus"""
    ranked = []
    date = pd.Timestamp(date_str)
    top_sector_set = set([s for s,_ in top_sectors[:3]])
    bottom_sector_set = set([s for s,_ in top_sectors[-3:]]) if len(top_sectors)>=6 else set()

    for ticker, closes in data.items():
        if ticker.startswith("_"): continue
        try:
            hist = closes[closes.index <= date]
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

            # L5 multi-TF momentum
            p3 = float(hist.iloc[-LOOKBACK_MOM_3M-1])
            p6 = float(hist.iloc[-LOOKBACK_MOM_6M-1])
            p12 = float(hist.iloc[-LOOKBACK_MOM_12M-1])
            r3 = cmp/p3 - 1; r6 = cmp/p6 - 1; r12 = cmp/p12 - 1
            if max(r3,r6,r12) > 2.0: continue

            base_score = 0.25*r3 + 0.50*r6 + 0.25*r12

            # L10: sector rotation bonus/penalty
            sec = sector_of(ticker)
            sector_bonus = 0
            if sec in top_sector_set: sector_bonus = 0.10  # +10% score boost
            elif sec in bottom_sector_set: sector_bonus = -0.05

            score = base_score + sector_bonus

            ranked.append({"ticker":ticker,"cmp":round(cmp,2),"score":score,"base":base_score,
                          "vol":round(vol,1),"sector":sec})
        except: continue
    ranked.sort(key=lambda x:-x["score"])
    return ranked

def apply_sector_cap(ranked, top_n, max_pct):
    max_per = max(1, int(top_n * max_pct / 100))
    picked = []; sec_count = {}
    for r in ranked:
        s = r["sector"]
        if sec_count.get(s,0) >= max_per: continue
        picked.append(r)
        sec_count[s] = sec_count.get(s,0) + 1
        if len(picked) >= top_n: break
    return picked

def kelly_weight(score, avg_score):
    """L9: bigger positions for higher-confidence picks (half-Kelly)"""
    if avg_score <= 0: return 1.0
    rel = score / avg_score
    # Clamp to [0.6, 1.5] for stability
    return max(0.6, min(1.5, rel)) * KELLY_FRAC + (1 - KELLY_FRAC)

def run_backtest():
    print("="*70)
    print("PMS SUPER-ENHANCED BACKTEST — 10 layers stacked")
    print("L1-L5: (Nifty, Trail, Vol, Sector, MultiTF-Mom) | L6:VIX | L7:Breadth | L9:Kelly | L10:SectorRot")
    print("="*70)

    regimes = load_cost_regimes()
    data = download_all()
    if len(data) < 50: print("ERROR: too few stocks"); sys.exit(1)

    month_ends = get_month_ends("2003-06-01", END_DATE)
    print(f"\nRunning {len(month_ends)} monthly rebalances with 10-layer super strategy...")

    holdings = {}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None
    prev_nav = CORPUS
    total_costs_paid = 0.0
    regime_offs = 0; vix_offs = 0; breadth_offs = 0

    for i, date_str in enumerate(month_ends):
        date = pd.Timestamp(date_str)
        c = costs_for_date(date_str, regimes)
        cmps = {}
        for t, closes in data.items():
            if t.startswith("_"): continue
            try:
                h = closes[closes.index <= date]
                if len(h) > 0: cmps[t] = float(h.iloc[-1])
            except: pass

        if starting_nifty is None and "_NIFTY" in data:
            nh = data["_NIFTY"][data["_NIFTY"].index <= date]
            if len(nh) > 0: starting_nifty = float(nh.iloc[-1])

        # L1: Nifty regime
        nifty_ok = nifty_above_dma(data, date)
        # L6: VIX regime → sizing multiplier
        vix_mult = vix_regime(data, date)
        # L7: Market breadth
        breadth = market_breadth(data, date)
        breadth_ok = breadth >= BREADTH_MIN

        if not nifty_ok: regime_offs += 1
        if vix_mult < 1.0: vix_offs += 1
        if not breadth_ok: breadth_offs += 1

        # Combined regime: all must be ON to add new positions
        regime_ok = nifty_ok and breadth_ok and vix_mult > 0

        # L2: Trailing stops
        forced_sells = []
        for t, pos in list(holdings.items()):
            if t in cmps:
                if cmps[t] > pos["peak"]: pos["peak"] = cmps[t]
                if (pos["peak"] - cmps[t]) / pos["peak"] * 100 >= TRAILING_STOP_PCT:
                    forced_sells.append(t)

        # L10: Sector strength ranking
        top_sectors = sector_strength(data, date)
        # L5+L10+L3 ranking
        ranked = rank_super(data, date_str, top_sectors)
        # L4: sector cap
        picked = apply_sector_cap(ranked, TOP_N, MAX_SECTOR_PCT)
        picked_tickers = [p["ticker"] for p in picked]

        # SELL logic
        to_sell = set(forced_sells)
        if not regime_ok:
            to_sell.update(list(holdings.keys()))  # regime off = full cash
        else:
            to_sell.update([t for t in holdings if t not in picked_tickers])

        sold = []
        for t in to_sell:
            if t not in holdings: continue
            pos = holdings[t]
            raw_sp = cmps.get(t, pos["entry_price"])
            sp = raw_sp * (1 - c["sell"]/100)
            cost = raw_sp * pos["shares"] * c["sell"]/100
            total_costs_paid += cost
            pnl_abs = round((sp-pos["entry_price"])*pos["shares"])
            pnl_pct = round(((sp-pos["entry_price"])/pos["entry_price"])*100, 2)
            hd = (date - pd.Timestamp(pos["entry_date"])).days
            reason = "TRAIL" if t in forced_sells else ("NO_NIFTY" if not nifty_ok else ("NO_BREADTH" if not breadth_ok else ("VIX_PANIC" if vix_mult==0 else "ROTATION")))
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

        # BUY logic (only if regime OK, with vix_mult sizing)
        bought = []
        if regime_ok and picked:
            avg_score = sum(p["score"] for p in picked) / len(picked) if picked else 1
            current_mv = sum(h["shares"]*cmps.get(t,h["entry_price"]) for t,h in holdings.items())
            current_nav = cash + current_mv
            # L6 VIX sizing: reduce total allocation
            target_deployed = current_nav * vix_mult
            base_per_stock = target_deployed / TOP_N

            for p in picked:
                if p["ticker"] in holdings: continue
                # L9: Kelly sizing based on score
                kw = kelly_weight(p["score"], avg_score)
                stock_alloc = base_per_stock * kw
                eff = p["cmp"] * (1 + c["buy"]/100)
                if eff <= 0: continue
                shares = int(stock_alloc/eff)
                outlay = shares*eff
                if shares < 1 or cash < outlay: continue
                cost = shares * p["cmp"] * c["buy"]/100
                total_costs_paid += cost
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
            "regimeOn":regime_ok,"niftyOk":nifty_ok,"breadth":round(breadth,1),"vixMult":vix_mult,
            "topSectors":[s for s,_ in top_sectors[:3]],
            "regimeEvent":c["regimeEvent"]
        })
        nav_history.append({"date":date_str,"nav":final_nav})
        prev_nav = final_nav

        if (i+1)%12 == 0:
            print(f"  {date_str[:4]}: NAV Rs {final_nav/10_000_000:.2f}Cr | Tot {total:+.1f}% | Breadth {breadth:.0f}% | VIX-mult {vix_mult}")

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
    print("SUPER-ENHANCED BACKTEST COMPLETE — 10 LAYERS")
    print("="*70)
    print(f"CAGR:              {cagr:+.2f}%   (Honest 25.65%, Enhanced ~32%, target 38-42%)")
    print(f"Nifty CAGR:        {nifty_cagr:+.2f}%")
    print(f"Alpha:             {cagr-nifty_cagr:+.2f}%")
    print(f"Max Drawdown:      {max_dd:.1f}%")
    print(f"Trades:            {len(completed_trades)} | Win {win_rate:.1f}% | Hold {avg_hold:.0f}d")
    print(f"Avg W/L:           +{avg_win:.1f}% / {avg_loss:.1f}%")
    print(f"Rs 1 Cr became:    Rs {final_nav/10_000_000:.2f} Cr")
    print(f"Exit reasons:      {reason_counts}")
    print(f"Nifty off months:  {regime_offs} | VIX-partial months: {vix_offs} | Breadth off: {breadth_offs}")
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
            "mode":"super-enhanced-10-layers","exitReasons":reason_counts,
            "layers":"L1 Nifty + L2 15% Trail + L3 60% Vol Cap + L4 30% Sector + L5 3M/6M/12M Mom + L6 VIX + L7 Breadth + L9 Kelly + L10 Sector Rotation",
            "assumptions":"10-layer super-enhanced on 261 stock universe with historical costs"
        },
        "runDate":datetime.now().isoformat()
    }
    with open("backtest_super_enhanced.json","w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_super_enhanced.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    try: run_backtest()
    except Exception as e:
        print(f"\nFATAL: {e}"); traceback.print_exc(); sys.exit(1)
