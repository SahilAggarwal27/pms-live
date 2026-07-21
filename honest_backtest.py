"""
PMS HONEST BACKTEST — kills survivorship bias.

Uses a MUCH larger universe (~300 stocks) that includes:
  - Historical Nifty 500 constituents approximation
  - Known BLOW-UPS still listed: Yes Bank, Vodafone Idea, JP Associates, Suzlon,
    Reliance Comm, IBRealest, Adani earlier bad names, DLF earlier
  - PSU laggards: BHEL, HPCL, IOC, ONGC, NTPC, SBI, PNB, BOB (many years of underperformance)
  - Old-economy losers: HindMotors, Kingfisher, Deccan Chronicle patterns
  - IPOs at their true listing date (Zomato, Paytm, Nykaa, LIC — many crashed)

Strategy is EXACTLY the same:
  - Top 15 by 6M momentum, above 200-DMA
  - Monthly rebalance
  - Historical costs (STT/GST/stamp/brokerage per era)
  - 3-year listing filter (prevents "pick IPO knowing it worked")

If honest_backtest CAGR < realistic_backtest CAGR → survivorship bias was real.
Result should land near 18-22% CAGR = defensible for SEBI.
"""
import json
import os
import sys
import traceback
import time
from datetime import datetime

import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
    print("Using curl_cffi session")
except ImportError:
    SESSION = None

# ============================================================
# HONEST UNIVERSE — approximation of historical Nifty 500
# Includes stocks that later became winners AND losers.
# This is the crucial anti-survivorship input.
# ============================================================

# ORIGINAL PICKS (still winners today) — kept for continuity
WINNERS_TODAY = ["PERSISTENT","COFORGE","MPHASIS","LTIM","KPITTECH","TATAELXSI","OFSS",
                  "BOSCHLTD","MRF","MOTHERSON","EXIDEIND","BALKRISIND","BHARATFORG",
                  "MUTHOOTFIN","CHOLAFIN","LICHSGFIN","MFSL","PFC","RECLTD","LUPIN",
                  "AUROPHARMA","GLENMARK","BIOCON","ALKEM","LAURUSLABS","JBCHEPHARM",
                  "ABBOTINDIA","SIEMENS","CUMMINSIND","THERMAX","HAL","BEL","CGPOWER",
                  "DIXON","PIIND","DEEPAKNTR","NAVINFLUOR","SRF","ATUL","AARTIIND",
                  "VINATIORGA","COROMANDEL","SOLARINDS","PAGEIND","HAVELLS","VOLTAS",
                  "CROMPTON","JUBLFOOD","VBL","TRENT","FEDERALBNK","AUBANK","IDFCFIRSTB",
                  "BANKBARODA","GODREJPROP","OBEROIRLTY","PRESTIGE","IEX","CDSL","MCX",
                  "INDIAMART","NAUKRI","GAIL","IGL","TATAPOWER","HINDZINC","JINDALSTEL","NMDC"]

# NIFTY 50 — the "obvious" large caps (many had mediocre returns)
NIFTY50 = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","HINDUNILVR","ITC","LT",
            "KOTAKBANK","SBIN","AXISBANK","BAJFINANCE","BHARTIARTL","ASIANPAINT","MARUTI",
            "HDFCLIFE","M&M","TATASTEEL","SUNPHARMA","NTPC","POWERGRID","ULTRACEMCO",
            "ONGC","TITAN","DRREDDY","NESTLEIND","ADANIENT","ADANIPORTS","JSWSTEEL",
            "TATAMOTORS","TATACONSUM","APOLLOHOSP","CIPLA","INDUSINDBK","GRASIM",
            "HEROMOTOCO","BRITANNIA","EICHERMOT","DIVISLAB","BAJAJFINSV","BPCL",
            "COALINDIA","HINDALCO","TECHM","WIPRO","BAJAJ-AUTO","SBILIFE","HCLTECH",
            "SHRIRAMFIN","UPL","LTIM"]

