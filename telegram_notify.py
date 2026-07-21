"""
Telegram notifier — sends PMS Algo updates to your Telegram.

Reads data.json (live portfolio) + optionally backtest_honest.json summary,
formats a message with today's BUYs/SELLs + portfolio value + alerts,
sends via Telegram Bot API.

Requires env vars:
  TELEGRAM_BOT_TOKEN  (from @BotFather)
  TELEGRAM_CHAT_ID    (your chat ID)

Optional env vars:
  ALERT_ONLY=1        Only send if there are actionable signals (BUY/SELL/alerts)
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
ALERT_ONLY = os.environ.get("ALERT_ONLY") == "1"

CORPUS = 10_000_000


def fmt_cr(v):
    return f"₹{v/10_000_000:.3f}Cr"


def fmt_pnl(v):
    s = "+" if v >= 0 else "-"
    a = abs(v)
    if a >= 100_000:
        return f"{s}₹{a/100_000:.2f}L"
    return f"{s}₹{int(a):,}"


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"  {path} read failed: {e}")
        return None


def build_message():
    live = load_json("data.json")
    honest = load_json("backtest_honest.json")
    lines = []

    now = datetime.now().strftime("%d %b %Y · %H:%M")
    lines.append(f"🤖 <b>PMS Algo Daily Update</b>")
    lines.append(f"<i>{now}</i>")
    lines.append("")

    if not live:
        lines.append("⚠️ No live data yet. Run daily-algo workflow.")
        return "\n".join(lines)

    # ------- LIVE PORTFOLIO -------
    holdings = live.get("holdings", {})
    completed = live.get("completedTrades", [])
    booked = sum(t.get("pnlAbs", 0) for t in completed)
    prices = live.get("prices", {})

    invested = sum(p["shares"] * p["entryPrice"] for p in holdings.values())
    mv = sum(p["shares"] * (prices.get(t, {}).get("cmp", p["entryPrice"]))
             for t, p in holdings.items())
    unrealized = sum((prices.get(t, {}).get("cmp", p["entryPrice"]) - p["entryPrice"]) * p["shares"]
                    for t, p in holdings.items())
    cash = CORPUS + booked - invested
    nav = cash + mv
    total_ret = (nav / CORPUS - 1) * 100

    buys = live.get("todayExecutedBuys", []) or []
    sells = live.get("todayExecutedSells", []) or []

    # Alert-only mode: skip if nothing new
    if ALERT_ONLY and not buys and not sells:
        print("Alert-only mode: nothing new. Skipping notification.")
        return None

    # Today's signals
    if buys or sells:
        lines.append("🎯 <b>TODAY'S ALGO ACTIONS</b>")
        if buys:
            lines.append(f"🟢 <b>BOUGHT ({len(buys)}):</b>")
            for t in buys[:15]:
                lines.append(f"  · {t}")
            if len(buys) > 15: lines.append(f"  ... +{len(buys)-15} more")
        if sells:
            lines.append(f"🔴 <b>SOLD ({len(sells)}):</b>")
            for t in sells[:15]:
                lines.append(f"  · {t}")
            if len(sells) > 15: lines.append(f"  ... +{len(sells)-15} more")
        lines.append("")
    else:
        lines.append("📋 No new BUY/SELL actions today")
        lines.append("")

    # Portfolio snapshot
    lines.append("📊 <b>PORTFOLIO SNAPSHOT</b>")
    lines.append(f"NAV: <b>{fmt_cr(nav)}</b>")
    lines.append(f"Return: {'+' if total_ret>=0 else ''}{total_ret:.2f}%")
    lines.append(f"Cash: {fmt_cr(cash)} · Invested: {fmt_cr(invested)}")
    lines.append(f"MTM: {fmt_cr(mv)}")
    booked_emoji = "🟢" if booked >= 0 else "🔴"
    unreal_emoji = "🟢" if unrealized >= 0 else "🔴"
    lines.append(f"Booked P&L: {booked_emoji} {fmt_pnl(booked)}")
    lines.append(f"Unrealized: {unreal_emoji} {fmt_pnl(unrealized)}")
    lines.append(f"Open: {len(holdings)} · Closed: {len(completed)}")
    lines.append("")

    # Top winners/losers in portfolio
    if holdings:
        pos_list = []
        for t, p in holdings.items():
            cmp = prices.get(t, {}).get("cmp", p["entryPrice"])
            pnl_pct = ((cmp - p["entryPrice"]) / p["entryPrice"]) * 100
            pos_list.append((t, pnl_pct))
        pos_list.sort(key=lambda x: -x[1])
        top3 = pos_list[:3]
        bot3 = pos_list[-3:]
        if top3:
            lines.append("🏆 <b>Top Winners:</b>")
            for t, p in top3:
                lines.append(f"  {t}: {'+' if p>=0 else ''}{p:.1f}%")
        if bot3 and bot3 != top3:
            lines.append("📉 <b>Top Losers:</b>")
            for t, p in bot3:
                lines.append(f"  {t}: {'+' if p>=0 else ''}{p:.1f}%")
        lines.append("")

    # Alerts
    alerts = []
    for t, p in holdings.items():
        cmp = prices.get(t, {}).get("cmp", p["entryPrice"])
        pnl_pct = ((cmp - p["entryPrice"]) / p["entryPrice"]) * 100
        if pnl_pct <= -15:
            alerts.append(f"⚠️ {t}: {pnl_pct:.1f}% - near trailing stop")
    if alerts:
        lines.append("🚨 <b>ALERTS</b>")
        lines.extend(alerts)
        lines.append("")

    # Benchmark context (from Honest backtest)
    if honest and honest.get("summary"):
        s = honest["summary"]
        lines.append("🏆 <b>Strategy Benchmark (23yr)</b>")
        lines.append(f"Honest CAGR: {s.get('cagr',0):+.2f}%")
        lines.append(f"vs Nifty: {s.get('niftyCagr',0):+.2f}%")
        lines.append(f"Alpha: {s.get('alpha',0):+.2f}%")
        lines.append("")

    lines.append("🔗 <a href='https://sahilaggarwal27.github.io/pms-live/'>Open Dashboard</a>")
    return "\n".join(lines)


def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set as env vars")
        sys.exit(1)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        body = resp.read().decode()
        print(f"Telegram OK: {resp.status}")
        return True
    except Exception as e:
        print(f"Telegram send failed: {e}")
        return False


def main():
    msg = build_message()
    if msg is None:
        print("No message to send (alert-only, no signals)")
        return
    print("=" * 60)
    print(msg)
    print("=" * 60)
    if BOT_TOKEN and CHAT_ID:
        send_telegram(msg)
    else:
        print("(Dry-run: set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to actually send)")


if __name__ == "__main__":
    main()
