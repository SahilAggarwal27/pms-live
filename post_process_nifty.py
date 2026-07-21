"""
Add Nifty 50 comparison to existing backtest JSONs.
Downloads Nifty history once, then augments each *.json with:
  - niftyValue per month
  - niftyMonthReturn per month
"""
import json, os, sys, time
from datetime import datetime
import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSION = cffi_requests.Session(impersonate="chrome")
except ImportError:
    SESSION = None


def fetch_nifty():
    print("Downloading Nifty 50 history...")
    for a in range(3):
        try:
            kw = dict(start="2000-01-01", end=datetime.now().strftime("%Y-%m-%d"),
                      progress=False, auto_adjust=True, threads=False)
            if SESSION: kw["session"] = SESSION
            df = yf.download("^NSEI", **kw)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                c = df["Close"]
                if hasattr(c,"columns") and len(c.columns)>0: c = c.iloc[:,0]
                c = c.dropna()
                print(f"Nifty: {len(c)} rows {c.index[0].date()} to {c.index[-1].date()}")
                return c
        except Exception as e:
            print(f"  retry {a+1}: {e}")
            time.sleep(2)
    return None


def enrich(path, nifty):
    if not os.path.exists(path):
        print(f"SKIP: {path} not found")
        return
    with open(path) as f: data = json.load(f)
    mj = data.get("monthlyJournal", [])
    if not mj:
        print(f"SKIP: {path} no monthlyJournal")
        return
    prev = None
    for entry in mj:
        date = pd.Timestamp(entry["date"])
        nh = nifty[nifty.index <= date]
        if len(nh) == 0:
            entry["niftyValue"] = None
            entry["niftyMonthReturn"] = None
            continue
        cur = float(nh.iloc[-1])
        entry["niftyValue"] = round(cur, 2)
        if prev is not None and prev > 0:
            entry["niftyMonthReturn"] = round((cur/prev - 1)*100, 2)
        else:
            entry["niftyMonthReturn"] = 0.0
        prev = cur
    with open(path, "w") as f: json.dump(data, f, indent=2, default=str)
    print(f"OK: {path} enriched ({len(mj)} months)")


def main():
    nifty = fetch_nifty()
    if nifty is None:
        print("FATAL: Nifty download failed"); sys.exit(1)
    for p in ["backtest_data.json","backtest_realistic.json","backtest_honest.json",
              "backtest_enhanced.json","backtest_super_enhanced.json"]:
        enrich(p, nifty)
    print("\nDone.")


if __name__ == "__main__":
    main()
