"""
PMS Algo - Server-side execution via GitHub Actions
Runs on weekdays. State persisted to data.json (committed back to repo).

STRATEGY = PURE RANK-AND-REBALANCE MOMENTUM (aligned to enhanced_backtest.py)
  This is how India's best momentum PMSs (e.g. Capitalmind Adaptive Momentum,
  Wright, Nifty 200 Momentum 30) actually run. There is NO per-stock stop-loss
  and NO take-profit target. The monthly re-ranking IS the profit booking:
  winners are held as long as they stay top-ranked; losers are cut when they
  fall out of the ranks. The only downside brake is a portfolio-level regime
  filter (go to cash when Nifty < 200-DMA).

  L1: Nifty regime filter  — liquidate to cash when Nifty < 200-DMA, no buys.
  L3: Volatility cap        — exclude 6M annualized realized vol > 60%.
  L4: Sector cap            — max 30% of book (per TOP_N) per sector.
  L5: Multi-timeframe momentum — 0.25*3M + 0.50*6M + 0.25*12M composite score.
  + Cost model from cost_history.json (brokerage+GST+STT+stamp+slippage).

REMOVED (were the cause of "stops kept hitting, no profit booking"):
  - The -8% daily hard stop. It fired on normal momentum noise, ejecting fresh
    buys as locked-in LOSSES before they could set a peak above entry.
  - The 15% trailing stop. In a rank-driven book it only churned winners.
  Both are gone. Exits now happen ONLY at the monthly rebalance (rank-drop or
  regime-off), so there is no daily exit pass and no daily universe fetch.

BUFFER: buy into the top TOP_N, but HOLD an existing name until it falls out of
  the top HOLD_RANK. This hysteresis band cuts turnover and tax drag — again,
  standard practice at the top momentum PMSs.

CADENCE:
  - RANKING + rank-drop sells + new buys run MONTHLY (last weekday-run of each
    calendar month). lastRebalanceMonth guard prevents a double-run.
  - On non-rebalance runs the algo only marks-to-market held names and updates
    NAV; it places no trades.
  - Market regime is evaluated at rebalance and drives liquidate-to-cash.
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
TOP_N = 15                  # book size / buy into top N
HOLD_RANK = 25              # hysteresis: hold an existing name until it exits top HOLD_RANK
CORPUS = 10_000_000
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
        "cash": CORPUS,
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
                # ---- one-time migration for pre-rank-only state files ----
                # Old files inflated entryPrice by buy costs and tracked no cash
                # field. If cash is missing/None, reconstruct it from CORPUS,
                # booked P&L and current invested-at-entry so NAV stays sane.
                if s.get("cash") is None:
                    invested = sum(p["shares"] * p["entryPrice"] for p in s["holdings"].values())
                    booked = sum(t.get("pnlAbs", 0) for t in s["completedTrades"])
                    s["cash"] = CORPUS + booked - invested
                # drop any stale peakPrice keys — no longer used
                for p in s["holdings"].values():
                    p.pop("peakPrice", None)
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

# ---- Data fetch: full history per stock (needed for vol + multi-TF) ----
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
    """L3 vol cap + L5 multi-timeframe momentum. Returns full ranked list of dicts."""
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
    """L4: cap stocks per sector while filling to top_n."""
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

def get_mv(state, cmps):
    return sum(p["shares"] * cmps.get(t, p["entryPrice"]) for t, p in state["holdings"].items())

def get_nav(state, cmps):
    return state["cash"] + get_mv(state, cmps)

def close_position(state, t, cmps, today, reason, sell_cost_pct):
    """Sell a holding. entryPrice is the RAW fill; costs are tracked once in
    totalCostsPaid and netted out of proceeds here. Cash is credited with the
    net proceeds."""
    pos = state["holdings"][t]
    raw = cmps.get(t, pos["entryPrice"])
    cost = raw * pos["shares"] * sell_cost_pct/100
    proceeds = raw * pos["shares"] - cost           # net cash received
    state["totalCostsPaid"] += cost
    state["cash"] += proceeds
    pnl_abs = round((raw - pos["entryPrice"]) * pos["shares"] - cost)
    pnl_pct = round(((raw * (1 - sell_cost_pct/100)) - pos["entryPrice"]) / pos["entryPrice"] * 100, 2)
    hd = (datetime.now() - datetime.strptime(pos["entryDate"], "%Y-%m-%d")).days
    state["completedTrades"].append({
        "ticker": t, "entryDate": pos["entryDate"], "exitDate": today,
        "entryPrice": pos["entryPrice"], "exitPrice": round(raw, 2),
        "shares": pos["shares"], "holdDays": hd,
        "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
        "outcome": "WIN" if pnl_pct > 0 else "LOSS", "exitReason": reason
    })
    del state["holdings"][t]
    return f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% -> {reason})"

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
    print(f"[{datetime.now().isoformat()}] Starting PMS Algo run (pure rank-only)")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()
    month = today[:7]

    if state["startDate"] is None:
        state["startDate"] = today

    rebalance_done_this_month = (state.get("lastRebalanceMonth") == month)
    do_rebalance = is_last_trading_run_of_month(today, weekday) and not rebalance_done_this_month

    print(f"Weekday={weekday} | Month={month} | Rebalance this run={do_rebalance} "
          f"(done this month={rebalance_done_this_month})")

    regimes = load_cost_regimes()
    c = costs_for_date(today, regimes)
    print(f"Costs today: buy {c['buy']:.3f}% | sell {c['sell']:.3f}%")

    # Market filter (evaluated every run; only acted on at rebalance)
    nifty_ok, nifty_price, nifty_dma = fetch_nifty()
    state["niftyAbove200DMA"] = nifty_ok
    state["niftyPrice"] = nifty_price
    state["nifty200DMA"] = nifty_dma
    print(f"Nifty: {nifty_price} vs 200-DMA {nifty_dma} -> {'BULLISH' if nifty_ok else 'BEARISH'}")

    # Fetch histories. With no per-stock stops there is no daily exit pass, so
    # on non-rebalance runs we only need current prices for held names (MTM).
    # Full universe is fetched only when rebalancing.
    tickers_to_fetch = set(state["holdings"].keys())
    if do_rebalance:
        tickers_to_fetch = set(UNIVERSE) | tickers_to_fetch

    print(f"Fetching {len(tickers_to_fetch)} tickers "
          f"({'full rebalance' if do_rebalance else 'held-only MTM'})...")
    histories = {}
    for i, t in enumerate(sorted(tickers_to_fetch)):
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{len(tickers_to_fetch)}")
        h = fetch_history(t)
        if h is not None:
            histories[t] = h

    cmps = {t: float(h.iloc[-1]) for t, h in histories.items()}
    for t, pos in state["holdings"].items():
        cmps.setdefault(t, pos["entryPrice"])
    state["prices"] = {t: {"cmp": round(v, 2)} for t, v in cmps.items()}

    sold, bought = [], []

    # ---- MONTHLY REBALANCE (the ONLY place trades happen) ----
    if do_rebalance:
        ranked = rank_enhanced({t: h for t, h in histories.items() if t in UNIVERSE})
        # Buy set: top TOP_N after sector cap.
        picked = apply_sector_cap(ranked, TOP_N, MAX_SECTOR_PCT)
        picked_tickers = [p["ticker"] for p in picked]
        # Hold set: hysteresis band — names still inside top HOLD_RANK (post
        # sector cap) are kept even if they slipped below TOP_N.
        hold_ok = set(t["ticker"] for t in apply_sector_cap(ranked, HOLD_RANK, 100.0))
        print(f"Rebalance top-{TOP_N}: {picked_tickers}")

        if not nifty_ok:
            # Regime OFF -> sell everything, go to cash (matches backtest)
            print("REGIME OFF (Nifty<200DMA): liquidating to cash, no buys.")
            for t in list(state["holdings"].keys()):
                sold.append(close_position(state, t, cmps, today, "REGIME_OFF", c["sell"]))
        else:
            # Rank-drop sells: exit only names that fell out of the HOLD band.
            for t in list(state["holdings"].keys()):
                if t not in hold_ok:
                    sold.append(close_position(state, t, cmps, today, "RANK_DROP", c["sell"]))

            # Buys — target equal weight across the FINAL book of TOP_N names.
            # Size each new buy against nav/TOP_N (not cash/TOP_N), so already-
            # held names count toward the book and we actually fill to TOP_N.
            nav_now = state["cash"] + get_mv(state, cmps)
            per_stock = nav_now / TOP_N
            for p in picked:
                if p["ticker"] in state["holdings"]:
                    continue
                raw = p["cmp"]
                buy_cost_rate = c["buy"] / 100
                # shares such that raw*shares + costs <= per_stock, bounded by cash
                budget = min(per_stock, state["cash"])
                shares = int(budget / (raw * (1 + buy_cost_rate)))
                if shares < 1:
                    continue
                gross = raw * shares
                cost = gross * buy_cost_rate
                outlay = gross + cost
                if state["cash"] < outlay:
                    continue
                state["totalCostsPaid"] += cost
                state["cash"] -= outlay
                state["holdings"][p["ticker"]] = {
                    "shares": shares,
                    "entryPrice": round(raw, 2),   # RAW fill, not cost-inflated
                    "entryDate": today
                }
                bought.append(p["ticker"])

        state["lastRebalanceMonth"] = month
    else:
        print("Not a rebalance run — MTM only, no ranking/trades.")

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
        existing["cash"] = round(state["cash"])
        existing["holdingsCount"] = len(state["holdings"])
        existing["held"] = [t for t in state["holdings"] if t not in existing["bought"]]
    else:
        state["monthlyJournal"].append({
            "month": month, "date": today, "nav": round(nav),
            "navCr": round(nav / 10_000_000, 3), "monthReturn": round(mom, 2),
            "totalReturn": round(total, 2), "cash": round(state["cash"]),
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
    print(f"SUMMARY - {today} ({'REBALANCE' if do_rebalance else 'MTM-only'})")
    print(f"{'='*60}")
    print(f"MARKET: Nifty {'BULLISH' if nifty_ok else 'BEARISH'} ({nifty_price} vs {nifty_dma})")
    print(f"BOUGHT ({len(bought)}): {bought}")
    print(f"SOLD ({len(sold)}): {sold}")
    print(f"NAV: Rs {nav/10_000_000:.3f} Cr | Total {total:+.2f}%")
    print(f"Booked P&L: Rs {sum(t['pnlAbs'] for t in state['completedTrades'])/100000:+.2f}L")
    print(f"Costs paid to date: Rs {state['totalCostsPaid']/100000:.2f}L")
    print(f"Holdings: {len(state['holdings'])}/{TOP_N} | Cash {state['cash']/nav*100:.1f}%")
    print(f"Win Rate: {win_rate:.1f}% ({wins}W/{losses}L)")
    print(f"{'='*60}\n")

    save_state(state)

if __name__ == "__main__":
    run_algo()
