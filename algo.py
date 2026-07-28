"""
PMS Algo - Server-side execution via GitHub Actions
Runs daily 9:15 AM IST. State persisted to data.json (committed back to repo).

ALIGNED TO BACKTEST (enhanced_backtest.py) — same strategy, now live:
  L1: Nifty regime filter — no buys / go to cash when Nifty < 200-DMA
  L2: Trailing stop 15% from peak (matches backtest)
  L3: Volatility cap — exclude 6M realized vol > 60%
  L4: Sector cap — max 30% (per TOP_N) per sector
  L5: Multi-timeframe momentum — 0.25*3M + 0.50*6M + 0.25*12M
  + Cost model from cost_history.json (brokerage+GST+STT+stamp+slippage)

DELIBERATE DIFFERENCE FROM BACKTEST (more conservative, intentional):
  + DAILY -8% HARD STOP on fresh positions. The 15% trailing stop cannot
    catch a new buy that craters before setting a peak above entry
    (the THERMAX case). This -8% floor runs every day. Backtest lacks it.

CADENCE:
  - EXITS (hard stop + trailing) checked EVERY DAY → crash-safe.
  - RANKING + rank-drop sells + new buys run MONTHLY (last run of each
    calendar month), matching the backtest's monthly rebalance.
  - Market filter checked daily.
"""
import yfinance as yf
import numpy as np
import json
import os
from datetime import datetime

# ---- Universe: 261 stocks, identical to enhanced_backtest.py ----
WINNERS = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]
NIFTY50 = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","HINDUNILVR","ITC","LT","KOTAKBANK","SBIN","AXISBANK","BAJFINANCE","BHARTIARTL","ASIANPAINT","MARUTI","HDFCLIFE","M&M","TATASTEEL","SUNPHARMA","NTPC","POWERGRID","ULTRACEMCO","ONGC","TITAN","DRREDDY","NESTLEIND","ADANIENT","ADANIPORTS","JSWSTEEL","TATAMOTORS","TATACONSUM","APOLLOHOSP","CIPLA","INDUSINDBK","GRASIM","HEROMOTOCO","BRITANNIA","EICHERMOT","DIVISLAB","BAJAJFINSV","BPCL","COALINDIA","HINDALCO","TECHM","WIPRO","BAJAJ-AUTO","SBILIFE","HCLTECH","SHRIRAMFIN","UPL"]
BLOWUPS = ["YESBANK","IDEA","JPASSOCIAT","SUZLON","RCOM","IDBI","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK","JPPOWER","IBREALEST","GVKPIL","GMRINFRA","IRB"]
LAGGARDS = ["BHEL","BEML","CONCOR","MOIL","MMTC","MRPL","HINDCOPPER","SAIL","NHPC","NLCINDIA","IOC","HPCL","OIL","NBCC","IRCTC","IRFC","RVNL","INDIGO","SPICEJET","VSTIND","GODREJIND","DABUR","EMAMILTD","COLPAL","MARICO","GODREJCP","BATA","RELAXO","INDHOTEL","LEMONTREE","MAHLIFE","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD","BLUEDART","GATI","VRLLOG","MAHLOG","TCI","ALLCARGO","MAZDOCK","COCHINSHIP","BANDHANBNK","RBLBANK","EQUITASBNK","UJJIVAN","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT","HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM","VEDL","APLAPOLLO","JINDALSAW","WELCORP","TORNTPHARM","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","PFIZER","GLAXO","SANOFI","AJANTPHARM","IPCALAB","ERISLIFE","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS","TVSMOTOR","ESCORTS","ASHOKLEY","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD","MMFSL","JYOTHYLAB","GILLETTE","VARUN","WESTLIFE","DEVYANI","BIKAJI","GODFRYPHLP","UBL","RADICO","ADANIPOWER","TORNTPOWER","JSWENERGY","NCC","HGINFRA","KNRCON"]
UNIVERSE = sorted(set(WINNERS + NIFTY50 + BLOWUPS + LAGGARDS))

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

