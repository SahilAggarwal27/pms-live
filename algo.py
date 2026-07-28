"""
PMS Algo - Server-side execution via GitHub Actions
Runs daily 9:15 AM IST. Fetches prices, checks exits DAILY, rebalances WEEKLY.
State persisted to data.json (committed back to repo).

CADENCE (Design B — crash-safe weekly):
- EXITS run EVERY DAY: -8% hard stop / -22% trailing stop fire the same day,
  so a mid-week crash is still handled. No waiting for the weekly slot.
- RANKING + NEW BUYS run ONCE A WEEK (Monday). This kills daily churn
  (the in/out noise from re-ranking every day) without touching protection.
- MARKET FILTER checked daily; Nifty below 200-DMA blocks new buys regardless.

RULES:
- HARD STOP LOSS: -8% from entry → AUTO SELL (daily)
- TRAILING STOP: -22% from peak → AUTO SELL (daily, lets winners run)
- NO PROFIT CAP: winners run until trailing stop or rank drop
- MAX POSITIONS: 12
- CASH BUFFER: Minimum 10% always
- REBALANCE_WEEKDAY: 0=Mon .. 4=Fri (ranking + buys + rank-drop sells)
"""
import yfinance as yf
import json
import os
from datetime import datetime

UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

# ============ RISK PARAMETERS (TUNABLE) ============
TOP_N = 12                  # Max positions
CORPUS = 10_000_000         # Rs 1 Cr starting capital
HARD_STOP_LOSS_PCT = -8.0   # Exit if down 8% from entry (checked DAILY)
TRAILING_STOP_PCT = 22.0    # Exit if down 22% from peak (checked DAILY)
MIN_CASH_BUFFER_PCT = 10.0  # Keep minimum 10% cash
REBALANCE_WEEKDAY = 0       # 0=Monday. Ranking + new buys + rank-drop sells run only on this day.
# NOTE: Profit target removed. Winners run until trailing stop or rank drop.
#       Stops are DAILY so crashes are handled; only ranking/buys are weekly.
# ===================================================

