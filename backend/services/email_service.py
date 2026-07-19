"""
Email service — sends HTML emails via Gmail SMTP (or any SMTP provider).
Configure via environment variables:
  EMAIL_SENDER       = your-email@gmail.com
  EMAIL_APP_PASSWORD = Gmail app password (not your main password)
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send HTML email via SendGrid (preferred) or Gmail SMTP (fallback)."""
    from backend.config import settings

    sg_key = settings.sendgrid_api_key.strip()
    if sg_key:
        return _send_via_sendgrid(to_email, subject, html_body, sg_key, settings.email_sender.strip())

    # SMTP fallback (works locally, blocked on Render free tier)
    return _send_via_smtp(to_email, subject, html_body, text_body,
                          settings.email_sender.strip(), settings.email_app_password.strip())


def _send_via_sendgrid(to_email: str, subject: str, html_body: str, api_key: str, from_email: str) -> bool:
    import requests
    from_email = from_email or "noreply@tradingresearchpro.com"
    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email, "name": "TradingResearch Pro"},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_body}],
            },
            timeout=15,
        )
        if resp.status_code == 202:
            logger.info("SendGrid: sent to %s", to_email)
            return True
        logger.error("SendGrid error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"SendGrid {resp.status_code}: {resp.text}")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("SendGrid request failed: %s", exc)
        raise


def _send_via_smtp(to_email: str, subject: str, html_body: str, text_body: str,
                   sender: str, password: str) -> bool:
    import ssl
    if not sender or not password:
        raise RuntimeError("EMAIL_SENDER and EMAIL_APP_PASSWORD are not configured")
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = sender
        msg["To"]      = to_email
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [to_email], msg.as_string())
        logger.info("SMTP: sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("SMTP send failed to %s: %s", to_email, exc)
        raise


def _signal_emoji(signal: str) -> str:
    return {"strong buy": "🟢🟢", "buy": "🟢", "watch": "🔵", "hold": "🟡", "sell": "🔴"}.get(signal, "⚪")


def _score_bar(score: float) -> str:
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)


def build_portfolio_section_html(holdings: list[dict]) -> str:
    """Build the portfolio review section for the digest email."""
    if not holdings:
        return ""

    action_styles = {
        "add_more": ("ADD MORE", "#dcfce7", "#166534"),
        "hold":     ("HOLD",     "#dbeafe", "#1d4ed8"),
        "reduce":   ("REDUCE",   "#fef3c7", "#92400e"),
        "sell":     ("SELL",     "#fee2e2", "#991b1b"),
    }

    rows = ""
    for h in holdings:
        if h.get("error"):
            continue
        action = h.get("action", "hold")
        label, bg, fg = action_styles.get(action, ("HOLD", "#dbeafe", "#1d4ed8"))
        pnl_pct   = h.get("pnl_pct")
        pnl_s     = f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—"
        pnl_color = "#16a34a" if (pnl_pct or 0) >= 0 else "#dc2626"
        st        = h.get("st_score", 0)
        lt        = h.get("lt_score") or 0
        rs        = h.get("rs_score", 0)
        price_s   = f"${h['current_price']:,.2f}" if h.get("current_price") else "—"
        reason    = (h.get("action_reasons") or [""])[0]

        rows += f"""
<tr>
  <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;">
    <strong style="font-size:14px;">{h['ticker']}</strong>
    <div style="font-size:11px;color:#64748b;">{h.get('company','')}</div>
  </td>
  <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:center;">
    <span style="background:{bg};color:{fg};padding:3px 10px;border-radius:99px;font-size:11px;font-weight:700;">{label}</span>
  </td>
  <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:center;font-size:12px;">
    ST&nbsp;<strong>{st:.0f}</strong> · LT&nbsp;<strong>{lt:.0f}</strong> · RS&nbsp;<strong>{rs}</strong>
  </td>
  <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
    <strong>{price_s}</strong>
    <div style="color:{pnl_color};font-size:12px;">{pnl_s}</div>
  </td>
  <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#475569;max-width:220px;">{reason}</td>
</tr>"""

    if not rows:
        return ""

    return f"""
  <div class="section" style="background:#f0fdf4;border-left:4px solid #16a34a;">
    <h2 style="color:#166534;">📊 Your Portfolio Review</h2>
    <p style="font-size:13px;color:#475569;margin-bottom:16px;">
      Personalised daily analysis of your saved holdings — what to add to, hold, trim, or exit today.
    </p>
    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <th style="text-align:left;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;">Stock</th>
        <th style="text-align:center;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;">Action</th>
        <th style="text-align:center;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;">Scores</th>
        <th style="text-align:right;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;">Price / P&L</th>
        <th style="text-align:left;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;">Key Reason</th>
      </tr>
      {rows}
    </table>
  </div>"""


