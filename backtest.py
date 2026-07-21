"""
PMS 25-Year Backtest
Runs same Quality+Momentum strategy on 2000-2026 history.
Produces backtest_data.json which the dashboard displays.
Full year -> month -> trades drill-down.
"""
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta

# ----- CONFIG -----
UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

TOP_N = 15
CORPUS = 10_000_000  # Rs 1 Cr
LOOKBACK_MOMENTUM = 126  # 6 months
LOOKBACK_TREND = 200  # 200-DMA
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")


def download_all_history():
    """Download 25-year daily prices for all stocks + Nifty."""
    print(f"Downloading history {START_DATE} to {END_DATE}...")
    all_data = {}
    for i, ticker in enumerate(UNIVERSE):
        try:
            print(f"  [{i+1}/{len(UNIVERSE)}] {ticker}")
            df = yf.download(f"{ticker}.NS", start=START_DATE, end=END_DATE,
                             progress=False, auto_adjust=True, threads=False)
            if df.empty or len(df) < LOOKBACK_TREND + 30:
                print(f"    skipped (only {len(df)} rows)")
                continue
            closes = df["Close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            all_data[ticker] = closes.dropna()
        except Exception as e:
            print(f"    error: {e}")
    print(f"Downloaded {len(all_data)}/{len(UNIVERSE)} stocks")

    # Nifty for benchmark
    try:
        nifty = yf.download("^NSEI", start=START_DATE, end=END_DATE,
                            progress=False, auto_adjust=True, threads=False)
        n_closes = nifty["Close"]
        if hasattr(n_closes, "columns"):
            n_closes = n_closes.iloc[:, 0]
        all_data["_NIFTY"] = n_closes.dropna()
    except Exception as e:
        print(f"Nifty error: {e}")
    return all_data


def get_month_ends(start, end):
    """Get last business day of each month."""
    dates = pd.date_range(start=start, end=end, freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]


def rank_at_date(all_data, date_str):
    """Rank stocks at given date based on 6M momentum + above 200-DMA filter."""
    ranked = []
    date = pd.Timestamp(date_str)
    for ticker, closes in all_data.items():
        if ticker == "_NIFTY":
            continue
        # Get closes up to this date
        hist = closes[closes.index <= date]
        if len(hist) < LOOKBACK_TREND:
            continue
        cmp = float(hist.iloc[-1])
        dma200 = float(hist.tail(LOOKBACK_TREND).mean())
        if cmp <= dma200:
            continue
        if len(hist) < LOOKBACK_MOMENTUM + 1:
            continue
        p6 = float(hist.iloc[-LOOKBACK_MOMENTUM-1])
        ret6m = (cmp / p6) - 1
        ranked.append({"ticker": ticker, "cmp": round(cmp, 2), "ret6m": ret6m,
                       "dma200": round(dma200, 2)})
    ranked.sort(key=lambda x: -x["ret6m"])
    return ranked[:TOP_N]


def run_backtest():
    print("=" * 70)
    print(f"PMS 25-YEAR BACKTEST | {START_DATE} → {END_DATE}")
    print("=" * 70)

    all_data = download_all_history()
    if len(all_data) < 20:
        print("ERROR: Not enough data downloaded")
        return

    month_ends = get_month_ends("2000-06-01", END_DATE)  # start after 6mo warm-up
    print(f"Running {len(month_ends)} monthly rebalances...")

    # Backtest state
    holdings = {}  # ticker -> {shares, entry_price, entry_date}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None

    prev_nav = CORPUS

    for i, date_str in enumerate(month_ends):
        # Get current prices from history
        date = pd.Timestamp(date_str)
        cmps = {}
        for t, closes in all_data.items():
            if t == "_NIFTY":
                continue
            hist = closes[closes.index <= date]
            if len(hist) > 0:
                cmps[t] = float(hist.iloc[-1])

        # Nifty for benchmark
        if starting_nifty is None:
            nifty_hist = all_data.get("_NIFTY", pd.Series()).loc[:date]
            if len(nifty_hist) > 0:
                starting_nifty = float(nifty_hist.iloc[-1])

        # Rank stocks
        picked = rank_at_date(all_data, date_str)
        picked_tickers = [p["ticker"] for p in picked]

        # SELL: exit holdings not in top-15
        to_sell = [t for t in list(holdings.keys()) if t not in picked_tickers]
        sold = []
        for t in to_sell:
            pos = holdings[t]
            if t not in cmps:
                sp = pos["entry_price"]
            else:
                sp = cmps[t]
            pnl_abs = round((sp - pos["entry_price"]) * pos["shares"])
            pnl_pct = round(((sp - pos["entry_price"]) / pos["entry_price"]) * 100, 2)
            hd = (date - pd.Timestamp(pos["entry_date"])).days
            completed_trades.append({
                "ticker": t, "entryDate": pos["entry_date"], "exitDate": date_str,
                "entryPrice": pos["entry_price"], "exitPrice": sp,
                "shares": pos["shares"], "holdDays": hd,
                "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
                "outcome": "WIN" if pnl_pct > 0 else "LOSS"
            })
            sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}%)")
            cash += pos["shares"] * sp
            del holdings[t]

        # BUY: enter new top-15 picks
        current_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                         for t, h in holdings.items())
        current_nav = cash + current_mv
        per_stock = current_nav / TOP_N
        bought = []
        for p in picked:
            if p["ticker"] in holdings:
                continue
            shares = int(per_stock / p["cmp"])
            cost = shares * p["cmp"]
            if shares < 1 or cash < cost:
                continue
            cash -= cost
            holdings[p["ticker"]] = {
                "shares": shares,
                "entry_price": p["cmp"],
                "entry_date": date_str
            }
            bought.append(p["ticker"])

        # Compute NAV
        final_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                       for t, h in holdings.items())
        final_nav = cash + final_mv
        mom = ((final_nav / prev_nav) - 1) * 100 if prev_nav > 0 else 0
        total = ((final_nav / CORPUS) - 1) * 100

        month_str = date_str[:7]
        held_this = [t for t in holdings if t not in bought]

        wins_month = sum(1 for tr in completed_trades
                         if tr["exitDate"].startswith(month_str) and tr["pnlPct"] > 0)
        losses_month = sum(1 for tr in completed_trades
                           if tr["exitDate"].startswith(month_str) and tr["pnlPct"] <= 0)

        monthly_journal.append({
            "month": month_str, "date": date_str,
            "nav": round(final_nav),
            "navCr": round(final_nav / 10_000_000, 3),
            "monthReturn": round(mom, 2),
            "totalReturn": round(total, 2),
            "cash": round(cash),
            "holdingsCount": len(holdings),
            "bought": bought,
            "sold": sold,
            "held": held_this,
            "winsThisMonth": wins_month,
            "lossesThisMonth": losses_month
        })
        nav_history.append({"date": date_str, "nav": final_nav})
        prev_nav = final_nav

        if (i+1) % 12 == 0:
            year = date_str[:4]
            print(f"  {year} complete: NAV Rs {final_nav/10_000_000:.3f}Cr, Total {total:+.1f}%")

    # Summary stats
    if not nav_history:
        print("ERROR: No history generated")
        return

    final_nav = nav_history[-1]["nav"]
    total_return = ((final_nav / CORPUS) - 1) * 100

    start_date = pd.Timestamp(nav_history[0]["date"])
    end_date = pd.Timestamp(nav_history[-1]["date"])
    years = (end_date - start_date).days / 365.25
    cagr = (pow(final_nav / CORPUS, 1/years) - 1) * 100 if years > 0 else 0

    # Max drawdown
    peak = CORPUS
    max_dd = 0
    for h in nav_history:
        if h["nav"] > peak:
            peak = h["nav"]
        dd = (h["nav"] - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    wins = sum(1 for t in completed_trades if t["pnlPct"] > 0)
    win_rate = (wins / len(completed_trades) * 100) if completed_trades else 0
    avg_win = sum(t["pnlPct"] for t in completed_trades if t["pnlPct"] > 0) / max(1, wins)
    losses = [t for t in completed_trades if t["pnlPct"] <= 0]
    avg_loss = sum(t["pnlPct"] for t in losses) / max(1, len(losses))
    avg_hold = sum(t["holdDays"] for t in completed_trades) / max(1, len(completed_trades))

    # Nifty return for comparison
    nifty_series = all_data.get("_NIFTY", pd.Series())
    if len(nifty_series) > 0 and starting_nifty:
        nifty_end = float(nifty_series.iloc[-1])
        nifty_total = ((nifty_end / starting_nifty) - 1) * 100
        nifty_cagr = (pow(nifty_end / starting_nifty, 1/years) - 1) * 100
    else:
        nifty_total = 0
        nifty_cagr = 0

    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)
    print(f"Period:            {nav_history[0]['date']} to {nav_history[-1]['date']} ({years:.1f} years)")
    print(f"Strategy CAGR:     {cagr:+.2f}%")
    print(f"Strategy Total:    {total_return:+.1f}%")
    print(f"Nifty CAGR:        {nifty_cagr:+.2f}%")
    print(f"Alpha (CAGR):      {cagr - nifty_cagr:+.2f}%")
    print(f"Max Drawdown:      {max_dd:.1f}%")
    print(f"Total Trades:      {len(completed_trades)}")
    print(f"Win Rate:          {win_rate:.1f}%")
    print(f"Avg Win:           {avg_win:+.1f}%")
    print(f"Avg Loss:          {avg_loss:+.1f}%")
    print(f"Avg Hold Days:     {avg_hold:.0f}")
    print(f"Rs 1 Cr became:    Rs {final_nav/10_000_000:.2f} Cr")
    print("=" * 70)

    # Save backtest_data.json
    output = {
        "monthlyJournal": monthly_journal,
        "completedTrades": completed_trades,
        "navHistory": [{"date": h["date"], "nav": round(h["nav"])} for h in nav_history],
        "holdings": {t: {"shares": h["shares"], "entryPrice": h["entry_price"], "entryDate": h["entry_date"]}
                     for t, h in holdings.items()},
        "startDate": nav_history[0]["date"],
        "endDate": nav_history[-1]["date"],
        "summary": {
            "years": round(years, 1),
            "cagr": round(cagr, 2),
            "totalReturn": round(total_return, 1),
            "niftyCagr": round(nifty_cagr, 2),
            "alpha": round(cagr - nifty_cagr, 2),
            "maxDrawdown": round(max_dd, 1),
            "totalTrades": len(completed_trades),
            "winRate": round(win_rate, 1),
            "avgWin": round(avg_win, 1),
            "avgLoss": round(avg_loss, 1),
            "avgHoldDays": round(avg_hold, 0),
            "finalNavCr": round(final_nav / 10_000_000, 2)
        },
        "runDate": datetime.now().isoformat()
    }

    with open("backtest_data.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_data.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    run_backtest()