# ============ PARAMETERS (aligned to enhanced_backtest.py) ============
TOP_N = 15                  # matches backtest
CORPUS = 10_000_000
TRAILING_STOP_PCT = 15.0    # L2 — matches backtest
HARD_STOP_LOSS_PCT = -8.0   # extra daily floor (backtest lacks this — intentional)
MAX_VOLATILITY = 60.0       # L3 — 6M annualized realized vol cap (%)
MAX_SECTOR_PCT = 30.0       # L4 — max % of book per sector
MAX_MOMENTUM = 2.0          # skip data-error outliers (>200% 12M)
SLIPPAGE_PER_SIDE = 0.30    # % per side
# L5 momentum lookbacks (trading days)
MOM_3M, MOM_6M, MOM_12M, TREND = 63, 126, 252, 200
# =====================================================================

def default_state():
    return {
        "holdings": {}, "monthlyJournal": [], "completedTrades": [],
        "navHistory": [], "startDate": None,
        "lastExecuteDate": None, "lastRebalanceMonth": None, "lastRun": None,
        "todayExecutedBuys": [], "todayExecutedSells": [],
        "prices": {}, "niftyAbove200DMA": True, "niftyPrice": 0, "nifty200DMA": 0,
        "totalCostsPaid": 0.0
    }

def load_state():
    if os.path.exists("data.json"):
        try:
            with open("data.json") as f:
                s = json.load(f)
                for k, v in default_state().items():
                    if k not in s:
                        s[k] = v
                return s
        except Exception as e:
            print(f"Warning: could not load data.json ({e}), using default")
    return default_state()

def save_state(state):
    with open("data.json", "w") as f:
        json.dump(state, f, indent=2, default=str)

# ---- Cost model (from cost_history.json) ----
def load_cost_regimes():
    try:
        with open("cost_history.json") as f:
            return sorted(json.load(f)["regimes"], key=lambda r: r["startDate"])
    except Exception:
        return []

def costs_for_date(date_str, regimes):
    if not regimes:
        return {"buy": 0.75, "sell": 0.75}
    active = regimes[0]
    for r in regimes:
        if r["startDate"] <= date_str:
            active = r
        else:
            break
    b = active["brokeragePerSide"]; gst = active["gstOnBrokerage"] / 100
    return {
        "buy":  b*(1+gst) + SLIPPAGE_PER_SIDE + active["sttBuyDelivery"]  + active["stampBuy"] + active["exchangeSebi"],
        "sell": b*(1+gst) + SLIPPAGE_PER_SIDE + active["sttSellDelivery"] + active["exchangeSebi"]
    }