def build_digest_html(
    picks: list[dict],
    user_name: str,
    date_str: str,
    portfolio_holdings: list[dict] | None = None,
) -> str:
    """Build the HTML body for a daily digest email."""

    st_picks    = [p for p in picks if p.get("horizon") == "short"]
    lt_picks    = [p for p in picks if p.get("horizon") == "long"]
    penny_picks = [p for p in picks if p.get("horizon") == "penny"]
    mid_picks   = [p for p in picks if p.get("horizon") == "mid"]

    def pick_rows(items: list[dict]) -> str:
        rows = ""
        for p in items:
            signal    = p.get("signal", "watch")
            composite = p.get("composite")
            rating    = composite if composite is not None else p.get("score", 50)
            emoji     = _signal_emoji(signal)
            rs        = p.get("rs_score", "—")
            price     = p.get("price")
            price_s   = f"${price:,.2f}" if price else "—"
            chg       = p.get("day_change_pct")
            chg_s     = f"{chg:+.2f}%" if chg is not None else "—"
            chg_color = "#16a34a" if (chg or 0) >= 0 else "#dc2626"

            val = p.get("valuation")
            if val and val.get("fair_value"):
                up = val.get("upside_pct", 0) or 0
                up_color = "#16a34a" if up >= 0 else "#dc2626"
                fv_html = (f"<strong>${val['fair_value']:,.2f}</strong><br>"
                           f"<span style=\"color:{up_color};font-size:11px;\">{up:+.1f}%</span>")
            else:
                fv_html = "<span style=\"color:#94a3b8;\">—</span>"

            reasons = p.get("reasoning", [])
            top_reason = reasons[0] if reasons else ""
            rows += f"""
<tr>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;">
    <strong style="font-size:16px;color:#1e293b;">{p['ticker']}</strong>
    <br><span style="font-size:12px;color:#64748b;">{p.get('company','')}</span>
  </td>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;text-align:center;">
    <strong style="font-size:18px;color:#1e293b;">{rating:.0f}</strong><span style="color:#94a3b8;">/100</span><br>
    <span style="font-size:11px;">{emoji} {signal.upper()}</span>
  </td>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;text-align:center;">
    <span style="font-size:13px;font-weight:bold;">{rs}</span><br>
    <span style="font-size:11px;color:#94a3b8;">RS</span>
  </td>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
    <strong>{price_s}</strong><br>
    <span style="color:{chg_color};font-size:12px;">{chg_s}</span>
  </td>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
    {fv_html}
  </td>
  <td style="padding:12px 8px;border-bottom:1px solid #e2e8f0;font-size:12px;color:#475569;max-width:220px;">
    {top_reason}
  </td>
</tr>"""
        return rows or "<tr><td colspan='6' style='padding:16px;color:#94a3b8;text-align:center;'>No picks meeting threshold today</td></tr>"

    disclaimer = """<p style="font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:16px;margin-top:24px;">
⚠️ <strong>Not investment advice.</strong> This digest is generated by AI algorithms using publicly available data.
It is provided for informational and research purposes only. Always do your own research and consult a qualified
financial advisor before making any investment decisions. Past performance does not guarantee future results.
Market data may be delayed up to 15 minutes.</p>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1e293b;background:#f8fafc;margin:0;padding:0;}}
  .container {{max-width:700px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);}}
  .header {{background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:32px;color:#fff;}}
  .section {{padding:24px;}}
  table {{width:100%;border-collapse:collapse;}}
  th {{text-align:left;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px;border-bottom:2px solid #e2e8f0;}}
  h2 {{font-size:16px;font-weight:700;color:#1e293b;margin:0 0 16px;padding-bottom:8px;border-bottom:2px solid #e2e8f0;}}
  .badge {{display:inline-block;padding:3px 10px;border-radius:99px;font-size:11px;font-weight:700;}}
  .st-badge {{background:#dcfce7;color:#166534;}}
  .lt-badge {{background:#dbeafe;color:#1d4ed8;}}
</style></head>
<body>
<div class="container">
  <div class="header">
    <div style="font-size:24px;font-weight:800;margin-bottom:4px;">📈 TradingResearch Pro</div>
    <div style="font-size:14px;opacity:.8;">Daily Market Digest · {date_str}</div>
    <div style="font-size:13px;opacity:.7;margin-top:4px;">Good morning, {user_name}</div>
  </div>

  <div class="section">
    <h2>🚀 <span class="badge st-badge">SHORT-TERM</span> &nbsp; Top picks for the next 1–4 weeks</h2>
    <p style="font-size:13px;color:#64748b;margin-bottom:16px;">
      Ranked by the cross-sectional factor <strong>Rating</strong> (momentum, quality, value, growth, revisions), RS Rating and near-term momentum.
      Financially distressed names are screened out.
    </p>
    <table>
      <tr>
        <th>Stock</th><th style="text-align:center;">Rating</th><th style="text-align:center;">RS</th><th style="text-align:right;">Price</th><th style="text-align:right;">Fair Value</th><th>Top Reason</th>
      </tr>
      {pick_rows(st_picks)}
    </table>
  </div>

  <div class="section" style="background:#f8fafc;">
    <h2>🏗️ <span class="badge lt-badge">LONG-TERM</span> &nbsp; Quality growth stocks for 3–12 months</h2>
    <p style="font-size:13px;color:#64748b;margin-bottom:16px;">
      Ranked by the factor <strong>Rating</strong> with a quality/valuation tilt (EPS growth, ROE, margins, fair value), RS Rating and trend structure.
      Distressed balance sheets are excluded, and <strong>Fair Value</strong> shows worth vs price.
    </p>
    <table>
      <tr>
        <th>Stock</th><th style="text-align:center;">Rating</th><th style="text-align:center;">RS</th><th style="text-align:right;">Price</th><th style="text-align:right;">Fair Value</th><th>Top Reason</th>
      </tr>
      {pick_rows(lt_picks)}
    </table>
  </div>

  <div class="section">
    <h2>💰 <span class="badge" style="background:#fef3c7;color:#92400e;">SUB-$5</span> &nbsp; Top stocks under $5</h2>
    <p style="font-size:13px;color:#64748b;margin-bottom:16px;">
      Low-priced names screened from the broad market and scored on the same factor engine. Higher risk — distressed balance sheets are excluded.
    </p>
    <table>
      <tr>
        <th>Stock</th><th style="text-align:center;">Rating</th><th style="text-align:center;">RS</th><th style="text-align:right;">Price</th><th style="text-align:right;">Fair Value</th><th>Top Reason</th>
      </tr>
      {pick_rows(penny_picks)}
    </table>
  </div>

  <div class="section" style="background:#f8fafc;">
    <h2>📊 <span class="badge" style="background:#e0f2fe;color:#0369a1;">$5–$25</span> &nbsp; Top stocks priced $5 to $25</h2>
    <p style="font-size:13px;color:#64748b;margin-bottom:16px;">
      Mid-priced names screened from the broad market and scored on the same factor engine, with <strong>Fair Value</strong> vs price. Distressed balance sheets are excluded.
    </p>
    <table>
      <tr>
        <th>Stock</th><th style="text-align:center;">Rating</th><th style="text-align:center;">RS</th><th style="text-align:right;">Price</th><th style="text-align:right;">Fair Value</th><th>Top Reason</th>
      </tr>
      {pick_rows(mid_picks)}
    </table>
  </div>

  {build_portfolio_section_html(portfolio_holdings or [])}

  <div class="section">
    <h3 style="font-size:14px;color:#1e293b;margin-bottom:12px;">📖 How to use this digest</h3>
    <ul style="font-size:13px;color:#475569;line-height:1.8;padding-left:20px;">
      <li><strong>Rating (/100)</strong>: a cross-sectional blend of six factors — momentum, quality, value, growth, analyst revisions and low-volatility — ranked vs the large-cap universe. 65+ leans Buy. Financially distressed names are auto-excluded from picks.</li>
      <li><strong>Fair Value</strong>: an estimate of what the business is worth (earnings power + analyst consensus) vs today's price. A positive % = potential upside / margin of safety. It's an estimate, not a promise.</li>
      <li><strong>RS Rating</strong>: 80+ = outperforming 80% of all stocks. Strong RS before a breakout is a good sign.</li>
      <li><strong>Risk management</strong>: Never risk more than 1–2% of capital on a single trade. Size by conviction and use a stop (≈1.5× ATR below entry).</li>
    </ul>
    {disclaimer}
  </div>
</div>
</body></html>"""
