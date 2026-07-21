"""
PMS ENHANCED BACKTEST — 5 layers of improvement stacked

Layers over Honest backtest:
  L1: NIFTY REGIME FILTER — hold cash when Nifty < 200-DMA
  L2: TRAILING STOP LOSS — exit any stock down 15% from its peak (per-position)
  L3: QUALITY PROXY — exclude stocks with 6M realized vol > 60% (data-driven)
  L4: SECTOR CAP — max 30% (5 stocks) per sector
  L5: MULTI-TIMEFRAME MOMENTUM — weighted 3M + 6M + 12M rank score

Expected: 25% -> 32-35% CAGR
"""
import json
import os
import sys
import traceback
import time
from datetime import datetime

import pandas as pd
import numpy as np
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
except ImportError:
    SESSION = None

# Same universe as honest backtest (261 stocks)
WINNERS = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]
NIFTY50 = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","HINDUNILVR","ITC","LT","KOTAKBANK","SBIN","AXISBANK","BAJFINANCE","BHARTIARTL","ASIANPAINT","MARUTI","HDFCLIFE","M&M","TATASTEEL","SUNPHARMA","NTPC","POWERGRID","ULTRACEMCO","ONGC","TITAN","DRREDDY","NESTLEIND","ADANIENT","ADANIPORTS","JSWSTEEL","TATAMOTORS","TATACONSUM","APOLLOHOSP","CIPLA","INDUSINDBK","GRASIM","HEROMOTOCO","BRITANNIA","EICHERMOT","DIVISLAB","BAJAJFINSV","BPCL","COALINDIA","HINDALCO","TECHM","WIPRO","BAJAJ-AUTO","SBILIFE","HCLTECH","SHRIRAMFIN","UPL"]
BLOWUPS = ["YESBANK","IDEA","JPASSOCIAT","SUZLON","RCOM","IDBI","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK","JPPOWER","IBREALEST","GVKPIL","GMRINFRA","IRB"]
LAGGARDS = ["BHEL","BEML","CONCOR","MOIL","MMTC","MRPL","HINDCOPPER","SAIL","NHPC","NLCINDIA","IOC","HPCL","OIL","NBCC","IRCTC","IRFC","RVNL","INDIGO","SPICEJET","VSTIND","GODREJIND","DABUR","EMAMILTD","COLPAL","MARICO","GODREJCP","BATA","RELAXO","INDHOTEL","LEMONTREE","MAHLIFE","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD","BLUEDART","GATI","VRLLOG","MAHLOG","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","BANDHANBNK","RBLBANK","EQUITASBNK","UJJIVAN","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK","ULTRACEMCO","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT","HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM","VEDL","APLAPOLLO","JINDALSAW","WELCORP","TORNTPHARM","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","PFIZER","GLAXO","SANOFI","AJANTPHARM","IPCALAB","ERISLIFE","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS","TVSMOTOR","ESCORTS","ASHOKLEY","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD","MMFSL","JYOTHYLAB","GILLETTE","VARUN","WESTLIFE","DEVYANI","BIKAJI","GODFRYPHLP","UBL","RADICO","ADANIPOWER","TORNTPOWER","JSWENERGY","NCC","HGINFRA","KNRCON"]
UNIVERSE = sorted(set(WINNERS + NIFTY50 + BLOWUPS + LAGGARDS))