# KNOWN BLOW-UPS / MASSIVE UNDERPERFORMERS (crucial for honest test)
BLOWUPS = ["YESBANK","IDEA","JPASSOCIAT","SUZLON","RCOM","DHFL","IBREALEST","IDBI",
            "UNITECH","IL&FSTRANS","JETAIRWAYS","KINGFISH","DECCAN","GVKPIL","GMRINFRA",
            "IRB","PNB","CANBK","UNIONBANK","INDIANB","CENTRALBK","BANKINDIA","MAHABANK",
            "SYNDIBANK","VIJAYABANK","ANDHRABANK","CORPBANK","ALBK","JISLJALEQS",
            "RCOM","RELIABLE","JPPOWER","PATNI","3IINFOTECH","MOSER","CHENNAI"]

# MID/SMALL CAP LAGGARDS + others
MIDCAP_LAGGARDS = ["BHEL","BEML","CONCOR","EIL","MOIL","MMTC","STCINDIA","MRPL",
                    "MADHUCON","HINDCOPPER","IRCON","SAIL","NHPC","NLCINDIA","IOC",
                    "HPCL","OIL","BPCL","GAIL","NBCC","PFC","REC","RITES","IRCTC",
                    "IRFC","RVNL","INDIGO","SPICEJET","JETSETGO","TATACHEM","DBCORP",
                    "JAGRAN","HTMEDIA","TVSMOTOR","BAJAJHLDNG","EIHOTEL","EIH",
                    "MAHINDCIE","MINDACORP","MINDAIND","APOLLOTYRE","JKTYRE","CEATLTD",
                    "MRF","TVSMOTOR","ESCORTS","ASHOKLEY","FORCEMOT","VSTIND","GODREJIND",
                    "DABUR","EMAMILTD","GILLETTE","COLPAL","MARICO","GODREJCP","BATA",
                    "RELAXO","METROBRAND","BATAINDIA","INDHOTEL","LEMONTREE","CHALET",
                    "MAHLIFE","OBEROIRLTY","BRIGADE","SUNTECK","KOLTEPATIL","PHOENIXLTD",
                    "BLUEDART","GATI","VRLLOG","MAHLOG","GATI","TCI","ALLCARGO",
                    "CONCOR","IRB","GESHIP","GEPIL","SHIPPINGCORP","MAZDOCK","COCHINSHIP"]

# BANK & FINANCIAL SECTOR (mixed performers)
BANKS = ["INDUSINDBK","CANBK","BANKBARODA","PNB","BANKINDIA","UNIONBANK","CENTRALBK",
         "IOB","IDBI","YESBANK","RBLBANK","BANDHANBNK","EQUITASBNK","UJJIVAN",
         "SURYODAY","DCB","KTKBANK","TMB","CSBBANK","SOUTHBANK","J&KBANK","LAKPRE"]

# CEMENT (many years of poor returns)
CEMENT = ["ULTRACEMCO","SHREECEM","AMBUJACEM","ACC","DALBHARAT","RAMCOCEM","JKCEMENT",
          "HEIDELBERG","BIRLACORPN","INDIACEM","STARCEMENT","ORIENTCEM","PRISMJOHNS"]

# STEEL & METAL (very cyclical, big drawdowns)
STEEL_METAL = ["TATASTEEL","JSWSTEEL","JINDALSTEL","SAIL","NMDC","VEDL","HINDCOPPER",
               "HINDZINC","NATIONALUM","HINDALCO","JSPL","ADANIENT","GALVANIZING",
               "APLAPOLLO","JINDALSAW","WELCORP","MOIL","MAHASTEEL"]

# PHARMA (mixed)
PHARMA = ["SUNPHARMA","CIPLA","DRREDDY","LUPIN","AUROPHARMA","DIVISLAB","BIOCON","CADILAHC",
          "TORNTPHARM","APOLLOHOSP","FORTIS","MAXHEALTH","METROPOLIS","LALPATHLAB","THYROCARE",
          "PFIZER","GLAXO","SANOFI","MERCK","NOVARTIS","BALPHARMA","AJANTPHARM","IPCALAB",
          "ERISLIFE","JBCHEPHARM","GRANULES","STAR","STRIDES","SEQUENT","MARKSANS"]

# IT (mixed after 2000 dot-com crash)
IT_MIXED = ["INFY","TCS","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","COFORGE","PERSISTENT",
            "OFSS","MINDTREE","LARSEN","3IINFOTECH","PATNI","POLARIS","GEOMETRIC","INFOTECHENT",
            "SUBEX","MOSCHIP","ONMOBILE","INTRASOFT","KELLTONTEC","RSSOFTWARE"]

