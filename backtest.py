"""
PMS 25-Year Backtest — robust version for GitHub Actions
Uses curl_cffi session to bypass Yahoo blocking datacenter IPs.
"""
import json
import os
import sys
import traceback
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

# Try to use curl_cffi (browser-fingerprint) to avoid Yahoo blocking
try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
    print("Using curl_cffi session (browser fingerprint)")
except ImportError:
    SESSION = None
    print("curl_cffi not available - using default yfinance session")

# ----- CONFIG -----
UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

TOP_N = 15
CORPUS = 10_000_000
LOOKBACK_MOMENTUM = 126
LOOKBACK_TREND = 200
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")


def download_ticker(ticker, max_retries=3):
    """Robust download with retries and multiple fallbacks."""
    for attempt in range(max_retries):
        try:
            kwargs = dict(start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True, threads=False)
            if SESSION:
                kwargs["session"] = SESSION
            df = yf.download(ticker, **kwargs)
            if df is None or df.empty:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue
                return None
            # Handle MultiIndex columns (newer yfinance)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            closes = df["Close"]
            if hasattr(closes, "columns") and len(closes.columns) > 0:
                closes = closes.iloc[:, 0]
            closes = closes.dropna()
            if len(closes) < LOOKBACK_TREND + 30:
                return None
            return closes
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"    retry {attempt+1}: {str(e)[:80]}")
                time.sleep(2)
            else:
                print(f"    failed after {max_retries} tries: {str(e)[:100]}")
    return None


def download_all_history():
    print(f"\nDownloading history {START_DATE} to {END_DATE}")
    print(f"Universe: {len(UNIVERSE)} stocks")
    all_data = {}
    for i, ticker in enumerate(UNIVERSE):
        sys.stdout.write(f"  [{i+1:2d}/{len(UNIVERSE)}] {ticker:<15} ")
        sys.stdout.flush()
        closes = download_ticker(f"{ticker}.NS")
        if closes is not None:
            all_data[ticker] = closes
            print(f"OK ({len(closes)} rows, {closes.index[0].strftime('%Y-%m')} → {closes.index[-1].strftime('%Y-%m')})")
        else:
            print("SKIP")
    print(f"\nSuccessfully downloaded {len(all_data)}/{len(UNIVERSE)} stocks")

    # Nifty - skip on failure
    try:
        nifty = download_ticker("^NSEI")
        if nifty is not None and len(nifty) > 0:
            all_data["_NIFTY"] = nifty
            print(f"Nifty: {len(nifty)} rows")
    except Exception as e:
        print(f"Nifty download failed (ok, benchmark skipped): {e}")

    return all_data


def get_month_ends(start, end):
    """Last business day per month. Try new freq name first, fall back to old."""
    try:
        dates = pd.date_range(start=start, end=end, freq="BME")
    except (ValueError, TypeError):
        dates = pd.date_range(start=start, end=end, freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]


def rank_at_date(all_data, date_str):
    ranked = []
    date = pd.Timestamp(date_str)
    for ticker, closes in all_data.items():
        if ticker == "_NIFTY":
            continue
        try:
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
        except Exception as e:
            continue
    ranked.sort(key=lambda x: -x["ret6m"])
    return ranked[:TOP_N]


def run_backtest():
    print("=" * 70)
    print(f"PMS 25-YEAR BACKTEST | {START_DATE} → {END_DATE}")
    print("=" * 70)

    all_data = download_all_history()
    if len(all_data) < 20:
        print(f"\nERROR: Only {len(all_data)} stocks downloaded (need 20+)")
        print("Yahoo may be rate-limiting. Try re-running the workflow in a few minutes.")
        sys.exit(1)

    month_ends = get_month_ends("2000-06-01", END_DATE)
    print(f"\nRunning {len(month_ends)} monthly rebalances...")

    holdings = {}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None
    prev_nav = CORPUS

    for i, date_str in enumerate(month_ends):
        date = pd.Timestamp(date_str)
        cmps = {}
        for t, closes in all_data.items():
            if t == "_NIFTY":
                continue
            try:
                hist = closes[closes.index <= date]
                if len(hist) > 0:
                    cmps[t] = float(hist.iloc[-1])
            except:
                pass

        if starting_nifty is None and "_NIFTY" in all_data:
            try:
                nh = all_data["_NIFTY"]
                nh = nh[nh.index <= date]
                if len(nh) > 0:
                    starting_nifty = float(nh.iloc[-1])
            except:
                pass

        picked = rank_at_date(all_data, date_str)
        picked_tickers = [p["ticker"] for p in picked]

        # SELL
        to_sell = [t for t in list(holdings.keys()) if t not in picked_tickers]
        sold = []
        for t in to_sell:
            pos = holdings[t]
            sp = cmps.get(t, pos["entry_price"])
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

        # BUY
        current_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                         for t, h in holdings.items())
        current_nav = cash + current_mv
        per_stock = current_nav / TOP_N if TOP_N > 0 else 0
        bought = []
        for p in picked:
            if p["ticker"] in holdings:
                continue
            if p["cmp"] <= 0:
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

        final_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                       for t, h in holdings.items())
        final_nav = cash + final_mv
        mom = ((final_nav / prev_nav) - 1) * 100 if prev_nav > 0 else 0
        total = ((final_nav / CORPUS) - 1) * 100

        month_str = date_str[:7]
        held_this = [t for t in holdings if t not in bought]

        wins_m = sum(1 for tr in completed_trades
                     if tr["exitDate"].startswith(month_str) and tr["pnlPct"] > 0)
        loss_m = sum(1 for tr in completed_trades
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
            "winsThisMonth": wins_m,
            "lossesThisMonth": loss_m
        })
        nav_history.append({"date": date_str, "nav": final_nav})
        prev_nav = final_nav

        if (i+1) % 12 == 0:
            year = date_str[:4]
            print(f"  {year} complete: NAV Rs {final_nav/10_000_000:.3f}Cr, Total {total:+.1f}%")

    if not nav_history:
        print("ERROR: No history generated")
        sys.exit(1)

    final_nav = nav_history[-1]["nav"]
    total_return = ((final_nav / CORPUS) - 1) * 100

    start_d = pd.Timestamp(nav_history[0]["date"])
    end_d = pd.Timestamp(nav_history[-1]["date"])
    years = (end_d - start_d).days / 365.25
    cagr = (pow(final_nav / CORPUS, 1/years) - 1) * 100 if years > 0 else 0

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

    nifty_cagr = 0
    nifty_series = all_data.get("_NIFTY")
    if nifty_series is not None and len(nifty_series) > 0 and starting_nifty:
        nifty_end = float(nifty_series.iloc[-1])
        nifty_cagr = (pow(nifty_end / starting_nifty, 1/years) - 1) * 100

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
    print(f"Rs 1 Cr became:    Rs {final_nav/10_000_000:.2f} Cr")
    print("=" * 70)

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
    try:
        run_backtest()
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