# SECTOR MAP for L4: sector cap
SECTOR_MAP = {
    "IT": ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","INFY","TCS","WIPRO","HCLTECH","TECHM"],
    "BANK": ["HDFCBANK","ICICIBANK","KOTAKBANK","SBIN","AXISBANK","INDUSINDBK","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","YESBANK","IDBI","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK","BANDHANBNK","RBLBANK","EQUITASBNK","UJJIVAN","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK"],
    "NBFC": ["BAJFINANCE","BAJAJFINSV","SBILIFE","HDFCLIFE","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","SHRIRAMFIN","MMFSL"],
    "AUTO": ["MARUTI","M&M","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ESCORTS","ASHOKLEY","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD"],
    "PHARMA": ["SUNPHARMA","CIPLA","DRREDDY","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","DIVISLAB","APOLLOHOSP","TORNTPHARM","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","PFIZER","GLAXO","SANOFI","AJANTPHARM","IPCALAB","ERISLIFE","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS"],
    "FMCG": ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","EMAMILTD","JYOTHYLAB","GILLETTE","VBL","VARUN","JUBLFOOD","WESTLIFE","DEVYANI","BIKAJI","GODFRYPHLP","UBL","RADICO","TATACONSUM","BATA","RELAXO"],
    "OIL_GAS": ["RELIANCE","ONGC","BPCL","IOC","HPCL","GAIL","IGL","OIL","PETRONET","GUJGASLTD","MGL","MRPL"],
    "METAL": ["TATASTEEL","JSWSTEEL","JINDALSTEL","SAIL","NMDC","VEDL","HINDCOPPER","HINDZINC","NATIONALUM","HINDALCO","MOIL","APLAPOLLO","JINDALSAW","WELCORP"],
    "CEMENT": ["ULTRACEMCO","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT","HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM"],
    "POWER": ["NTPC","POWERGRID","TATAPOWER","ADANIPOWER","TORNTPOWER","JSWENERGY","JPPOWER","NHPC","NLCINDIA"],
    "INFRA": ["LT","ADANIENT","ADANIPORTS","GRASIM","NBCC","IRCTC","IRFC","RVNL","INDIGO","SPICEJET","BLUEDART","GATI","VRLLOG","MAHLOG","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","NCC","HGINFRA","KNRCON","JPASSOCIAT","GVKPIL","GMRINFRA","IRB","BHEL","BEML","CONCOR","BEL","HAL","SIEMENS","CUMMINSIND","THERMAX","CGPOWER","DIXON"],
    "CAPITAL_GOODS": [],
    "TELECOM": ["BHARTIARTL","IDEA","RCOM"],
    "REALESTATE": ["GODREJPROP","OBEROIRLTY","PRESTIGE","MAHLIFE","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD","IBREALEST","INDHOTEL","LEMONTREE"],
    "CHEMICAL": ["PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","UPL"],
    "CONSUMER_DUR": ["ASIANPAINT","TITAN","HAVELLS","VOLTAS","CROMPTON","PAGEIND","TRENT"],
    "EXCHANGE": ["IEX","CDSL","BSE","CAMS","MCX","INDIAMART","NAUKRI"],
    "OTHER": ["COALINDIA","VSTIND","GODREJIND","MMTC","SUZLON"]
}

def sector_of(ticker):
    for sec, stocks in SECTOR_MAP.items():
        if ticker in stocks:
            return sec
    return "OTHER"

# CONFIG
TOP_N = 15
CORPUS = 10_000_000
SLIPPAGE_PER_SIDE = 0.30
MIN_LISTING_DAYS = 3 * 365
MAX_6M_MOMENTUM = 2.0
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# LAYER PARAMETERS
NIFTY_TREND_LOOKBACK = 200  # L1
TRAILING_STOP_PCT = 15.0    # L2 (%)
MAX_VOLATILITY = 60.0       # L3 (%) annualized realized vol cap
MAX_SECTOR_PCT = 30.0       # L4 (%)
LOOKBACK_MOM_3M = 63        # L5
LOOKBACK_MOM_6M = 126
LOOKBACK_MOM_12M = 252
LOOKBACK_TREND = 200


def load_cost_regimes():
    try:
        with open("cost_history.json") as f:
            return sorted(json.load(f)["regimes"], key=lambda r: r["startDate"])
    except:
        return []

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
            if len(closes) < 60: return None
            return closes
        except: 
            if a < retries-1: time.sleep(1)
    return None

def download_all():
    print(f"Downloading {len(UNIVERSE)} stocks + Nifty benchmark...")
    data = {}
    for i, t in enumerate(UNIVERSE):
        if (i+1)%25==0 or i==0: print(f"  {i+1}/{len(UNIVERSE)} ({len(data)} OK)")
        c = download_ticker(f"{t}.NS")
        if c is not None: data[t] = c
    print(f"OK: {len(data)}/{len(UNIVERSE)}")
    n = download_ticker("^NSEI")
    if n is not None: data["_NIFTY"] = n
    return data

def get_month_ends(start, end):
    try: dates = pd.date_range(start=start,end=end,freq="BME")
    except: dates = pd.date_range(start=start,end=end,freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]

def nifty_above_dma(data, date):
    """L1: True if Nifty above its 200-DMA"""
    if "_NIFTY" not in data: return True  # fallback: allow trading
    nh = data["_NIFTY"]
    nh = nh[nh.index <= date]
    if len(nh) < NIFTY_TREND_LOOKBACK: return True
    cmp = float(nh.iloc[-1])
    dma = float(nh.tail(NIFTY_TREND_LOOKBACK).mean())
    return cmp > dma