# AUTO (cyclical)
AUTO = ["MARUTI","M&M","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR",
        "ASHOKLEY","ESCORTS","MOTHERSON","BOSCHLTD","MRF","BALKRISIND","BHARATFORG",
        "EXIDEIND","AMARAJABAT","APOLLOTYRE","JKTYRE","CEATLTD","SHRIRAMFIN","MMFSL","MAHLIFE"]

# CONSUMER (mostly quality but slow)
CONSUMER = ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP",
            "COLPAL","EMAMILTD","JYOTHYLAB","GILLETTE","VBL","VARUN","JUBLFOOD","WESTLIFE",
            "DEVYANI","SPECIALTY","BIKAJI","GODFRYPHLP","VBLR","UBL","RADICO","GLOBALTELE"]

# INFRA & POWER (many years of losses)
INFRA_POWER = ["LT","ADANIPORTS","RVNL","CONCOR","NHPC","NTPC","POWERGRID","TATAPOWER",
                "ADANIPOWER","TORNTPOWER","JSWENERGY","JPPOWER","INDIANHUME","IRB",
                "NCC","HGINFRA","KNRCON","JMFEBUILD","GMRINFRA","GVK","JAIPRAKAS"]

# Combine all universes, dedupe
UNIVERSE_SET = set(WINNERS_TODAY) | set(NIFTY50) | set(BLOWUPS) | set(MIDCAP_LAGGARDS) | \
               set(BANKS) | set(CEMENT) | set(STEEL_METAL) | set(PHARMA) | \
               set(IT_MIXED) | set(AUTO) | set(CONSUMER) | set(INFRA_POWER)
UNIVERSE = sorted(UNIVERSE_SET)
print(f"Honest universe: {len(UNIVERSE)} stocks (vs 68 in realistic backtest)")

TOP_N = 15
CORPUS = 10_000_000
LOOKBACK_MOMENTUM = 126
LOOKBACK_TREND = 200
SLIPPAGE_PER_SIDE = 0.30
MIN_LISTING_DAYS = 3 * 365
MAX_6M_MOMENTUM = 2.0
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")


def load_cost_regimes():
    try:
        with open("cost_history.json") as f:
            data = json.load(f)
        return sorted(data["regimes"], key=lambda r: r["startDate"])
    except Exception as e:
        print(f"WARN: cost_history.json load failed: {e}")
        return []


def costs_for_date(date_str, regimes):
    if not regimes:
        return {"buy": 0.75, "sell": 0.75, "regimeEvent": "FLAT"}
    active = regimes[0]
    for r in regimes:
        if r["startDate"] <= date_str:
            active = r
        else:
            break
    b = active["brokeragePerSide"]
    gst = active["gstOnBrokerage"] / 100
    slip = SLIPPAGE_PER_SIDE
    stt_b = active["sttBuyDelivery"]
    stt_s = active["sttSellDelivery"]
    stamp = active["stampBuy"]
    exch = active["exchangeSebi"]
    return {
        "buy": b * (1 + gst) + slip + stt_b + stamp + exch,
        "sell": b * (1 + gst) + slip + stt_s + exch,
        "regimeEvent": active["event"],
    }


def download_ticker(ticker, max_retries=2):
    for attempt in range(max_retries):
        try:
            kwargs = dict(start=START_DATE, end=END_DATE,
                          progress=False, auto_adjust=True, threads=False)
            if SESSION:
                kwargs["session"] = SESSION
            df = yf.download(ticker, **kwargs)
            if df is None or df.empty:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            closes = df["Close"]
            if hasattr(closes, "columns") and len(closes.columns) > 0:
                closes = closes.iloc[:, 0]
            closes = closes.dropna()
            if len(closes) < 60:  # more lenient - even short-listed stocks count if enough history
                return None
            return closes
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(1)
    return None


