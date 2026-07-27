"""
PMS Algo - Server-side execution via GitHub Actions
Runs daily 9:15 AM IST. Fetches prices, ranks stocks, auto-executes paper trades.
State persisted to data.json (committed back to repo).

RULES (Updated):
- HARD STOP LOSS: -8% from entry → AUTO SELL
- TRAILING STOP: -15% from peak → AUTO SELL  
- PROFIT TARGET: +10% → AUTO SELL (book winner!)
- MARKET FILTER: Only buy when Nifty > 200-DMA
- MAX POSITIONS: 12 (not 15)
- CASH BUFFER: Minimum 10% always
"""
import yfinance as yf
import json
import os
from datetime import datetime

UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

# ============ RISK PARAMETERS (TUNABLE) ============
TOP_N = 12                  # Max positions (was 15)
CORPUS = 10_000_000         # Rs 1 Cr starting capital
HARD_STOP_LOSS_PCT = -8.0   # Exit if down 8% from entry
TRAILING_STOP_PCT = 15.0    # Exit if down 15% from peak
PROFIT_TARGET_PCT = 10.0    # Book profits at +10%
MIN_CASH_BUFFER_PCT = 10.0  # Keep minimum 10% cash
# ===================================================

def default_state():
    return {
        "holdings": {},
        "monthlyJournal": [],
        "completedTrades": [],
        "navHistory": [],
        "startDate": None,
        "lastExecuteDate": None,
        "lastRun": None,
        "todayExecutedBuys": [],
        "todayExecutedSells": [],
        "prices": {},
        "niftyAbove200DMA": True,  # Market filter
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
    Check if position should be exited based on:
    1. HARD STOP LOSS: -8% from entry
    2. TRAILING STOP: -15% from peak
    3. PROFIT TARGET: +10% (book winner!)
    
    Returns: (should_exit, exit_reason)
    """
    entry_price = pos["entryPrice"]
    peak_price = pos.get("peakPrice", entry_price)
    
    # Update peak if current price is higher
    if cmp > peak_price:
        pos["peakPrice"] = cmp
        peak_price = cmp
    
    # Calculate P&L percentages
    pnl_from_entry = ((cmp - entry_price) / entry_price) * 100
    drawdown_from_peak = ((peak_price - cmp) / peak_price) * 100
    
    # 1. HARD STOP LOSS: -8% from entry
    if pnl_from_entry <= HARD_STOP_LOSS_PCT:
        return True, f"STOP_LOSS ({pnl_from_entry:+.1f}%)"
    
    # 2. TRAILING STOP: -15% from peak (only if we were up at some point)
    if peak_price > entry_price and drawdown_from_peak >= TRAILING_STOP_PCT:
        return True, f"TRAILING_STOP ({drawdown_from_peak:.1f}% from peak)"
    
    # 3. PROFIT TARGET: +10% (book winner!)
    if pnl_from_entry >= PROFIT_TARGET_PCT:
        return True, f"PROFIT_BOOKED (+{pnl_from_entry:.1f}%)"
    
    return False, None

def run_algo():
    print(f"[{datetime.now().isoformat()}] Starting PMS Algo run")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    month = today[:7]

    # Idempotency: don't double-execute same day
    if state.get("lastExecuteDate") == today:
        print(f"Already executed today ({today}). Refreshing prices only.")
        state["lastRun"] = datetime.now().isoformat()

    if state["startDate"] is None:
        state["startDate"] = today

    # 0. CHECK MARKET FILTER (Nifty > 200-DMA)
    print("Checking Nifty 200-DMA filter...")
    nifty_ok, nifty_price, nifty_dma = fetch_nifty()
    state["niftyAbove200DMA"] = nifty_ok
    state["niftyPrice"] = nifty_price
    state["nifty200DMA"] = nifty_dma
    print(f"  Nifty: {nifty_price} vs 200-DMA: {nifty_dma} → {'✅ BULLISH' if nifty_ok else '🛑 BEARISH'}")

    # 1. FETCH ALL PRICES
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

    # 2. RANK & IDENTIFY SIGNALS
    picked = rank_stocks(prices)
    picked_tickers = [p["ticker"] for p in picked]
    print(f"Top-{TOP_N} picks: {picked_tickers}")

    # If already executed today, just save updated prices and exit
    if state.get("lastExecuteDate") == today:
        save_state(state)
        print("Prices refreshed for MTM. Skipping trades (already ran today).")
        return

    # ============================================================
    # 3. AUTO-EXECUTE SELLS (NEW LOGIC WITH STOP LOSS & TARGETS)
    # ============================================================
    to_sell = []
    sell_reasons = {}
    
    for t, pos in list(state["holdings"].items()):
        cmp = prices_map.get(t, {}).get("cmp", pos["entryPrice"])
        
        # Check exit conditions (stop loss, trailing stop, profit target)
        should_exit, reason = check_exit_conditions(t, pos, cmp)
        
        if should_exit:
            to_sell.append(t)
            sell_reasons[t] = reason
            print(f"  📢 {t}: EXIT triggered → {reason}")
        elif t not in picked_tickers:
            # Also sell if fell out of top rankings
            to_sell.append(t)
            sell_reasons[t] = "RANK_DROP"
            print(f"  📢 {t}: EXIT triggered → Fell out of top {TOP_N}")
    
    sold = []
    for t in to_sell:
        pos = state["holdings"][t]
        if t in prices_map:
            sp = prices_map[t]["cmp"]
        else:
            sp = pos["entryPrice"]
        pnl_abs = round((sp - pos["entryPrice"]) * pos["shares"])
        pnl_pct = round(((sp - pos["entryPrice"]) / pos["entryPrice"]) * 100, 2)
        hd = (datetime.now() - datetime.strptime(pos["entryDate"], "%Y-%m-%d")).days
        exit_reason = sell_reasons.get(t, "UNKNOWN")
        
        state["completedTrades"].append({
            "ticker": t, "entryDate": pos["entryDate"], "exitDate": today,
            "entryPrice": pos["entryPrice"], "exitPrice": sp,
            "shares": pos["shares"], "holdDays": hd,
            "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
            "outcome": "WIN" if pnl_pct > 0 else "LOSS",
            "exitReason": exit_reason
        })
        sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}% → {exit_reason})")
        del state["holdings"][t]

    # ============================================================
    # 4. AUTO-EXECUTE BUYS (WITH MARKET FILTER & CASH BUFFER)
    # ============================================================
    cash = get_cash(state)
    current_nav = cash + get_mv(state, prices_map)
    
    # Check cash buffer - don't buy if cash would go below 10%
    min_cash_required = current_nav * (MIN_CASH_BUFFER_PCT / 100)
    available_for_buys = max(0, cash - min_cash_required)
    
    # Check market filter - don't buy new positions if Nifty below 200-DMA
    if not nifty_ok:
        print(f"🛑 MARKET FILTER: Nifty below 200-DMA. NO NEW BUYS today.")
        available_for_buys = 0
    
    # Check position limit
    current_positions = len(state["holdings"])
    max_new_buys = max(0, TOP_N - current_positions)
    
    print(f"  Cash: ₹{cash/100000:.1f}L | Min buffer: ₹{min_cash_required/100000:.1f}L | Available: ₹{available_for_buys/100000:.1f}L")
    print(f"  Current positions: {current_positions}/{TOP_N} | Can buy: {max_new_buys}")
    
    per_stock = available_for_buys / max(1, max_new_buys) if max_new_buys > 0 else 0
    
    bought = []
    for p in picked:
        if p["ticker"] in state["holdings"]:
            continue
        if len(bought) >= max_new_buys:
            break
        if available_for_buys <= 0:
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
            "peakPrice": p["cmp"]  # Track peak for trailing stop
        }
        bought.append(p["ticker"])

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

    # Update win/loss counts for this month
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

    # Calculate stats
    wins = sum(1 for t in state["completedTrades"] if t["pnlPct"] > 0)
    losses = sum(1 for t in state["completedTrades"] if t["pnlPct"] <= 0)
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    print(f"\n{'='*60}")
    print(f"EXECUTION SUMMARY - {today}")
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