def realized_vol(prices):
    """L3: annualized realized vol from daily returns"""
    if len(prices) < 30: return 100.0  # unknown → high vol → excluded
    rets = prices.pct_change().dropna()
    if len(rets) == 0: return 100.0
    return float(rets.std() * np.sqrt(252) * 100)

def rank_enhanced(data, date_str):
    """L5: multi-timeframe momentum + L3: vol filter"""
    ranked = []
    date = pd.Timestamp(date_str)
    for ticker, closes in data.items():
        if ticker == "_NIFTY": continue
        try:
            hist = closes[closes.index <= date]
            if len(hist) < LOOKBACK_MOM_12M: continue
            if (date - hist.index[0]).days < MIN_LISTING_DAYS: continue
            cmp = float(hist.iloc[-1])
            dma200 = float(hist.tail(LOOKBACK_TREND).mean())
            if cmp <= dma200: continue

            # L3 QUALITY: volatility cap
            recent_prices = hist.tail(126)  # 6M
            vol = realized_vol(recent_prices)
            if vol > MAX_VOLATILITY: continue

            # L5 Multi-TF momentum
            p3 = float(hist.iloc[-LOOKBACK_MOM_3M-1])
            p6 = float(hist.iloc[-LOOKBACK_MOM_6M-1])
            p12 = float(hist.iloc[-LOOKBACK_MOM_12M-1])
            r3 = cmp/p3 - 1
            r6 = cmp/p6 - 1
            r12 = cmp/p12 - 1

            # Skip extreme outliers (data errors)
            if max(r3,r6,r12) > MAX_6M_MOMENTUM: continue

            # Weighted score: 3M=25%, 6M=50%, 12M=25%
            score = 0.25*r3 + 0.50*r6 + 0.25*r12

            ranked.append({"ticker":ticker,"cmp":round(cmp,2),"score":score,
                          "ret6m":r6,"vol":round(vol,1),"sector":sector_of(ticker)})
        except: continue
    ranked.sort(key=lambda x:-x["score"])
    return ranked

def apply_sector_cap(ranked, top_n, max_pct):
    """L4: cap max stocks per sector"""
    max_per_sector = max(1, int(top_n * max_pct / 100))
    picked = []
    sector_count = {}
    for r in ranked:
        s = r["sector"]
        if sector_count.get(s,0) >= max_per_sector: continue
        picked.append(r)
        sector_count[s] = sector_count.get(s,0) + 1
        if len(picked) >= top_n: break
    return picked

