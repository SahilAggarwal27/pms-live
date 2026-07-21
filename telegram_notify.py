"""
Telegram notifier v3 — with EOD_MODE for clean 3:30 PM summary.

Env vars:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required)
  ALERT_ONLY=1  → skip if no signals (morning use)
  EOD_MODE=1    → clean end-of-day format (3:30 PM use)
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
ALERT_ONLY = os.environ.get("ALERT_ONLY") == "1"
EOD_MODE = os.environ.get("EOD_MODE") == "1"
CORPUS = 10_000_000


def fmt_cr(v):    return f"₹{v/10_000_000:.3f}Cr"
def fmt_l(v):     return f"₹{v/100_000:.1f}L"
def fmt_pnl(v):
    s = "+" if v >= 0 else "-"; a = abs(v)
    if a >= 100_000: return f"{s}₹{a/100_000:.2f}L"
    if a >= 1_000:   return f"{s}₹{a/1000:.1f}K"
    return f"{s}₹{int(a):,}"


def load_json(path):
    if not os.path.exists(path): return None
    try:
        with open(path) as f: return json.load(f)
    except Exception as e:
        print(f"  {path} read failed: {e}")
        return None


def build_eod_message():
    """CLEAN 3:30 PM summary — just booked profit/loss + open positions."""
    live = load_json("data.json")
    if not live:
        return "⚠️ No live data yet."

    holdings = live.get("holdings", {})
    completed = live.get("completedTrades", [])
    prices = live.get("prices", {})
    now = datetime.now().strftime("%d %b %Y")
    lines = []
    lines.append(f"📊 <b>EOD SUMMARY · 3:30 PM</b>")
    lines.append(f"<i>{now} · Market Close</i>")
    lines.append("")

    # ------ BOOKED (realized) ------
    winners = [t for t in completed if t.get("pnlPct", 0) > 0]
    losers  = [t for t in completed if t.get("pnlPct", 0) <= 0]
    total_win_pnl = sum(t.get("pnlAbs", 0) for t in winners)
    total_loss_pnl = sum(t.get("pnlAbs", 0) for t in losers)
    net_booked = total_win_pnl + total_loss_pnl

    avg_win_pct = sum(t.get("pnlPct", 0) for t in winners) / max(1, len(winners))
    avg_loss_pct = sum(t.get("pnlPct", 0) for t in losers) / max(1, len(losers))

    lines.append(f"💰 <b>BOOKED P&L (Realized)</b>")
    if winners:
        lines.append(f"🟢 Profit Booked: <b>{fmt_pnl(total_win_pnl)}</b> · avg <b>+{avg_win_pct:.2f}%</b> ({len(winners)} trades)")
    else:
        lines.append(f"🟢 Profit Booked: ₹0 (no wins yet)")
    if losers:
        lines.append(f"🔴 Loss Booked: <b>{fmt_pnl(total_loss_pnl)}</b> · avg <b>{avg_loss_pct:.2f}%</b> ({len(losers)} trades)")
    else:
        lines.append(f"🔴 Loss Booked: ₹0 (no losses yet)")
    net_emoji = "🟢" if net_booked >= 0 else "🔴"
    lines.append(f"📗 <b>Net Booked: {net_emoji} {fmt_pnl(net_booked)}</b>")
    lines.append("")

    # ------ OPEN POSITIONS ------
    if not holdings:
        lines.append("📭 No open positions")
    else:
        pos_list = []
        for t, p in holdings.items():
            cmp = prices.get(t, {}).get("cmp", p["entryPrice"])
            pnl_pct = ((cmp - p["entryPrice"]) / p["entryPrice"]) * 100
            pnl_abs = (cmp - p["entryPrice"]) * p["shares"]
            pos_list.append({"t": t, "entry": p["entryPrice"], "cmp": cmp,
                            "pct": pnl_pct, "abs": pnl_abs})
        pos_list.sort(key=lambda x: -x["pct"])

        total_unrealized = sum(p["abs"] for p in pos_list)
        pos_gainers = [p for p in pos_list if p["pct"] > 0]
        pos_losers  = [p for p in pos_list if p["pct"] <= 0]

        unreal_emoji = "🟢" if total_unrealized >= 0 else "🔴"
        lines.append(f"📈 <b>OPEN POSITIONS ({len(pos_list)})</b>")
        lines.append(f"📘 <b>Unrealized: {unreal_emoji} {fmt_pnl(total_unrealized)}</b>")
        lines.append(f"🟢 In Profit: {len(pos_gainers)} · 🔴 In Loss: {len(pos_losers)}")
        lines.append("")

        # List each position with +/- %
        for p in pos_list:
            emoji = "🟢" if p["pct"] >= 0 else "🔴"
            lines.append(f"  {emoji} <b>{p['t']}</b> · {p['pct']:+.2f}% ({fmt_pnl(p['abs'])})")
        lines.append("")

    # ------ TOTAL RETURN ------
    invested = sum(p["shares"] * p["entryPrice"] for p in holdings.values())
    mv = sum(p["shares"] * prices.get(t, {}).get("cmp", p["entryPrice"])
             for t, p in holdings.items())
    cash = CORPUS + net_booked - invested
    nav = cash + mv
    total_ret = (nav / CORPUS - 1) * 100
    ret_emoji = "🟢" if total_ret >= 0 else "🔴"
    lines.append(f"💼 <b>Portfolio NAV: {fmt_cr(nav)} · {ret_emoji} {total_ret:+.2f}%</b>")
    lines.append("")
    lines.append("🔗 <a href='https://sahilaggarwal27.github.io/pms-live/'>Dashboard</a>")
    return "\n".join(lines)


def build_full_message():
    """FULL morning message with signals + all details."""
    live = load_json("data.json")
    honest = load_json("backtest_honest.json")
    lines = []
    now = datetime.now().strftime("%d %b %Y · %H:%M IST")
    lines.append(f"🤖 <b>PMS Algo — Live Update</b>")
    lines.append(f"<i>{now}</i>")
    lines.append("")

    if not live:
        lines.append("⚠️ No live data yet. Trigger daily-algo workflow.")
        return "\n".join(lines)

    holdings = live.get("holdings", {})
    completed = live.get("completedTrades", [])
    prices = live.get("prices", {})
    booked = sum(t.get("pnlAbs", 0) for t in completed)
    invested = sum(p["shares"] * p["entryPrice"] for p in holdings.values())
    mv = sum(p["shares"] * prices.get(t, {}).get("cmp", p["entryPrice"])
             for t, p in holdings.items())
    unrealized = sum((prices.get(t, {}).get("cmp", p["entryPrice"]) - p["entryPrice"]) * p["shares"]
                    for t, p in holdings.items())
    cash = CORPUS + booked - invested
    nav = cash + mv
    total_ret = (nav / CORPUS - 1) * 100

    last_run = live.get("lastExecuteDate")
    today_iso = datetime.now().strftime("%Y-%m-%d")
    ran_today = last_run == today_iso
    buys_today = live.get("todayExecutedBuys", []) or []
    sells_today_str = live.get("todayExecutedSells", []) or []
    sells_today_detail = [t for t in completed if t.get("exitDate") == last_run]

    has_action = bool(buys_today or sells_today_str)
    if ALERT_ONLY and not has_action:
        print("Alert-only mode: no actions today. Skipping.")
        return None

    if buys_today:
        lines.append(f"🟢 <b>BOUGHT TODAY ({len(buys_today)})</b>")
        for t in buys_today:
            pos = holdings.get(t)
            if pos:
                entry = pos["entryPrice"]; sh = pos["shares"]
                invested_amt = entry * sh
                cmp = prices.get(t, {}).get("cmp", entry)
                pct = ((cmp - entry) / entry) * 100 if entry else 0
                emoji = "🟢" if pct >= 0 else "🔴"
                lines.append(f"  • <b>{t}</b> · {sh} sh @ ₹{entry:.2f}")
                lines.append(f"    Invested: {fmt_l(invested_amt)} · CMP ₹{cmp:.2f} {emoji} {pct:+.2f}%")
            else:
                lines.append(f"  • <b>{t}</b>")
        lines.append("")

    if sells_today_detail:
        wins = sum(1 for t in sells_today_detail if t["pnlPct"] > 0)
        losses = len(sells_today_detail) - wins
        total_booked_today = sum(t.get("pnlAbs", 0) for t in sells_today_detail)
        lines.append(f"🔴 <b>SOLD TODAY ({len(sells_today_detail)}) · W {wins} / L {losses} · Booked {fmt_pnl(total_booked_today)}</b>")
        for t in sells_today_detail:
            emoji = "🟢" if t["pnlPct"] > 0 else "🔴"
            reason = t.get("exitReason", "")
            reason_txt = f" · <i>{reason}</i>" if reason else ""
            lines.append(f"  {emoji} <b>{t['ticker']}</b> · Entry ₹{t['entryPrice']:.2f} → Exit ₹{t['exitPrice']:.2f}")
            lines.append(f"    <b>{t['pnlPct']:+.2f}%</b> · {fmt_pnl(t['pnlAbs'])} · Held {t['holdDays']}d{reason_txt}")
        lines.append("")
    elif sells_today_str:
        lines.append(f"🔴 <b>SOLD TODAY ({len(sells_today_str)})</b>")
        for s in sells_today_str:
            lines.append(f"  • {s}")
        lines.append("")

    if not has_action and ran_today:
        lines.append("📋 <b>Algo ran today · No new BUY/SELL signals</b>")
        lines.append("")
    elif not ran_today:
        lines.append(f"⚠️ Algo hasn't run today · Last run: {last_run or 'never'}")
        lines.append("")

    lines.append("📊 <b>PORTFOLIO SNAPSHOT</b>")
    lines.append(f"NAV: <b>{fmt_cr(nav)}</b> · Return: <b>{total_ret:+.2f}%</b>")
    lines.append(f"💰 Cash: {fmt_l(cash)} · Invested: {fmt_l(invested)} · MV: {fmt_l(mv)}")
    booked_emoji = "🟢" if booked >= 0 else "🔴"
    unreal_emoji = "🟢" if unrealized >= 0 else "🔴"
    lines.append(f"📗 Booked P&L: {booked_emoji} <b>{fmt_pnl(booked)}</b>")
    lines.append(f"📘 Unrealized: {unreal_emoji} <b>{fmt_pnl(unrealized)}</b>")
    if completed:
        wins = sum(1 for t in completed if t.get("pnlPct", 0) > 0)
        wr = wins / len(completed) * 100
        lines.append(f"Win Rate: {wr:.1f}% ({wins}/{len(completed)})")
    lines.append("")

    if holdings:
        pos_list = []
        for t, p in holdings.items():
            cmp = prices.get(t, {}).get("cmp", p["entryPrice"])
            pnl_pct = ((cmp - p["entryPrice"]) / p["entryPrice"]) * 100
            pnl_abs = (cmp - p["entryPrice"]) * p["shares"]
            days = (datetime.now() - datetime.fromisoformat(p["entryDate"])).days if isinstance(p.get("entryDate"), str) else 0
            pos_list.append({"t": t, "entry": p["entryPrice"], "cmp": cmp,
                             "pct": pnl_pct, "abs": pnl_abs, "days": days})
        pos_list.sort(key=lambda x: -x["pct"])
        winners = [p for p in pos_list if p["pct"] > 0]
        losers = [p for p in pos_list if p["pct"] <= 0]
        if winners:
            lines.append(f"🏆 <b>WINNERS ({len(winners)})</b>")
            for p in winners[:8]:
                lines.append(f"  🟢 <b>{p['t']}</b> · ₹{p['entry']:.2f}→₹{p['cmp']:.2f} · <b>{p['pct']:+.1f}%</b> ({fmt_pnl(p['abs'])}) · {p['days']}d")
            if len(winners) > 8: lines.append(f"  ... +{len(winners)-8} more")
            lines.append("")
        if losers:
            lines.append(f"📉 <b>LOSERS ({len(losers)})</b>")
            for p in losers[:8]:
                near_stop = " ⚠️" if p["pct"] <= -12 else ""
                lines.append(f"  🔴 <b>{p['t']}</b> · ₹{p['entry']:.2f}→₹{p['cmp']:.2f} · <b>{p['pct']:+.1f}%</b> ({fmt_pnl(p['abs'])}) · {p['days']}d{near_stop}")
            if len(losers) > 8: lines.append(f"  ... +{len(losers)-8} more")
            lines.append("")

    alerts = []
    for t, p in holdings.items():
        cmp = prices.get(t, {}).get("cmp", p["entryPrice"])
        pnl_pct = ((cmp - p["entryPrice"]) / p["entryPrice"]) * 100
        if pnl_pct <= -13:
            alerts.append(f"⚠️ <b>{t}</b>: {pnl_pct:+.1f}% — near trailing stop")
        elif pnl_pct >= 40:
            alerts.append(f"🚀 <b>{t}</b>: {pnl_pct:+.1f}% — big winner, consider trim")
    if alerts:
        lines.append("🚨 <b>ALERTS</b>")
        lines.extend(alerts)
        lines.append("")

    if honest and honest.get("summary"):
        s = honest["summary"]
        lines.append("🎯 <b>Strategy Benchmark (23yr Honest)</b>")
        lines.append(f"Gross CAGR: <b>{s.get('cagr',0):+.2f}%</b> · Alpha: <b>{s.get('alpha',0):+.2f}%</b>")
        lines.append("")

    lines.append("🔗 <a href='https://sahilaggarwal27.github.io/pms-live/'>Open Full Dashboard</a>")
    return "\n".join(lines)


def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)
    max_len = 4000
    chunks = [msg]
    if len(msg) > max_len:
        chunks = []; buf = ""
        for line in msg.split("\n"):
            if len(buf) + len(line) + 1 > max_len:
                chunks.append(buf); buf = line
            else:
                buf = buf + "\n" + line if buf else line
        if buf: chunks.append(buf)
    for i, chunk in enumerate(chunks):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": CHAT_ID, "text": chunk,
            "parse_mode": "HTML", "disable_web_page_preview": "true"
        }).encode()
        req = urllib.request.Request(url, data=data)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            print(f"Telegram chunk {i+1}/{len(chunks)} OK: {resp.status}")
        except Exception as e:
            print(f"Send failed: {e}")
            return False
    return True


def main():
    if EOD_MODE:
        print("EOD_MODE — building clean 3:30 PM summary")
        msg = build_eod_message()
    else:
        msg = build_full_message()
    if msg is None:
        print("Skipped (alert-only, no signals)")
        return
    print("=" * 60)
    print(msg[:2000])
    print("=" * 60)
    if BOT_TOKEN and CHAT_ID:
        send_telegram(msg)
    else:
        print("(Dry-run mode)")


if __name__ == "__main__":
    main()