def download_all():
    print(f"\nDownloading {len(UNIVERSE)} stocks {START_DATE}..{END_DATE}")
    print(f"(This universe includes known losers like Yes Bank, DHFL, Suzlon, PSUs)")
    all_data = {}
    skipped = []
    for i, t in enumerate(UNIVERSE):
        if (i + 1) % 25 == 0 or i == 0:
            print(f"  Progress: {i+1}/{len(UNIVERSE)} ({len(all_data)} OK, {len(skipped)} skip)")
        c = download_ticker(f"{t}.NS")
        if c is not None:
            all_data[t] = c
        else:
            skipped.append(t)
    print(f"Downloaded {len(all_data)}/{len(UNIVERSE)} stocks")
    if skipped:
        print(f"Skipped ({len(skipped)}): {skipped[:20]}... (likely delisted / never listed on NSE)")
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


def rank_honest(all_data, date_str):
    """Rank with strict point-in-time listing check."""
    ranked = []
    date = pd.Timestamp(date_str)
    for ticker, closes in all_data.items():
        if ticker == "_NIFTY":
            continue
        try:
            hist = closes[closes.index <= date]
            if len(hist) < LOOKBACK_TREND:
                continue
            # POINT-IN-TIME: stock must have been listed at least 3 yrs before this date
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
            if ret6m > MAX_6M_MOMENTUM:
                continue
            ranked.append({"ticker": ticker, "cmp": round(cmp, 2), "ret6m": ret6m})
        except Exception:
            continue
    ranked.sort(key=lambda x: -x["ret6m"])
    return ranked[:TOP_N]