def run_backtest():
    print("="*70)
    print(f"PMS ENHANCED BACKTEST (5 layers) | {START_DATE} -> {END_DATE}")
    print(f"L1: Nifty regime | L2: {TRAILING_STOP_PCT}% trail | L3: {MAX_VOLATILITY}% vol cap | L4: {MAX_SECTOR_PCT}% sector | L5: multi-TF mom")
    print("="*70)

    regimes = load_cost_regimes()
    data = download_all()
    if len(data) < 50: print("ERROR: too few stocks"); sys.exit(1)

    month_ends = get_month_ends("2003-06-01", END_DATE)
    print(f"\nRunning {len(month_ends)} monthly rebalances with 5-layer strategy...")

    holdings = {}  # ticker -> {shares, entry, entryDate, peak}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None
    prev_nav = CORPUS
    total_costs_paid = 0.0
    regime_offs = 0  # count months in cash due to L1

    for i, date_str in enumerate(month_ends):
        date = pd.Timestamp(date_str)
        c = costs_for_date(date_str, regimes)
        cmps = {}
        for t, closes in data.items():
            if t == "_NIFTY": continue
            try:
                h = closes[closes.index <= date]
                if len(h) > 0: cmps[t] = float(h.iloc[-1])
            except: pass

        if starting_nifty is None and "_NIFTY" in data:
            nh = data["_NIFTY"]; nh = nh[nh.index <= date]
            if len(nh) > 0: starting_nifty = float(nh.iloc[-1])

        # L1: Check Nifty regime
        regime_ok = nifty_above_dma(data, date)
        if not regime_ok: regime_offs += 1

        # L2: Update peak prices and check trailing stops
        forced_sells = []
        for t, pos in list(holdings.items()):
            if t in cmps:
                if cmps[t] > pos["peak"]: pos["peak"] = cmps[t]
                drop_from_peak = (pos["peak"] - cmps[t]) / pos["peak"] * 100
                if drop_from_peak >= TRAILING_STOP_PCT:
                    forced_sells.append(t)

        # Rank candidates using L3+L5
        ranked = rank_enhanced(data, date_str)
        # Apply L4 sector cap
        picked = apply_sector_cap(ranked, TOP_N, MAX_SECTOR_PCT)
        picked_tickers = [p["ticker"] for p in picked]

        # SELL: (1) trailing stops forced, (2) not in top ranks, (3) regime off
        to_sell = set(forced_sells)
        if regime_ok:
            to_sell.update([t for t in holdings if t not in picked_tickers])
        else:
            # Regime OFF: sell everything (go to cash)
            to_sell.update(list(holdings.keys()))

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
            reason = "TRAIL_STOP" if t in forced_sells else ("REGIME_OFF" if not regime_ok else "TOP_ROTATION")
            completed_trades.append({
                "ticker":t,"entryDate":pos["entry_date"],"exitDate":date_str,
                "entryPrice":pos["entry_price"],"exitPrice":round(sp,2),
                "shares":pos["shares"],"holdDays":hd,
                "pnlAbs":pnl_abs,"pnlPct":pnl_pct,
                "outcome":"WIN" if pnl_pct>0 else "LOSS",
                "exitReason": reason
            })
            sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% via {reason[:6]})")
            cash += pos["shares"]*sp
            del holdings[t]

        # BUY: only if regime is ON
        bought = []
        if regime_ok:
            current_mv = sum(h["shares"]*cmps.get(t,h["entry_price"]) for t,h in holdings.items())
            current_nav = cash + current_mv
            per_stock = current_nav / TOP_N
            for p in picked:
                if p["ticker"] in holdings: continue
                eff = p["cmp"] * (1 + c["buy"]/100)
                if eff <= 0: continue
                shares = int(per_stock/eff)
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
            "regimeOn": regime_ok,
            "regimeCostBuy":round(c["buy"],3),"regimeCostSell":round(c["sell"],3),
            "regimeEvent":c["regimeEvent"]
        })
        nav_history.append({"date":date_str,"nav":final_nav})
        prev_nav = final_nav

        if (i+1)%12 == 0:
            print(f"  {date_str[:4]}: NAV Rs {final_nav/10_000_000:.2f}Cr | Tot {total:+.1f}% | Regime {'ON' if regime_ok else 'OFF'}")

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
    trail_exits = sum(1 for t in completed_trades if t.get("exitReason")=="TRAIL_STOP")
    regime_exits = sum(1 for t in completed_trades if t.get("exitReason")=="REGIME_OFF")
    top_exits = sum(1 for t in completed_trades if t.get("exitReason")=="TOP_ROTATION")

    nifty_cagr = 0
    if "_NIFTY" in data and starting_nifty:
        nifty_end = float(data["_NIFTY"].iloc[-1])
        nifty_cagr = (pow(nifty_end/starting_nifty, 1/years)-1)*100

    print("\n"+"="*70)
    print("ENHANCED BACKTEST COMPLETE — 5 LAYERS APPLIED")
    print("="*70)
    print(f"CAGR:              {cagr:+.2f}%   (Honest was 25.65%)")
    print(f"Nifty CAGR:        {nifty_cagr:+.2f}%")
    print(f"Alpha:             {cagr-nifty_cagr:+.2f}%")
    print(f"Max Drawdown:      {max_dd:.1f}%")
    print(f"Trades:            {len(completed_trades)} | Win {win_rate:.1f}% | Hold {avg_hold:.0f}d")
    print(f"Avg W/L:           +{avg_win:.1f}% / {avg_loss:.1f}%")
    print(f"Rs 1 Cr became:    Rs {final_nav/10_000_000:.2f} Cr")
    print(f"Exit reasons:      Trailing {trail_exits} | Regime off {regime_exits} | Top rotation {top_exits}")
    print(f"Months in cash:    {regime_offs}/{len(month_ends)} ({regime_offs/len(month_ends)*100:.0f}%)")
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
            "mode":"enhanced-5-layers",
            "trailingStopExits":trail_exits,"regimeOffExits":regime_exits,
            "monthsInCash":regime_offs,
            "layers":"L1 Nifty regime + L2 15% trailing stop + L3 60% vol cap + L4 30% sector cap + L5 3M/6M/12M momentum",
            "assumptions":"5-layer enhancement on 261 stock universe"
        },
        "runDate":datetime.now().isoformat()
    }
    with open("backtest_enhanced.json","w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_enhanced.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    try: run_backtest()
    except Exception as e:
        print(f"\nFATAL: {e}"); traceback.print_exc(); sys.exit(1)