# ---- Data fetch: full 1y daily history per stock (needed for vol + multi-TF) ----
def fetch_history(ticker):
    try:
        df = yf.download(f"{ticker}.NS", period="15mo", progress=False, auto_adjust=True, threads=False)
        if df.empty:
            return None
        closes = df["Close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()
        if len(closes) < MOM_12M:
            return None
        return closes
    except Exception as e:
        print(f"  {ticker}: {e}")
        return None

def fetch_nifty():
    try:
        df = yf.download("^NSEI", period="15mo", progress=False, auto_adjust=True, threads=False)
        if df.empty:
            return True, 0, 0
        closes = df["Close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()
        if len(closes) < TREND:
            return True, 0, 0
        cmp = float(closes.iloc[-1]); dma = float(closes.tail(TREND).mean())
        return cmp > dma, round(cmp, 2), round(dma, 2)
    except Exception as e:
        print(f"  Nifty fetch error: {e}")
        return True, 0, 0

def realized_vol(closes):
    if len(closes) < 30:
        return 100.0
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return 100.0
    return float(rets.std() * np.sqrt(252) * 100)

def rank_enhanced(histories):
    """L3 vol cap + L5 multi-timeframe momentum. Returns ranked list of dicts."""
    ranked = []
    for ticker, closes in histories.items():
        try:
            cmp = float(closes.iloc[-1])
            dma200 = float(closes.tail(TREND).mean())
            if cmp <= dma200:
                continue
            vol = realized_vol(closes.tail(MOM_6M))
            if vol > MAX_VOLATILITY:
                continue
            p3 = float(closes.iloc[-MOM_3M-1])
            p6 = float(closes.iloc[-MOM_6M-1])
            p12 = float(closes.iloc[-MOM_12M-1])
            r3, r6, r12 = cmp/p3 - 1, cmp/p6 - 1, cmp/p12 - 1
            if max(r3, r6, r12) > MAX_MOMENTUM:
                continue
            score = 0.25*r3 + 0.50*r6 + 0.25*r12
            ranked.append({"ticker": ticker, "cmp": round(cmp, 2), "score": score,
                           "vol": round(vol, 1), "sector": sector_of(ticker)})
        except Exception:
            continue
    ranked.sort(key=lambda x: -x["score"])
    return ranked

def apply_sector_cap(ranked, top_n, max_pct):
    """L4: cap stocks per sector."""
    max_per_sector = max(1, int(top_n * max_pct / 100))
    picked, sector_count = [], {}
    for r in ranked:
        s = r["sector"]
        if sector_count.get(s, 0) >= max_per_sector:
            continue
        picked.append(r)
        sector_count[s] = sector_count.get(s, 0) + 1
        if len(picked) >= top_n:
            break
    return picked

def get_cash(state):
    invested = sum(p["shares"] * p["entryPrice"] for p in state["holdings"].values())
    booked = sum(t["pnlAbs"] for t in state["completedTrades"])
    return CORPUS + booked - invested

def get_mv(state, cmps):
    return sum(p["shares"] * cmps.get(t, p["entryPrice"]) for t, p in state["holdings"].items())

def get_nav(state, cmps):
    return get_cash(state) + get_mv(state, cmps)

def check_daily_exit(pos, cmp):
    """Daily: -8% hard stop, then 15% trailing. Returns (exit?, reason)."""
    entry = pos["entryPrice"]
    peak = pos.get("peakPrice", entry)
    if cmp > peak:
        pos["peakPrice"] = cmp
        peak = cmp
    pnl = (cmp - entry) / entry * 100
    dd_peak = (peak - cmp) / peak * 100
    if pnl <= HARD_STOP_LOSS_PCT:
        return True, f"STOP_LOSS ({pnl:+.1f}%)"
    if peak > entry and dd_peak >= TRAILING_STOP_PCT:
        return True, f"TRAILING_STOP ({dd_peak:.1f}% from peak)"
    return False, None

def close_position(state, t, cmps, today, reason, sell_cost_pct):
    pos = state["holdings"][t]
    raw = cmps.get(t, pos["entryPrice"])
    sp = raw * (1 - sell_cost_pct/100)           # net of sell costs
    state["totalCostsPaid"] += raw * pos["shares"] * sell_cost_pct/100
    pnl_abs = round((sp - pos["entryPrice"]) * pos["shares"])
    pnl_pct = round((sp - pos["entryPrice"]) / pos["entryPrice"] * 100, 2)
    hd = (datetime.now() - datetime.strptime(pos["entryDate"], "%Y-%m-%d")).days
    state["completedTrades"].append({
        "ticker": t, "entryDate": pos["entryDate"], "exitDate": today,
        "entryPrice": pos["entryPrice"], "exitPrice": round(sp, 2),
        "shares": pos["shares"], "holdDays": hd,
        "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
        "outcome": "WIN" if pnl_pct > 0 else "LOSS", "exitReason": reason
    })
    del state["holdings"][t]
    return f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% → {reason})"

def is_last_trading_run_of_month(today, weekday):
    """
    Monthly rebalance trigger: run rebalance on the last weekday-run we see
    for the calendar month. Approximated as: today is within last 3 days of
    month AND it's a weekday. lastRebalanceMonth guard prevents double-run.
    """
    import calendar
    y, m, d = map(int, today.split("-"))
    last_day = calendar.monthrange(y, m)[1]
    return weekday < 5 and (last_day - d) <= 2

def run_algo():
    print(f"[{datetime.now().isoformat()}] Starting PMS Algo run")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()
    month = today[:7]

    if state["startDate"] is None:
        state["startDate"] = today

    stops_ran_today = (state.get("lastExecuteDate") == today)
    rebalance_done_this_month = (state.get("lastRebalanceMonth") == month)
    do_rebalance = is_last_trading_run_of_month(today, weekday) and not rebalance_done_this_month

    print(f"Weekday={weekday} | Month={month} | Rebalance this run={do_rebalance} "
          f"(done this month={rebalance_done_this_month})")

    regimes = load_cost_regimes()
    c = costs_for_date(today, regimes)
    print(f"Costs today: buy {c['buy']:.3f}% | sell {c['sell']:.3f}%")

    # Market filter
    nifty_ok, nifty_price, nifty_dma = fetch_nifty()
    state["niftyAbove200DMA"] = nifty_ok
    state["niftyPrice"] = nifty_price
    state["nifty200DMA"] = nifty_dma
    print(f"Nifty: {nifty_price} vs 200-DMA {nifty_dma} → {'BULLISH' if nifty_ok else 'BEARISH'}")

    # Fetch histories (only need full histories on rebalance; on plain days we
    # still need current prices for held names + MTM). Fetch held always; fetch
    # full universe only when rebalancing to save time.
    tickers_to_fetch = set(state["holdings"].keys())
    if do_rebalance:
        tickers_to_fetch = set(UNIVERSE) | tickers_to_fetch

    print(f"Fetching {len(tickers_to_fetch)} tickers "
          f"({'full rebalance' if do_rebalance else 'held-only'})...")
    histories = {}
    for i, t in enumerate(sorted(tickers_to_fetch)):
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{len(tickers_to_fetch)}")
        h = fetch_history(t)
        if h is not None:
            histories[t] = h

    cmps = {t: float(h.iloc[-1]) for t, h in histories.items()}
    # keep last-known prices for any held name that failed to fetch
    for t, pos in state["holdings"].items():
        cmps.setdefault(t, pos["entryPrice"])
    state["prices"] = {t: {"cmp": round(v, 2)} for t, v in cmps.items()}

    sold, bought = [], []

    # ---- DAILY EXITS (every day) ----
    if not stops_ran_today:
        for t, pos in list(state["holdings"].items()):
            cmp = cmps.get(t, pos["entryPrice"])
            hit, reason = check_daily_exit(pos, cmp)
            if hit:
                print(f"  📢 {t}: DAILY EXIT → {reason}")
                sold.append(close_position(state, t, cmps, today, reason, c["sell"]))
    else:
        print("Stops already ran today — skipping duplicate pass.")

    # ---- MONTHLY REBALANCE ----
    if do_rebalance:
        ranked = rank_enhanced({t: h for t, h in histories.items() if t in UNIVERSE})
        picked = apply_sector_cap(ranked, TOP_N, MAX_SECTOR_PCT)
        picked_tickers = [p["ticker"] for p in picked]
        print(f"Rebalance top-{TOP_N}: {picked_tickers}")

        if not nifty_ok:
            # Regime OFF → sell everything, go to cash (matches backtest)
            print("🛑 REGIME OFF (Nifty<200DMA): liquidating to cash, no buys.")
            for t in list(state["holdings"].keys()):
                sold.append(close_position(state, t, cmps, today, "REGIME_OFF", c["sell"]))
        else:
            # Rank-drop sells
            for t in list(state["holdings"].keys()):
                if t not in picked_tickers:
                    sold.append(close_position(state, t, cmps, today, "RANK_DROP", c["sell"]))
            # Buys — equal weight to TOP_N, net of buy costs
            cash = get_cash(state)
            nav_now = cash + get_mv(state, cmps)
            per_stock = nav_now / TOP_N
            for p in picked:
                if p["ticker"] in state["holdings"]:
                    continue
                eff = p["cmp"] * (1 + c["buy"]/100)   # effective buy price incl costs
                shares = int(per_stock / eff)
                outlay = shares * eff
                if shares < 1 or cash < outlay:
                    continue
                state["totalCostsPaid"] += shares * p["cmp"] * c["buy"]/100
                cash -= outlay
                state["holdings"][p["ticker"]] = {
                    "shares": shares, "entryPrice": round(eff, 2),
                    "entryDate": today, "peakPrice": p["cmp"]
                }
                bought.append(p["ticker"])

        state["lastRebalanceMonth"] = month
    else:
        print("Not a rebalance run — holding, no ranking/buys.")

    # ---- JOURNAL + NAV ----
    nav = get_nav(state, cmps)
    prev_nav = state["navHistory"][-1]["nav"] if state["navHistory"] else CORPUS
    mom = ((nav / prev_nav) - 1) * 100 if prev_nav else 0
    total = ((nav / CORPUS) - 1) * 100

    existing = next((m for m in state["monthlyJournal"] if m["month"] == month), None)
    if existing:
        existing["bought"] = list(set(existing["bought"] + bought))
        existing["sold"] += sold
        existing["nav"] = round(nav)
        existing["navCr"] = round(nav / 10_000_000, 3)
        existing["monthReturn"] = round(mom, 2)
        existing["totalReturn"] = round(total, 2)
        existing["cash"] = round(get_cash(state))
        existing["holdingsCount"] = len(state["holdings"])
        existing["held"] = [t for t in state["holdings"] if t not in existing["bought"]]
    else:
        state["monthlyJournal"].append({
            "month": month, "date": today, "nav": round(nav),
            "navCr": round(nav / 10_000_000, 3), "monthReturn": round(mom, 2),
            "totalReturn": round(total, 2), "cash": round(get_cash(state)),
            "holdingsCount": len(state["holdings"]), "bought": bought,
            "sold": sold, "held": [t for t in state["holdings"] if t not in bought],
            "winsThisMonth": 0, "lossesThisMonth": 0
        })

    for m in state["monthlyJournal"]:
        m["winsThisMonth"] = sum(1 for t in state["completedTrades"]
                                 if t["exitDate"].startswith(m["month"]) and t["pnlPct"] > 0)
        m["lossesThisMonth"] = sum(1 for t in state["completedTrades"]
                                   if t["exitDate"].startswith(m["month"]) and t["pnlPct"] <= 0)

    state["navHistory"].append({"date": today, "nav": nav})
    state["todayExecutedBuys"] = bought
    state["todayExecutedSells"] = sold
    state["lastExecuteDate"] = today
    state["lastRun"] = datetime.now().isoformat()

    wins = sum(1 for t in state["completedTrades"] if t["pnlPct"] > 0)
    losses = sum(1 for t in state["completedTrades"] if t["pnlPct"] <= 0)
    win_rate = wins / (wins + losses) * 100 if (wins + losses) else 0

    print(f"\n{'='*60}")
    print(f"SUMMARY - {today} ({'REBALANCE' if do_rebalance else 'stops-only'})")
    print(f"{'='*60}")
    print(f"MARKET: Nifty {'BULLISH' if nifty_ok else 'BEARISH'} ({nifty_price} vs {nifty_dma})")
    print(f"BOUGHT ({len(bought)}): {bought}")
    print(f"SOLD ({len(sold)}): {sold}")
    print(f"NAV: Rs {nav/10_000_000:.3f} Cr | Total {total:+.2f}%")
    print(f"Booked P&L: Rs {sum(t['pnlAbs'] for t in state['completedTrades'])/100000:+.2f}L")
    print(f"Costs paid to date: Rs {state['totalCostsPaid']/100000:.2f}L")
    print(f"Holdings: {len(state['holdings'])}/{TOP_N} | Cash {get_cash(state)/nav*100:.1f}%")
    print(f"Win Rate: {win_rate:.1f}% ({wins}W/{losses}L)")
    print(f"{'='*60}\n")

    save_state(state)

if __name__ == "__main__":
    run_algo()