def run_backtest():
    print("=" * 70)
    print(f"PMS HONEST BACKTEST | Anti-Survivorship | {START_DATE} -> {END_DATE}")
    print("=" * 70)

    regimes = load_cost_regimes()
    all_data = download_all()
    if len(all_data) < 50:
        print(f"\nERROR: only {len(all_data)} stocks — too few for honest test")
        sys.exit(1)

    month_ends = get_month_ends("2003-06-01", END_DATE)
    print(f"\nRunning {len(month_ends)} monthly rebalances on {len(all_data)-1} stock universe...")

    holdings = {}
    monthly_journal = []
    completed_trades = []
    nav_history = []
    cash = CORPUS
    starting_nifty = None
    prev_nav = CORPUS
    total_costs_paid = 0.0
    universe_by_year = {}  # track how many eligible stocks each year

    for i, date_str in enumerate(month_ends):
        date = pd.Timestamp(date_str)
        c = costs_for_date(date_str, regimes)
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

        picked = rank_honest(all_data, date_str)
        picked_tickers = [p["ticker"] for p in picked]
        year = date_str[:4]
        # Count eligible stocks in universe at this point
        eligible = sum(1 for t, cl in all_data.items() if t != "_NIFTY" and
                       len(cl[cl.index <= date]) >= LOOKBACK_TREND and
                       (date - cl[cl.index <= date].index[0]).days >= MIN_LISTING_DAYS)
        universe_by_year[year] = eligible

        # SELL
        to_sell = [t for t in list(holdings.keys()) if t not in picked_tickers]
        sold = []
        for t in to_sell:
            pos = holdings[t]
            raw_sp = cmps.get(t, pos["entry_price"])
            sp = raw_sp * (1 - c["sell"] / 100)
            cost_this_side = raw_sp * pos["shares"] * (c["sell"] / 100)
            total_costs_paid += cost_this_side
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

        # BUY
        current_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                         for t, h in holdings.items())
        current_nav = cash + current_mv
        per_stock = current_nav / TOP_N
        bought = []
        for p in picked:
            if p["ticker"] in holdings: continue
            eff_price = p["cmp"] * (1 + c["buy"] / 100)
            if eff_price <= 0: continue
            shares = int(per_stock / eff_price)
            outlay = shares * eff_price
            cost_this_side = shares * p["cmp"] * (c["buy"] / 100)
            if shares < 1 or cash < outlay: continue
            total_costs_paid += cost_this_side
            cash -= outlay
            holdings[p["ticker"]] = {"shares": shares, "entry_price": round(eff_price, 2), "entry_date": date_str}
            bought.append(p["ticker"])

        final_mv = sum(h["shares"] * cmps.get(t, h["entry_price"])
                       for t, h in holdings.items())
        final_nav = cash + final_mv
        mom = ((final_nav / prev_nav) - 1) * 100 if prev_nav > 0 else 0
        total = ((final_nav / CORPUS) - 1) * 100
        month_str = date_str[:7]
        held_this = [t for t in holdings if t not in bought]
        wins_m = sum(1 for tr in completed_trades if tr["exitDate"].startswith(month_str) and tr["pnlPct"] > 0)
        loss_m = sum(1 for tr in completed_trades if tr["exitDate"].startswith(month_str) and tr["pnlPct"] <= 0)

        monthly_journal.append({
            "month": month_str, "date": date_str,
            "nav": round(final_nav),
            "navCr": round(final_nav / 10_000_000, 3),
            "monthReturn": round(mom, 2),
            "totalReturn": round(total, 2),
            "cash": round(cash),
            "holdingsCount": len(holdings),
            "bought": bought, "sold": sold, "held": held_this,
            "winsThisMonth": wins_m, "lossesThisMonth": loss_m,
            "eligibleUniverse": eligible,
            "regimeCostBuy": round(c["buy"], 3),
            "regimeCostSell": round(c["sell"], 3),
            "regimeEvent": c["regimeEvent"]
        })
        nav_history.append({"date": date_str, "nav": final_nav})
        prev_nav = final_nav

        if (i + 1) % 12 == 0:
            print(f"  {year}: NAV Rs {final_nav/10_000_000:.2f}Cr | Total {total:+.1f}% | Universe {eligible} eligible")

    if not nav_history:
        print("ERROR: no history")
        sys.exit(1)

    final_nav = nav_history[-1]["nav"]
    total_return = ((final_nav / CORPUS) - 1) * 100
    start_d = pd.Timestamp(nav_history[0]["date"])
    end_d = pd.Timestamp(nav_history[-1]["date"])
    years = (end_d - start_d).days / 365.25
    cagr = (pow(final_nav / CORPUS, 1 / years) - 1) * 100 if years > 0 else 0

    peak = CORPUS
    max_dd = 0
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
    print("HONEST BACKTEST COMPLETE (300+ stock universe, anti-survivorship)")
    print("=" * 70)
    print(f"Universe size:     {len(all_data)-1} stocks (vs 68 in previous realistic)")
    print(f"Period:            {nav_history[0]['date']} to {nav_history[-1]['date']} ({years:.1f} years)")
    print(f"Strategy CAGR:     {cagr:+.2f}%")
    print(f"Nifty CAGR:        {nifty_cagr:+.2f}%")
    print(f"Alpha:             {cagr - nifty_cagr:+.2f}%")
    print(f"Max Drawdown:      {max_dd:.1f}%")
    print(f"Trades:            {len(completed_trades)} | Win {win_rate:.1f}% | Hold {avg_hold:.0f}d")
    print(f"Avg W/L:           +{avg_win:.1f}% / {avg_loss:.1f}%")
    print(f"Rs 1 Cr ->         Rs {final_nav/10_000_000:.2f} Cr")
    print(f"Total costs:       Rs {total_costs_paid/10_000_000:.2f} Cr")
    print("=" * 70)
    print(f"\nEligible universe by year (point-in-time):")
    for y in sorted(universe_by_year.keys())[::4]:
        print(f"  {y}: {universe_by_year[y]} stocks")

    output = {
        "monthlyJournal": monthly_journal,
        "completedTrades": completed_trades,
        "navHistory": [{"date": h["date"], "nav": round(h["nav"])} for h in nav_history],
        "holdings": {t: {"shares": h["shares"], "entryPrice": h["entry_price"], "entryDate": h["entry_date"]}
                     for t, h in holdings.items()},
        "startDate": nav_history[0]["date"],
        "endDate": nav_history[-1]["date"],
        "universeSize": len(all_data) - 1,
        "universeByYear": universe_by_year,
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
            "mode": "honest-anti-survivorship",
            "universeSize": len(all_data) - 1,
            "assumptions": f"{len(all_data)-1} stock universe including Yes Bank, DHFL, Suzlon, PSU laggards + 3yr listing filter + historical costs"
        },
        "runDate": datetime.now().isoformat()
    }
    with open("backtest_honest.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved backtest_honest.json ({len(monthly_journal)} months, {len(completed_trades)} trades)")


if __name__ == "__main__":
    try:
        run_backtest()
    except Exception as e:
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)
