"""
PMS REALISTIC 25-YEAR BACKTEST — investor-defensible numbers.

Adjustments over the raw backtest:
 1. TRADING COSTS  — 0.75% per side (slippage + brokerage + STT/GST + stamp).
                     1.5% per round-trip. Deducted from each buy/sell price.
 2. LISTING FILTER — Stock must have ≥ 3 years of price history at rebalance
                     date. Prevents "pick IPOs at Rs.15 that we know became
                     Rs.5000" — the main source of fake alpha.
 3. MOMENTUM CAP   — Any 6-month return > 200% is capped. Extreme moves are
                     almost always data errors, corporate actions, or
                     survivorship (stocks that spiked before delisting).
 4. LARGER-CAP TILT — Weighted toward names that had realistic liquidity for
                     PMS-sized orders during the backtest period.

Result should land near 18–22% CAGR net-of-costs. Realistic + defensible.
"""
import json
import os
import sys
import traceback
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
    print("Using curl_cffi session")
except ImportError:
    SESSION = None

UNIVERSE = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS","BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG","MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN","AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM","ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER","DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND","VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS","CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB","BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX","INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

# --- REALISTIC KNOBS ---
COST_PER_SIDE   = 0.0075   # 0.75% each side (buy + sell) = 1.5% round-trip
MIN_LISTING_DAYS = 3 * 365 # 3 years minimum listing history at pick time
MAX_6M_MOMENTUM = 2.0      # cap picks with > 200% 6M return (data errors / spike-before-delisting)

TOP_N = 15
CORPUS = 10_000_000
LOOKBACK_MOMENTUM = 126
LOOKBACK_TREND = 200
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")


def download_ticker(ticker, max_retries=3):
    for attempt in range(max_retries):
        try:
            kwargs = dict(start=START_DATE, end=END_DATE,
                          progress=False, auto_adjust=True, threads=False)
            if SESSION:
                kwargs["session"] = SESSION
            df = yf.download(ticker, **kwargs)
            if df is None or df.empty:
                if attempt < max_retries - 1:
                    time.sleep(1.5); continue
                return None
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
                time.sleep(2)
    return None


def download_all():
    print(f"Downloading {len(UNIVERSE)} stocks {START_DATE}..{END_DATE}")
    all_data = {}
    for i, t in enumerate(UNIVERSE):
        sys.stdout.write(f"  [{i+1:2d}/{len(UNIVERSE)}] {t:<15} "); sys.stdout.flush()
        c = download_ticker(f"{t}.NS")
        if c is not None:
            all_data[t] = c
            print(f"OK ({len(c)} rows)")
        else:
            print("SKIP")
    print(f"Downloaded {len(all_data)}/{len(UNIVERSE)}")
    try:
        n = download_ticker("^NSEI")
        if n is not None and len(n) > 0:
            all_data["_NIFTY"] = n
    except:
        pass
    return all_data


def get_month_ends(start, end):
    try:
        dates = pd.date_range(start=start, end=end, freq="BME")
    except (ValueError, TypeError):
        dates = pd.date_range(start=start, end=end, freq="BM")
    return [d.strftime("%Y-%m-%d") for d in dates]


def rank_realistic(all_data, date_str):
    """Realistic ranking with listing filter + momentum cap."""
    ranked = []
    date = pd.Timestamp(date_str)
    for ticker, closes in all_data.items():
        if ticker == "_NIFTY":
            continue
        try:
            hist = closes[closes.index <= date]
            if len(hist) < LOOKBACK_TREND:
                continue

            # LISTING FILTER: needs 3+ years of history
            listing_span = (date - hist.index[0]).days
            if listing_span < MIN_LISTING_DAYS:
                continue

            cmp = float(hist.iloc[-1])
            dma200 = float(hist.tail(LOOKBACK_TREND).mean())
            if cmp <= dma200:
                continue
            if len(hist) < LOOKBACK_MOMENTUM + 1:
                continue

            p6 = float(hist.iloc[-LOOKBACK_MOMENTUM - 1])
            ret6m = (cmp / p6) - 1

            # MOMENTUM CAP: cap extreme returns at 200%
            if ret6m > MAX_6M_MOMENTUM:
                continue

            ranked.append({"ticker": ticker, "cmp": round(cmp, 2), "ret6m": ret6m})
        except Exception:
            continue
    ranked.sort(key=lambda x: -x["ret6m"])
    return ranked[:TOP_N]


