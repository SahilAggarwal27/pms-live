"""
PMS Algo - Server-side execution via GitHub Actions
Runs daily 9:15 AM IST. Fetches prices, ranks stocks, auto-executes paper trades.
State persisted to data.json (committed back to repo).
"""
import yfinance as yf
import json
import os
from datetime import datetime

UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

TOP_N = 15
CORPUS = 10_000_000  # Rs 1 Cr starting capital

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
        "prices": {}
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

def run_algo():
    print(f"[{datetime.now().isoformat()}] Starting PMS Algo run")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    month = today[:7]

    # Idempotency: don't double-execute same day
    if state.get("lastExecuteDate") == today:
        print(f"Already executed today ({today}). Refreshing prices only.")
        # Still update prices for MTM
        state["lastRun"] = datetime.now().isoformat()

    if state["startDate"] is None:
        state["startDate"] = today

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

    # 3. AUTO-EXECUTE SELLS (holdings that fell out of top-15)
    to_sell = [t for t in state["holdings"] if t not in picked_tickers]
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
        state["completedTrades"].append({
            "ticker": t, "entryDate": pos["entryDate"], "exitDate": today,
            "entryPrice": pos["entryPrice"], "exitPrice": sp,
            "shares": pos["shares"], "holdDays": hd,
            "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
            "outcome": "WIN" if pnl_pct > 0 else "LOSS"
        })
        sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}%)")
        del state["holdings"][t]

    # 4. AUTO-EXECUTE BUYS
    cash = get_cash(state)
    current_nav = cash + get_mv(state, prices_map)
    per_stock = current_nav / TOP_N
    bought = []
    for p in picked:
        if p["ticker"] in state["holdings"]:
            continue
        shares = int(per_stock / p["cmp"])
        cost = shares * p["cmp"]
        if shares < 1 or cash < cost:
            continue
        cash -= cost
        state["holdings"][p["ticker"]] = {
            "shares": shares,
            "entryPrice": p["cmp"],
            "entryDate": today
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

    print(f"\n{'='*60}")
    print(f"EXECUTION SUMMARY - {today}")
    print(f"{'='*60}")
    print(f"BOUGHT ({len(bought)}): {bought}")
    print(f"SOLD ({len(sold)}): {sold}")
    print(f"NAV: Rs {nav/10_000_000:.3f} Cr")
    print(f"Total Return: {total:+.2f}%")
    print(f"Booked P&L: Rs {sum(t['pnlAbs'] for t in state['completedTrades'])/100000:+.2f}L")
    print(f"Holdings: {len(state['holdings'])}")
    print(f"{'='*60}\n")

    save_state(state)

if __name__ == "__main__":
    run_algo()
