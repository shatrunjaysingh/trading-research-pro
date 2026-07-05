"""
Price alert checker — checks active alerts against current prices.
Runs every 5 minutes via the main scheduler.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

CONDITION_LABELS = {
    'above': 'Price rose above target',
    'below': 'Price fell below target',
    'breakout_52w_high': '52-week high breakout',
    'breakdown_52w_low': '52-week low breakdown',
    'cross_sma50_up': 'Crossed above 50-day SMA',
    'cross_sma50_down': 'Crossed below 50-day SMA',
    'cross_sma200_up': 'Crossed above 200-day SMA',
    'cross_sma200_down': 'Crossed below 200-day SMA',
}


def _check_ticker_alerts(ticker: str, alerts: list[dict]) -> list[tuple[dict, str]]:
    """Returns list of (alert, message) for triggered alerts."""
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        fi = tk.fast_info
        price = float(fi.last_price) if fi.last_price else None
        if not price:
            return []

        high_52w = float(fi.year_high) if hasattr(fi, 'year_high') and fi.year_high else None
        low_52w  = float(fi.year_low)  if hasattr(fi, 'year_low')  and fi.year_low  else None

        # Fetch SMA50 and SMA200
        hist = tk.history(period="1y", interval="1d", auto_adjust=True)
        sma50 = sma200 = prev_close = None
        if len(hist) >= 2:
            prev_close = float(hist['Close'].iloc[-2])
        if len(hist) >= 50:
            sma50 = float(hist['Close'].rolling(50).mean().iloc[-1])
        if len(hist) >= 200:
            sma200 = float(hist['Close'].rolling(200).mean().iloc[-1])

        triggered = []
        for alert in alerts:
            cond   = alert['condition']
            target = float(alert['target_price']) if alert.get('target_price') else None
            msg    = None

            if   cond == 'above'           and target and price >= target:
                msg = f"{ticker} is above ${target:.2f} — now ${price:.2f}"
            elif cond == 'below'           and target and price <= target:
                msg = f"{ticker} is below ${target:.2f} — now ${price:.2f}"
            elif cond == 'breakout_52w_high' and high_52w and price >= high_52w * 0.995:
                msg = f"{ticker} broke out to 52W high! ${price:.2f} (high: ${high_52w:.2f})"
            elif cond == 'breakdown_52w_low' and low_52w and price <= low_52w * 1.005:
                msg = f"{ticker} broke down to 52W low! ${price:.2f} (low: ${low_52w:.2f})"
            elif cond == 'cross_sma50_up'  and sma50 and prev_close and price > sma50 and prev_close <= sma50:
                msg = f"{ticker} crossed above 50-day SMA (${sma50:.2f}) — now ${price:.2f}"
            elif cond == 'cross_sma50_down' and sma50 and prev_close and price < sma50 and prev_close >= sma50:
                msg = f"{ticker} crossed below 50-day SMA (${sma50:.2f}) — now ${price:.2f}"
            elif cond == 'cross_sma200_up' and sma200 and prev_close and price > sma200 and prev_close <= sma200:
                msg = f"{ticker} crossed above 200-day SMA (${sma200:.2f}) — now ${price:.2f}"
            elif cond == 'cross_sma200_down' and sma200 and prev_close and price < sma200 and prev_close >= sma200:
                msg = f"{ticker} crossed below 200-day SMA (${sma200:.2f}) — now ${price:.2f}"

            if msg:
                triggered.append((alert, msg))

        return triggered
    except Exception as exc:
        logger.debug("Alert check failed for %s: %s", ticker, exc)
        return []


def check_price_alerts() -> dict:
    """Check all active price alerts. Returns {checked, triggered}."""
    import database as db
    try:
        alerts = db.get_active_price_alerts()
        if not alerts:
            return {"checked": 0, "triggered": 0}

        from collections import defaultdict
        by_ticker: dict[str, list] = defaultdict(list)
        for a in alerts:
            by_ticker[a['ticker']].append(a)

        all_triggered = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_check_ticker_alerts, t, a_list): t for t, a_list in by_ticker.items()}
            for f in as_completed(futs):
                all_triggered.extend(f.result())

        from backend.services.email_service import send_email
        sent = 0
        for alert, msg in all_triggered:
            try:
                note_html = f'<p style="font-size:13px;color:#64748b;margin-top:8px;">Your note: <em>{alert["note"]}</em></p>' if alert.get('note') else ''
                html = f"""<div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
<div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:white;padding:28px;border-radius:8px 8px 0 0;">
  <div style="font-size:22px;font-weight:800;">🔔 Price Alert</div>
  <div style="font-size:13px;opacity:.8;margin-top:4px;">{alert['ticker']} · {CONDITION_LABELS.get(alert['condition'], alert['condition'])}</div>
</div>
<div style="background:#fff;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;padding:24px;">
  <p style="font-size:17px;font-weight:600;color:#1e293b;margin:0 0 8px;">{msg}</p>
  {note_html}
  <p style="font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:12px;margin-top:20px;">
    Not investment advice. Prices may be delayed ~15 min.</p>
</div></div>"""
                ok = send_email(to_email=alert['email'], subject=f"🔔 Alert triggered: {alert['ticker']}", html_body=html)
                if ok:
                    sent += 1
                db.mark_alert_triggered(alert['id'])
            except Exception as exc:
                logger.error("Alert send failed %d: %s", alert['id'], exc)

        return {"checked": len(alerts), "triggered": len(all_triggered), "sent": sent}
    except Exception as exc:
        logger.error("check_price_alerts error: %s", exc)
        return {"checked": 0, "triggered": 0, "error": str(exc)}