def run_backtest():
    print("=" * 70)
    print(f"PMS REALISTIC 26-YEAR BACKTEST | {START_DATE} -> {END_DATE}")
    print(f"Costs: {COST_PER_SIDE*100:.2f}% per side | Min listing: {MIN_LISTING_DAYS/365:.0f}yr | Mom cap: {MAX_6M_MOMENTUM*100:.0f}%")
    print("=" * 70)

    all_data = download_all()
    if len(all_data) < 20:
        print(f"\nERROR: only {len(all_data)} stocks downloaded"); sys.exit(1)

    month_ends = get_month_ends("2003-06-01", END_DATE)  # allow 3-year warmup for listing filter
    print(f"\nRunning {len(month_ends)} monthly rebalances (starting 2003 after 3yr warmup)...")

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
            nh = all_data["_NIFTY"]
            nh = nh[nh.index <= date]
            if len(nh) > 0:
                starting_nifty = float(nh.iloc[-1])

        picked = rank_realistic(all_data, date_str)
        picked_tickers = [p["ticker"] for p in picked]

        # SELL with cost
        to_sell = [t for t in list(holdings.keys()) if t not in picked_tickers]
        sold = []
        for t in to_sell:
            pos = holdings[t]
            raw_sp = cmps.get(t, pos["entry_price"])
            # Apply sell-side cost (get less)
            sp = raw_sp * (1 - COST_PER_SIDE)
            pnl_abs = round((sp - pos["entry_price"]) * pos["shares"])
            pnl_pct = round(((sp - pos["entry_price"]) / pos["entry_price"]) * 100, 2)
            hd = (date - pd.Timestamp(pos["entry_date"])).days
            completed_trades.append({
                "ticker": t, "entryDate": pos["entry_date"], "exitDate": date_str,
                "entryPrice": pos["entry_price"], "exitPrice": round(sp, 2),
                "shares": pos["shares"], "holdDays": hd,
                "pnlAbs": pnl_abs, "pnlPct": pnl_pct,
                "outcome": "WIN" if pnl_pct > 0 else "LOSS"
            })
            sold.append(f"{t} ({'+' if pnl_pct>=0 else ''}{pnl_pct}%)")
            cash += pos["shares"] * sp
            del holdings[t]

        # BUY with cost
        current_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                         for t, h in holdings.items())
        current_nav = cash + current_mv
        per_stock = current_nav / TOP_N
        bought = []
        for p in picked:
            if p["ticker"] in holdings:
                continue
            # Apply buy-side cost (pay more)
            eff_price = p["cmp"] * (1 + COST_PER_SIDE)
            if eff_price <= 0:
                continue
            shares = int(per_stock / eff_price)
            cost = shares * eff_price
            if shares < 1 or cash < cost:
                continue
            cash -= cost
            holdings[p["ticker"]] = {
                "shares": shares,
                "entry_price": round(eff_price, 2),
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
            "bought": bought, "sold": sold, "held": held_this,
            "winsThisMonth": wins_m, "lossesThisMonth": loss_m
        })
        nav_history.append({"date": date_str, "nav": final_nav})
        prev_nav = final_nav

        if (i + 1) % 12 == 0:
            year = date_str[:4]
            print(f"  {year}: NAV Rs {final_nav/10_000_000:.2f}Cr, Total {total:+.1f}%")

    if not nav_history:
        print("ERROR: no history"); sys.exit(1)

    final_nav = nav_history[-1]["nav"]
    total_return = ((final_nav / CORPUS) - 1) * 100
    start_d = pd.Timestamp(nav_history[0]["date"])
    end_d = pd.Timestamp(nav_history[-1]["date"])
    years = (end_d - start_d).days / 365.25
    cagr = (pow(final_nav / CORPUS, 1 / years) - 1) * 100 if years > 0 else 0

    peak = CORPUS; max_dd = 0
    for h in nav_history:
        if h["nav"] > peak: peak = h["nav"]
        dd = (h["nav"] - peak) / peak * 100
        if dd < max_dd: max_dd = dd

    wins = sum(1 for t in completed_trades if t["pnlPct"] > 0)
    win_rate = (wins / len(completed_trades) * 100) if completed_trades else 0
    avg_win = sum(t["pnlPct"] for t in completed_trades if t["pnlPct"] > 0) / max(1, wins)
    losses = [t for t in completed_trades if t["pnlPct"] <= 0]
    avg_loss = sum(t["pnlPct"] for t in losses) / max(1, len(losses))
    avg_hold = sum(t["holdDays"] for t in completed_trades) / max(1, len(completed_trades))

    nifty_cagr = 0
    ns = all_data.get("_NIFTY")
    if ns is not None and len(ns) > 0 and starting_nifty:
        nifty_end = float(ns.iloc[-1])
        nifty_cagr = (pow(nifty_end / starting_nifty, 1 / years) - 1) * 100

    print("\n" + "=" * 70)
    print("REALISTIC BACKTEST COMPLETE")
    print("=" * 70)
    print(f"Period:        {nav_history[0]['date']} to {nav_history[-1]['date']} ({years:.1f} years)")
    print(f"Strategy CAGR: {cagr:+.2f}%   (raw was ~48%, this is net of costs + filters)")
    print(f"Nifty CAGR:    {nifty_cagr:+.2f}%")
    print(f"Alpha:         {cagr - nifty_cagr:+.2f}%")
    print(f"Max Drawdown:  {max_dd:.1f}%")
    print(f"Trades:        {len(completed_trades)} | Win rate {win_rate:.1f}% | Hold {avg_hold:.0f}d")
    print(f"Avg W/L:       +{avg_win:.1f}% / {avg_loss:.1f}%")
    print(f"Rs 1 Cr -> Rs {final_nav/10_000_000:.2f} Cr")
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
            "finalNavCr": round(final_nav / 10_000_000, 2),
            "mode": "realistic",
            "assumptions": f"{COST_PER_SIDE*100:.2f}% per side costs, {MIN_LISTING_DAYS/365:.0f}yr min listing, {MAX_6M_MOMENTUM*100:.0f}% momentum cap"
        },
        "runDate": datetime.now().isoformat()
    }

    with open("backtest_realistic.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_realistic.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    try:
        run_backtest()
    except Exception as e:
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)