def default_state():
    return {
        "holdings": {},
        "monthlyJournal": [],
        "completedTrades": [],
        "navHistory": [],
        "startDate": None,
        "lastExecuteDate": None,      # last day ANY trade logic ran (stops or rebalance)
        "lastRebalanceDate": None,    # last day ranking + buys ran
        "lastRun": None,
        "todayExecutedBuys": [],
        "todayExecutedSells": [],
        "prices": {},
        "niftyAbove200DMA": True,     # Market filter
        "niftyPrice": 0,
        "nifty200DMA": 0
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

def fetch_nifty():
    """Fetch Nifty 50 and check if above 200-DMA (market filter)"""
    try:
        df = yf.download("^NSEI", period="1y", progress=False, auto_adjust=True, threads=False)
        if df.empty or len(df) < 200:
            return True, 0, 0  # Default to bullish if can't fetch
        closes = df["Close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()
        cmp = float(closes.iloc[-1])
        dma200 = float(closes.tail(200).mean())
        return cmp > dma200, round(cmp, 2), round(dma200, 2)
    except Exception as e:
        print(f"  Nifty fetch error: {e}")
        return True, 0, 0

def fetch_stock(ticker):
    try:
        df = yf.download(f"{ticker}.NS", period="1y", progress=False, auto_adjust=True, threads=False)
        if df.empty or len(df) < 150:
            return None
        closes = df["Close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()
        if len(closes) < 150:
            return None
        cmp = float(closes.iloc[-1])
        dma200 = float(closes.tail(200).mean())
        p6 = float(closes.iloc[-126]) if len(closes) > 126 else float(closes.iloc[0])
        p1 = float(closes.iloc[-22]) if len(closes) > 22 else cmp
        return {
            "ticker": ticker,
            "cmp": round(cmp, 2),
            "dma200": round(dma200, 2),
            "ret6m": (cmp/p6) - 1,
            "ret1m": (cmp/p1) - 1
        }
    except Exception as e:
        print(f"  {ticker}: {e}")
        return None

def rank_stocks(prices):
    """Rank stocks: above 200-DMA, sorted by (6M return - 0.5 * 1M return)"""
    eligible = [p for p in prices if p["cmp"] > p["dma200"]]
    for p in eligible:
        p["score"] = p["ret6m"] - 0.5 * p["ret1m"]
    return sorted(eligible, key=lambda x: -x["score"])[:TOP_N]

def get_cash(state):
    invested = sum(p["shares"] * p["entryPrice"] for p in state["holdings"].values())
    booked = sum(t["pnlAbs"] for t in state["completedTrades"])
    return CORPUS + booked - invested

def get_mv(state, prices_map):
    return sum(p["shares"] * prices_map.get(t, {"cmp": p["entryPrice"]})["cmp"]
               for t, p in state["holdings"].items())

def get_nav(state, prices_map):
    return get_cash(state) + get_mv(state, prices_map)

def check_exit_conditions(ticker, pos, cmp):
    """
    DAILY exit checks:
    1. HARD STOP LOSS: -8% from entry
    2. TRAILING STOP: -22% from peak (lets winners run)

    NO profit cap. Rank-drop exits are handled separately on rebalance day.
    Returns: (should_exit, exit_reason)
    """
    entry_price = pos["entryPrice"]
    peak_price = pos.get("peakPrice", entry_price)

    # Update peak if current price is higher
    if cmp > peak_price:
        pos["peakPrice"] = cmp
        peak_price = cmp

    pnl_from_entry = ((cmp - entry_price) / entry_price) * 100
    drawdown_from_peak = ((peak_price - cmp) / peak_price) * 100

    if pnl_from_entry <= HARD_STOP_LOSS_PCT:
        return True, f"STOP_LOSS ({pnl_from_entry:+.1f}%)"

    if peak_price > entry_price and drawdown_from_peak >= TRAILING_STOP_PCT:
        return True, f"TRAILING_STOP ({drawdown_from_peak:.1f}% from peak)"

    return False, None

def close_position(state, t, prices_map, today, reason):
    """Book a sell into completedTrades and remove from holdings. Returns display string."""
    pos = state["holdings"][t]
    sp = prices_map[t]["cmp"] if t in prices_map else pos["entryPrice"]
    pnl_abs = round((sp - pos["entryPrice"]) * pos["shares"])
    pnl_pct = round(((sp - pos["entryPrice"]) / pos["entryPrice"]) * 100, 2)
    hd = (datetime.now() - datetime.strptime(pos["entryDate"], "%Y-%m-%d")).days
    state["completedTrades"].append({
        "ticker": t, "entryDate": pos["entryDate"], "exitDate": today,
        "entryPrice": pos["entryPrice"], "exitPrice": sp,
        "shares": pos["shares"], "holdDays": hd,
        "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
        "outcome": "WIN" if pnl_pct > 0 else "LOSS",
        "exitReason": reason
    })
    del state["holdings"][t]
    return f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% → {reason})"

def run_algo():
    print(f"[{datetime.now().isoformat()}] Starting PMS Algo run")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()  # 0=Mon .. 6=Sun
    month = today[:7]
    is_rebalance_day = (weekday == REBALANCE_WEEKDAY)

    if state["startDate"] is None:
        state["startDate"] = today

    # Idempotency: has stop-check already run today?
    stops_already_ran_today = (state.get("lastExecuteDate") == today)
    rebalance_already_ran_today = (state.get("lastRebalanceDate") == today)

    print(f"Weekday={weekday} | Rebalance day={is_rebalance_day} "
          f"(REBALANCE_WEEKDAY={REBALANCE_WEEKDAY})")

    # 0. MARKET FILTER (daily)
    print("Checking Nifty 200-DMA filter...")
    nifty_ok, nifty_price, nifty_dma = fetch_nifty()
    state["niftyAbove200DMA"] = nifty_ok
    state["niftyPrice"] = nifty_price
    state["nifty200DMA"] = nifty_dma
    print(f"  Nifty: {nifty_price} vs 200-DMA: {nifty_dma} → {'✅ BULLISH' if nifty_ok else '🛑 BEARISH'}")

    # 1. FETCH ALL PRICES (needed daily for stop checks + MTM)
    print(f"Fetching {len(UNIVERSE)} stocks...")
    prices = []
    for i, ticker in enumerate(UNIVERSE):
        if (i+1) % 10 == 0:
            print(f"  {i+1}/{len(UNIVERSE)} fetched")
        p = fetch_stock(ticker)
        if p:
            prices.append(p)
    print(f"Successfully fetched {len(prices)}/{len(UNIVERSE)} stocks")

    prices_map = {p["ticker"]: p for p in prices}
    state["prices"] = prices_map

    if len(prices) < 20:
        print("ERROR: Too few stocks fetched. Aborting execution.")
        save_state(state)
        return

    # 2. RANK (only meaningful on rebalance day, but compute for logging)
    picked = rank_stocks(prices)
    picked_tickers = [p["ticker"] for p in picked]
    if is_rebalance_day:
        print(f"Top-{TOP_N} picks (rebalance): {picked_tickers}")

    sold = []
    bought = []

    # ============================================================
    # 3. DAILY EXITS — stop loss & trailing stop (EVERY DAY)
    # ============================================================
    if not stops_already_ran_today:
        for t, pos in list(state["holdings"].items()):
            cmp = prices_map.get(t, {}).get("cmp", pos["entryPrice"])
            should_exit, reason = check_exit_conditions(t, pos, cmp)
            if should_exit:
                print(f"  📢 {t}: DAILY EXIT → {reason}")
                sold.append(close_position(state, t, prices_map, today, reason))
    else:
        print("Stops already checked today — skipping duplicate exit pass.")

    # ============================================================
    # 4. WEEKLY REBALANCE — rank-drop sells + new buys (Mon only)
    # ============================================================
    if is_rebalance_day and not rebalance_already_ran_today:
        # 4a. Rank-drop sells: holdings no longer in top N
        for t in list(state["holdings"].keys()):
            if t not in picked_tickers:
                print(f"  📢 {t}: REBALANCE EXIT → Fell out of top {TOP_N}")
                sold.append(close_position(state, t, prices_map, today, "RANK_DROP"))

        # 4b. New buys (respect market filter, cash buffer, position cap)
        cash = get_cash(state)
        current_nav = cash + get_mv(state, prices_map)
        min_cash_required = current_nav * (MIN_CASH_BUFFER_PCT / 100)
        available_for_buys = max(0, cash - min_cash_required)

        if not nifty_ok:
            print(f"🛑 MARKET FILTER: Nifty below 200-DMA. NO NEW BUYS this rebalance.")
            available_for_buys = 0

        current_positions = len(state["holdings"])
        max_new_buys = max(0, TOP_N - current_positions)
        print(f"  Cash: ₹{cash/100000:.1f}L | Min buffer: ₹{min_cash_required/100000:.1f}L "
              f"| Available: ₹{available_for_buys/100000:.1f}L")
        print(f"  Positions: {current_positions}/{TOP_N} | Can buy: {max_new_buys}")

        per_stock = available_for_buys / max(1, max_new_buys) if max_new_buys > 0 else 0
        for p in picked:
            if p["ticker"] in state["holdings"]:
                continue
            if len(bought) >= max_new_buys or available_for_buys <= 0:
                break
            shares = int(per_stock / p["cmp"])
            cost = shares * p["cmp"]
            if shares < 1 or available_for_buys < cost:
                continue
            available_for_buys -= cost
            state["holdings"][p["ticker"]] = {
                "shares": shares,
                "entryPrice": p["cmp"],
                "entryDate": today,
                "peakPrice": p["cmp"]
            }
            bought.append(p["ticker"])

        state["lastRebalanceDate"] = today
    elif not is_rebalance_day:
        print(f"Not rebalance day — holding positions, no new buys. "
              f"(Next rebalance: weekday {REBALANCE_WEEKDAY})")

    # 5. UPDATE MONTHLY JOURNAL
    nav = get_nav(state, prices_map)
    prev_nav = state["navHistory"][-1]["nav"] if state["navHistory"] else CORPUS
    mom = ((nav / prev_nav) - 1) * 100
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
            "month": month, "date": today,
            "nav": round(nav),
            "navCr": round(nav / 10_000_000, 3),
            "monthReturn": round(mom, 2),
            "totalReturn": round(total, 2),
            "cash": round(get_cash(state)),
            "holdingsCount": len(state["holdings"]),
            "bought": bought,
            "sold": sold,
            "held": [t for t in state["holdings"] if t not in bought],
            "winsThisMonth": 0,
            "lossesThisMonth": 0
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
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    print(f"\n{'='*60}")
    print(f"EXECUTION SUMMARY - {today} ({'REBALANCE' if is_rebalance_day else 'stops-only'})")
    print(f"{'='*60}")
    print(f"MARKET: Nifty {'✅ BULLISH' if nifty_ok else '🛑 BEARISH'} ({nifty_price} vs 200-DMA {nifty_dma})")
    print(f"BOUGHT ({len(bought)}): {bought}")
    print(f"SOLD ({len(sold)}): {sold}")
    print(f"NAV: Rs {nav/10_000_000:.3f} Cr")
    print(f"Total Return: {total:+.2f}%")
    print(f"Booked P&L: Rs {sum(t['pnlAbs'] for t in state['completedTrades'])/100000:+.2f}L")
    print(f"Holdings: {len(state['holdings'])}/{TOP_N}")
    print(f"Cash: Rs {get_cash(state)/100000:.1f}L ({get_cash(state)/nav*100:.1f}%)")
    print(f"Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"{'='*60}\n")

    save_state(state)

if __name__ == "__main__":
    run_algo()
