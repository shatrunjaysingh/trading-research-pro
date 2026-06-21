"""
TradingResearch Pro — Enterprise Edition
"""

import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import pytz
import streamlit as st

from database import (
    init_db,
    get_all_users,
    get_all_licenses,
    get_license_by_id,
    get_user_count_for_license,
    create_user,
    update_user,
    change_password,
    create_license,
    update_license,
    get_audit_log,
    log_audit,
)

init_db()

from auth import (
    login,
    logout,
    register,
    validate_token,
    has_permission,
    can_use_mode,
    can_use_sector,
    get_max_picks,
    validate_email,
    validate_password,
    validate_username,
    ROLE_LABELS,
    TIER_BADGE_COLOR,
)

from research import (
    PICKS_PER_CATEGORY,
    SECTOR_LABELS,
    load_config,
    run_research,
)

st.set_page_config(
    page_title="TradingResearch Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS: only things config.toml cannot do ─────────────────────────────────────
st.markdown("""
<style>
/* Sidebar dark background — this works reliably */
section[data-testid="stSidebar"] {
    background-color: #0F172A !important;
}
section[data-testid="stSidebar"] > div {
    background-color: #0F172A !important;
}
/* Sidebar text to light */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] .stMarkdown {
    color: #CBD5E1 !important;
}
/* Sidebar buttons */
section[data-testid="stSidebar"] .stButton > button {
    background-color: #1E293B !important;
    border: 1px solid #334155 !important;
    color: #CBD5E1 !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    width: 100% !important;
    text-align: left !important;
    transition: all 0.15s !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #334155 !important;
    color: #F1F5F9 !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background-color: #1D4ED8 !important;
    border-color: #1D4ED8 !important;
    color: #FFFFFF !important;
}
/* Sidebar radio / multiselect labels */
section[data-testid="stSidebar"] .stRadio > label > div,
section[data-testid="stSidebar"] .stMultiSelect > label,
section[data-testid="stSidebar"] .stSlider > label,
section[data-testid="stSidebar"] .stNumberInput > label,
section[data-testid="stSidebar"] .stCheckbox > label {
    color: #94A3B8 !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.07em !important;
}
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] .stCaption p {
    color: #64748B !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #1E293B !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background-color: #F1F5F9;
    padding: 4px;
    border-radius: 10px;
    border: 1px solid #E2E8F0;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px;
    font-size: 0.82rem;
    font-weight: 600;
    color: #64748B;
    padding: 6px 14px;
    background: transparent;
    border: none;
}
.stTabs [aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: #0F172A !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

/* ── Cards ── */
.pick-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.pick-header {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}
.pick-ticker  { font-size: 1.3rem; font-weight: 800; color: #0F172A; }
.pick-company { font-size: 0.82rem; color: #64748B; }
.pick-price   { font-size: 1.1rem; font-weight: 700; color: #0F172A; margin-left: auto; text-align: right; }
.chip {
    display: inline-block; padding: 3px 10px;
    border-radius: 20px; font-size: 0.71rem; font-weight: 700;
    letter-spacing: 0.03em;
}
.chip-rank    { background: #F1F5F9; color: #64748B; }
.chip-score   { background: #F1F5F9; color: #334155; }
.chip-conf    { background: #F5F3FF; color: #6D28D9; }
.chip-buy     { background: #DCFCE7; color: #15803D; }
.chip-watch   { background: #DBEAFE; color: #1D4ED8; }
.chip-hold    { background: #FEF9C3; color: #92400E; }
.chip-sell    { background: #FEE2E2; color: #DC2626; }
.chg-pos      { font-size: 0.8rem; font-weight: 600; color: #16A34A; }
.chg-neg      { font-size: 0.8rem; font-weight: 600; color: #DC2626; }

/* ── Section labels ── */
.sec-label {
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.09em;
    text-transform: uppercase; color: #94A3B8; margin: 12px 0 3px;
}
.sec-val { font-size: 0.875rem; color: #334155; line-height: 1.6; }

/* ── Trade levels ── */
.trade-bar {
    display: flex; gap: 0; margin-top: 10px;
    background: #F8FAFC; border-radius: 10px; overflow: hidden;
    border: 1px solid #E2E8F0;
}
.trade-cell { flex: 1; padding: 10px 14px; text-align: center; border-right: 1px solid #E2E8F0; }
.trade-cell:last-child { border-right: none; }
.trade-cell-lbl { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #94A3B8; }
.trade-cell-val { font-size: 0.95rem; font-weight: 700; margin-top: 3px; }
.t-entry  { color: #1D4ED8; }
.t-target { color: #15803D; }
.t-stop   { color: #DC2626; }
.t-upside { color: #7C3AED; }
.t-horiz  { color: #0F172A; }

/* ── Risk items ── */
.risk-row {
    background: #FFFBEB; border-left: 3px solid #F59E0B;
    border-radius: 0 6px 6px 0; padding: 5px 10px;
    font-size: 0.8rem; color: #78350F; margin-bottom: 4px;
}

/* ── Market banner ── */
.mkt-banner {
    background: linear-gradient(135deg, #EFF6FF, #F0FDF4);
    border: 1px solid #BFDBFE; border-radius: 10px;
    padding: 12px 16px; font-size: 0.875rem; color: #1E3A5F;
    margin-bottom: 16px; line-height: 1.6;
}
.avoid-banner {
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 10px; padding: 10px 16px;
    font-size: 0.83rem; color: #78350F; margin-top: 10px;
}

/* ── KPI row ── */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 24px;
}
.kpi-box {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.kpi-val   { font-size: 2rem; font-weight: 800; color: #0F172A; line-height: 1; }
.kpi-lbl   { font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
              letter-spacing: 0.08em; color: #94A3B8; margin-top: 5px; }

/* ── Badges ── */
.badge {
    display: inline-block; padding: 2px 9px; border-radius: 20px;
    font-size: 0.68rem; font-weight: 700; color: #fff !important;
    letter-spacing: 0.02em;
}
.b-admin    { background: #DC2626; }
.b-analyst  { background: #2563EB; }
.b-trader   { background: #059669; }
.b-viewer   { background: #6B7280; }
.b-free         { background: #475569; }
.b-professional { background: #2563EB; }
.b-enterprise   { background: #7C3AED; }

/* ── User card in sidebar ── */
.user-card {
    background: #1E293B; border-radius: 10px;
    padding: 12px 14px; margin: 8px 0 16px;
}
.user-name  { font-size: 0.9rem; font-weight: 600; color: #F1F5F9 !important; }
.user-email { font-size: 0.73rem; color: #64748B !important; margin-top: 1px; }
.user-badges { margin-top: 8px; }

/* ── License card ── */
.lic-card {
    background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 12px; padding: 16px; margin-bottom: 12px;
}
.lic-name { font-size: 0.95rem; font-weight: 700; color: #0F172A; }
.lic-meta { font-size: 0.78rem; color: #64748B; margin: 6px 0; line-height: 1.9; }
.lic-feat {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.7rem; font-weight: 600; margin: 1px 2px;
}
.lic-on  { background: #DCFCE7; color: #15803D; }
.lic-off { background: #F1F5F9; color: #94A3B8; }

/* ── Profile info table ── */
.info-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #F1F5F9;
}
.info-key { font-size: 0.8rem; color: #94A3B8; font-weight: 600; }
.info-val { font-size: 0.875rem; color: #0F172A; font-weight: 500; }

/* ── Sidebar brand ── */
.sb-brand {
    font-size: 1rem; font-weight: 800; color: #F1F5F9 !important;
    letter-spacing: -0.2px; padding: 4px 0 16px;
    display: flex; align-items: center; gap: 8px;
}

/* ── Page header ── */
.pg-title { font-size: 1.55rem; font-weight: 800; color: #0F172A; letter-spacing: -0.3px; }
.pg-sub   { font-size: 0.82rem; color: #64748B; margin-top: 2px; }

/* ── Auth page ── */
.auth-hero {
    text-align: center; padding: 32px 0 20px;
}
.auth-icon  { font-size: 3rem; line-height: 1; }
.auth-title { font-size: 1.8rem; font-weight: 800; color: #0F172A; letter-spacing: -0.5px; margin-top: 8px; }
.auth-sub   { font-size: 0.875rem; color: #64748B; margin-top: 4px; }

/* ── Footer ── */
.footer {
    border-top: 1px solid #E2E8F0; margin-top: 2rem;
    padding-top: 0.75rem; font-size: 0.72rem; color: #94A3B8;
    display: flex; justify-content: space-between;
}

/* ── Expander tweaks ── */
details[data-testid="stExpander"] {
    border: 1px solid #E2E8F0 !important;
    border-radius: 10px !important;
    background: #FAFBFD;
}

/* ── Perm row ── */
.perm-row { font-size: 0.85rem; padding: 4px 0; }
.perm-on  { color: #15803D; }
.perm-off { color: #94A3B8; }
</style>
""", unsafe_allow_html=True)


# ── Constants ──────────────────────────────────────────────────────────────────
_SECTOR_TAB = {
    "technology":  "💻 Tech",
    "pharma":      "💊 Pharma",
    "healthcare":  "🏥 Health",
    "finance":     "🏦 Finance",
    "energy":      "⚡ Energy",
    "consumer":    "🛍 Consumer",
    "industrials": "🏭 Industrials",
    "crypto":      "₿ Crypto",
    "penny":       "💰 Penny",
}
_ALL_SECTORS = ["technology","pharma","healthcare","finance","energy","consumer","industrials","crypto","penny"]
_ROLE_CLS = {"admin":"b-admin","analyst":"b-analyst","trader":"b-trader","viewer":"b-viewer"}
_TIER_CLS = {"free":"b-free","professional":"b-professional","enterprise":"b-enterprise"}
_SIG_CLS  = {"BUY":"chip-buy","WATCH":"chip-watch","HOLD":"chip-hold","SELL":"chip-sell"}
_SIG_ICON = {"BUY":"🟢","WATCH":"🔵","HOLD":"🟡","SELL":"🔴"}


# ── Log capture ────────────────────────────────────────────────────────────────
class _UILogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
    def emit(self, record):
        self.lines.append(self.format(record))


# ── Tiny HTML helpers ──────────────────────────────────────────────────────────
def _badge(text, cls): return f"<span class='badge {cls}'>{text}</span>"
def _chip(text, cls):  return f"<span class='chip {cls}'>{text}</span>"
def _role_badge(role): return _badge(ROLE_LABELS.get(role, role.title()), _ROLE_CLS.get(role,"b-viewer"))
def _tier_badge(tier): return _badge(tier.title(), _TIER_CLS.get(tier,"b-free"))
def _sig_chip(sig):    return _chip(sig, _SIG_CLS.get(sig,"chip-hold"))

def _chg_html(val):
    try:
        v = float(val)
        cls = "chg-pos" if v >= 0 else "chg-neg"
        arr = "▲" if v >= 0 else "▼"
        return f"<span class='{cls}'>{arr}{abs(v):.2f}%</span>"
    except Exception:
        return "<span style='color:#94A3B8'>—</span>"

def _hl_signal(v):
    m = {"BUY":"background:#DCFCE7;color:#15803D;font-weight:700",
         "WATCH":"background:#DBEAFE;color:#1D4ED8;font-weight:700",
         "HOLD":"background:#FEF9C3;color:#92400E;font-weight:700",
         "SELL":"background:#FEE2E2;color:#DC2626;font-weight:700"}
    for k, s in m.items():
        if k in str(v): return s
    return ""


# ── Pick card renderers ────────────────────────────────────────────────────────

def _api_pick_card(p: dict, idx: int):
    signal  = p.get("signal", "")
    ticker  = p.get("ticker", "?")
    company = p.get("company_name", "")
    price   = f"${p.get('current_price','?')}"
    score   = p.get("score","—")
    conf    = f"{p['confidence_pct']}%" if p.get("confidence_pct") else "—"
    rank    = p.get("rank", idx)
    day_ch  = p.get("day_change_pct", 0)

    label = f"#{rank}  {ticker}  ·  {company}  ·  {signal}  ·  {price}"
    with st.expander(label, expanded=False):
        st.markdown(
            f"<div class='pick-header'>"
            f"{_chip(f'#{rank}','chip-rank')}"
            f"<div><div class='pick-ticker'>{ticker}</div><div class='pick-company'>{company}</div></div>"
            f"{_sig_chip(signal)}"
            f"{_chip(f'Score {score}','chip-score')}"
            f"{_chip(f'⬡ {conf}','chip-conf')}"
            f"<div class='pick-price'>{price}<br>{_chg_html(day_ch)}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        left, right = st.columns(2)
        with left:
            for field, label_txt in [
                ("why_picked","Why Picked"),("key_catalyst","Key Catalyst"),
                ("sector_tailwind","Sector Tailwind"),("technical_analysis","Technical Analysis"),
                ("fundamental_snapshot","Fundamentals"),("why_its_cheap","Why It's Cheap"),
                ("business_viability","Business Viability"),("financial_health","Financial Health"),
            ]:
                val = p.get(field)
                if val:
                    st.markdown(f"<div class='sec-label'>{label_txt}</div><div class='sec-val'>{val}</div>", unsafe_allow_html=True)

        with right:
            if p.get("news_summary"):
                sent = p.get("news_sentiment","")
                st.markdown(
                    f"<div class='sec-label'>Latest News</div>"
                    f"<div class='sec-val'>{p['news_summary']}"
                    + (f" <em style='color:#94A3B8'>({sent})</em>" if sent else "") + "</div>",
                    unsafe_allow_html=True,
                )
            if p.get("analyst_sentiment"):
                st.markdown(f"<div class='sec-label'>Analyst View</div><div class='sec-val'>{p['analyst_sentiment']}</div>", unsafe_allow_html=True)

            e = f"${p['suggested_entry']}" if p.get("suggested_entry") else "—"
            t = f"${p['target_price']}"    if p.get("target_price")    else "—"
            s = f"${p['stop_loss']}"       if p.get("stop_loss")       else "—"
            u = f"{p['upside_pct']:.1f}%"  if p.get("upside_pct")      else "—"
            h = p.get("time_horizon","—")
            st.markdown(
                f"<div class='sec-label' style='margin-top:14px'>Trade Levels</div>"
                f"<div class='trade-bar'>"
                f"<div class='trade-cell'><div class='trade-cell-lbl'>Entry</div><div class='trade-cell-val t-entry'>{e}</div></div>"
                f"<div class='trade-cell'><div class='trade-cell-lbl'>Target</div><div class='trade-cell-val t-target'>{t}</div></div>"
                f"<div class='trade-cell'><div class='trade-cell-lbl'>Stop</div><div class='trade-cell-val t-stop'>{s}</div></div>"
                f"<div class='trade-cell'><div class='trade-cell-lbl'>Upside</div><div class='trade-cell-val t-upside'>{u}</div></div>"
                f"<div class='trade-cell'><div class='trade-cell-lbl'>Horizon</div><div class='trade-cell-val t-horiz' style='font-size:0.8rem'>{h}</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            risks = p.get("risk_factors",[])
            if risks:
                st.markdown("<div class='sec-label' style='margin-top:14px'>Risk Factors</div>", unsafe_allow_html=True)
                for r in risks:
                    st.markdown(f"<div class='risk-row'>⚠ {r}</div>", unsafe_allow_html=True)


def _render_api_section(section: dict):
    data = section.get("data") or {}
    if not isinstance(data, dict):
        st.info("No data for this sector.")
        return

    if data.get("market_summary"):
        st.markdown(f"<div class='mkt-banner'>📊 <strong>Market Context</strong><br>{data['market_summary']}</div>", unsafe_allow_html=True)

    picks = data.get("top_picks", [])
    if not picks:
        st.info("No picks met the 90%+ confidence threshold today.")
        return

    rows = [{
        "Rank": f"#{p.get('rank','?')}", "Ticker": p.get("ticker",""),
        "Company": p.get("company_name",""), "Score": p.get("score",""),
        "Confidence": f"{p['confidence_pct']}%" if p.get("confidence_pct") else "—",
        "Signal": p.get("signal",""), "Price": f"${p.get('current_price','?')}",
        "Day %": f"{p.get('day_change_pct',0):+.1f}%",
        "Upside": f"{p['upside_pct']:.1f}%" if p.get("upside_pct") else "—",
    } for p in picks]
    st.dataframe(
        pd.DataFrame(rows).style.map(_hl_signal, subset=["Signal"]),
        hide_index=True, use_container_width=True,
        column_config={"Company": st.column_config.TextColumn(width="medium")},
    )
    st.write("")
    for i, p in enumerate(picks, 1):
        _api_pick_card(p, i)

    avoid = data.get("avoid_today",[])
    if avoid:
        reason = data.get("avoid_reason","")
        st.markdown(
            f"<div class='avoid-banner'>⚠️ <strong>Avoid today:</strong> {', '.join(avoid)}"
            + (f"<br>{reason}" if reason else "") + "</div>",
            unsafe_allow_html=True,
        )


def _render_free_section(section: dict):
    rows_data = section.get("data") or []
    if not rows_data:
        st.info("No qualifying picks today.")
        return

    def _sent_badge(r):
        lbl = r.get("sentiment_label", "")
        pct = r.get("sentiment_bullish", 50)
        if not lbl or lbl == "Neutral":
            return f"— ({pct}% 🐂)"
        return f"{lbl} ({pct}% 🐂)"

    rows = [{
        "Rank": f"#{i}", "Ticker": r["ticker"],
        "Type": r.get("type","stock").capitalize(),
        "Score": r["score"], "Signal": r["signal"],
        "Price": f"${r['current_price']:,.4f}",
        "Day %": f"{r['day_change_pct']:+.2f}%",
        "Vol Ratio": f"{r['vol_ratio']:.2f}x",
        "52w Pos": f"{r['pos_52w']:.1f}%",
        "Sentiment": _sent_badge(r),
    } for i, r in enumerate(rows_data, 1)]
    st.dataframe(
        pd.DataFrame(rows).style.map(_hl_signal, subset=["Signal"]),
        hide_index=True, use_container_width=True,
    )
    st.caption("Score = Momentum 39% · Volume 11% · RS 16% · Earnings 8% · Social Sentiment 6% · other 20%")
    st.write("")

    for i, r in enumerate(rows_data, 1):
        with st.expander(f"#{i}  {r['ticker']}  ·  Score {r['score']}  ·  {r['signal']}  ·  ${r['current_price']:,.4f}", expanded=False):
            st.markdown(
                f"<div class='pick-header'>"
                f"{_chip(f'#{i}','chip-rank')}"
                f"<span class='pick-ticker'>{r['ticker']}</span>"
                f"{_sig_chip(r['signal'])}"
                f"{_chip('Score ' + str(r['score']), 'chip-score')}"
                f"<div class='pick-price'>${r['current_price']:,.4f}<br>{_chg_html(r['day_change_pct'])}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if r.get("why_picked"):
                st.markdown(f"<div class='sec-label'>Why Picked</div><div class='sec-val'>{r['why_picked']}</div>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Day Change",   f"{r['day_change_pct']:+.2f}%")
            c2.metric("Volume Ratio", f"{r['vol_ratio']:.2f}x")
            c3.metric("52w Position", f"{r['pos_52w']:.1f}%")

            sent_lbl   = r.get("sentiment_label", "")
            sent_bull  = r.get("sentiment_bullish", 0)
            sent_bear  = r.get("sentiment_bearish", 0)
            st_total   = r.get("st_total", 0)
            rd_posts   = r.get("reddit_mentions", 0)
            fg_lbl     = r.get("fg_label") or ""
            sources    = r.get("sentiment_sources", [])
            if sources:
                bull_bar = int(sent_bull / 10)
                bear_bar = 10 - bull_bar
                bar_html = (
                    "<span style='color:#22c55e'>" + "█" * bull_bar + "</span>"
                    + "<span style='color:#ef4444'>" + "█" * bear_bar + "</span>"
                )
                src_str = " · ".join(sources)
                detail_parts = []
                if st_total:
                    detail_parts.append(f"StockTwits: {st_total} msgs")
                if fg_lbl:
                    detail_parts.append(f"Fear & Greed: {fg_lbl}")
                if rd_posts:
                    detail_parts.append(f"Reddit: {rd_posts} posts")
                st.markdown(
                    f"<div class='sec-label' style='margin-top:10px'>Social Sentiment "
                    f"<span style='font-weight:400;color:#94A3B8'>({src_str})</span></div>"
                    f"<div class='sec-val'>{bar_html} &nbsp;"
                    f"<b>{sent_lbl}</b> &nbsp;·&nbsp; "
                    f"🐂 {sent_bull}% bullish &nbsp;·&nbsp; 🐻 {sent_bear}% bearish<br>"
                    f"<small style='color:#94A3B8'>"
                    + " &nbsp;|&nbsp; ".join(detail_parts)
                    + "</small></div>",
                    unsafe_allow_html=True,
                )


def _render_section(section: dict):
    if section.get("mode") == "api":
        _render_api_section(section)
    else:
        _render_free_section(section)


# ── Session ────────────────────────────────────────────────────────────────────
for _k, _v in [("token", None), ("user", None), ("page", "research")]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

if st.session_state["token"]:
    try:
        r = validate_token(st.session_state["token"])
        if r:
            st.session_state["user"] = r
        else:
            st.session_state.update(token=None, user=None, page="research")
    except Exception:
        st.session_state.update(token=None, user=None, page="research")


# ── Auth page ──────────────────────────────────────────────────────────────────
def show_auth_page():
    _, mid, _ = st.columns([1, 1.05, 1])
    with mid:
        st.markdown(
            "<div class='auth-hero'>"
            "<div class='auth-icon'>📈</div>"
            "<div class='auth-title'>TradingResearch Pro</div>"
            "<div class='auth-sub'>Institutional-grade market intelligence</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        tab_in, tab_up = st.tabs(["Sign In", "Create Account"])

        with tab_in:
            with st.form("signin_form"):
                email_in = st.text_input("Email", placeholder="you@company.com")
                pwd_in   = st.text_input("Password", type="password", placeholder="••••••••")
                ok = st.form_submit_button("Sign In →", type="primary", use_container_width=True)
            if ok:
                if not email_in or not pwd_in:
                    st.error("Email and password are required.")
                else:
                    try:
                        u, err = login(email_in, pwd_in)
                        if err: st.error(err)
                        elif u:
                            st.session_state.update(token=u.get("token"), user=u, page="research")
                            st.rerun()
                        else: st.error("Login failed.")
                    except Exception as exc:
                        st.error(f"Error: {exc}")

        with tab_up:
            with st.form("signup_form"):
                fn  = st.text_input("Full Name",        placeholder="Jane Smith")
                em  = st.text_input("Email",            placeholder="you@company.com", key="reg_em")
                un  = st.text_input("Username",         placeholder="jsmith")
                pw  = st.text_input("Password",         type="password", key="reg_pw")
                cpw = st.text_input("Confirm Password", type="password")
                ok  = st.form_submit_button("Create Account →", use_container_width=True)
            if ok:
                err = (not fn.strip() and "Full name required.") or validate_email(em) \
                      or validate_username(un) or validate_password(pw) \
                      or (pw != cpw and "Passwords do not match.")
                if err:
                    st.error(err)
                else:
                    try:
                        u, reg_err = register(email=em, username=un, password=pw,
                                              full_name=fn.strip(), role="viewer", license_id=None)
                        if reg_err: st.error(reg_err)
                        elif u:
                            st.session_state.update(token=u.get("token"), user=u, page="research")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

        st.markdown(
            "<p style='text-align:center;font-size:0.72rem;color:#94A3B8;margin-top:20px'>"
            "Research only · Not financial advice</p>",
            unsafe_allow_html=True,
        )


# ── Sidebar ────────────────────────────────────────────────────────────────────
def show_sidebar(user: dict):
    with st.sidebar:
        role  = user.get("role", "viewer")
        tier  = user.get("license_tier", user.get("tier", "free"))
        name  = user.get("full_name") or user.get("username", "User")
        email = user.get("email", "")

        # Brand
        st.markdown(
            "<div class='sb-brand'>📈 &nbsp;TradingResearch Pro</div>",
            unsafe_allow_html=True,
        )

        # User card
        st.markdown(
            f"<div class='user-card'>"
            f"<div class='user-name'>{name}</div>"
            f"<div class='user-email'>{email}</div>"
            f"<div class='user-badges' style='margin-top:8px'>"
            f"{_role_badge(role)}&nbsp;{_tier_badge(tier)}"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        page = st.session_state.get("page", "research")

        st.button("🔍  Research",   key="nav_research",
                  use_container_width=True,
                  type="primary" if page == "research" else "secondary",
                  on_click=lambda: st.session_state.update(page="research"))

        if has_permission(user, "admin_panel"):
            st.button("⚙️  Admin Panel", key="nav_admin",
                      use_container_width=True,
                      type="primary" if page == "admin" else "secondary",
                      on_click=lambda: st.session_state.update(page="admin"))

        st.button("👤  My Profile", key="nav_profile",
                  use_container_width=True,
                  type="primary" if page == "profile" else "secondary",
                  on_click=lambda: st.session_state.update(page="profile"))

        st.divider()

        def _sign_out():
            try: logout(st.session_state["token"], user)
            except Exception: pass
            st.session_state.update(token=None, user=None, page="research")

        st.button("↩  Sign Out", use_container_width=True, on_click=_sign_out)

        lic_name = user.get("license_name", "Free Tier")
        exp      = user.get("expires_at")
        st.markdown(
            f"<div style='font-size:0.72rem;color:#475569;margin-top:12px;line-height:2'>"
            f"<b style='color:#64748B'>License</b> &nbsp;{lic_name}<br>"
            f"<b style='color:#64748B'>Expires</b> &nbsp;{'Never' if not exp else str(exp)[:10]}"
            f"</div>",
            unsafe_allow_html=True,
        )


# ── Research page ──────────────────────────────────────────────────────────────
def show_research_page(user: dict):
    with st.sidebar:
        st.divider()
        st.markdown("**Research Settings**")

        avail_modes  = [m for m in ["free","api"] if can_use_mode(user, m)] or ["free"]
        mode_labels  = {"free":"⚡ Free — instant (yfinance)", "api":"🔬 Deep — Claude AI (2-5 min)"}

        if len(avail_modes) == 1:
            mode_choice = avail_modes[0]
            st.info(mode_labels[mode_choice], icon="ℹ️")
            if mode_choice == "free":
                st.caption("🔒 Upgrade for Deep Research.")
        else:
            mode_choice = st.radio("Mode", avail_modes, format_func=lambda x: mode_labels[x])

        if mode_choice == "api" and not os.getenv("ANTHROPIC_API_KEY"):
            st.warning("ANTHROPIC_API_KEY not set.", icon="⚠️")

        st.markdown("**Filters**")
        max_price_input = st.number_input("Max price ($)", min_value=0.0, value=0.0, step=1.0, help="0 = no filter")
        max_price       = max_price_input if max_price_input > 0 else None

        _mcap_options = {
            "No minimum": 0,
            "$1M+":       1_000_000,
            "$5M+":       5_000_000,
            "$10M+":      10_000_000,
            "$25M+":      25_000_000,
            "$50M+":      50_000_000,
            "$100M+":     100_000_000,
            "$500M+":     500_000_000,
        }
        _mcap_label = st.selectbox(
            "Min mkt cap (Penny Stocks)",
            options=list(_mcap_options.keys()),
            index=3,  # $10M+ default
            help="Minimum market cap filter when screening penny / cheap stocks",
        )
        min_market_cap = _mcap_options[_mcap_label]

        max_picks = get_max_picks(user)
        top_n     = st.slider("Picks per sector", 1, max(max_picks, 1), min(5, max_picks))

        st.markdown("**Sectors**")
        _disp2key    = {SECTOR_LABELS.get(k, k.title()): k for k in _ALL_SECTORS}
        allowed_keys = [k for k in _ALL_SECTORS if can_use_sector(user, k)]
        allowed_disp = [SECTOR_LABELS.get(k, k.title()) for k in allowed_keys]

        sel_disp     = st.multiselect("Sectors", options=allowed_disp, default=[],
                                      placeholder="All sectors (default)",
                                      label_visibility="collapsed")
        sel_sectors  = [_disp2key[d] for d in sel_disp if d in _disp2key]

        locked = len(_ALL_SECTORS) - len(allowed_keys)
        if locked:
            st.caption(f"🔒 {locked} sector(s) require higher license.")

        send_email = False
        lic = None
        if user.get("license_id"):
            try: lic = get_license_by_id(user["license_id"])
            except Exception: pass
        if lic and lic.get("can_email"):
            st.markdown("**Delivery**")
            send_email = st.checkbox("📧 Email results")
            if send_email:
                cfg_e  = load_config()
                recips = cfg_e.get("email",{}).get("recipient",[])
                if isinstance(recips, str): recips = [recips]
                if recips: st.caption(f"→ {', '.join(recips)}")
                missing = [v for v in ("EMAIL_SENDER","EMAIL_APP_PASSWORD") if not os.getenv(v)]
                if missing: st.warning(f"Missing env: {', '.join(missing)}", icon="⚠️")

        st.divider()
        run_btn = st.button("▶  Run Research", type="primary", use_container_width=True)

    # ── Header
    et  = pytz.timezone("America/New_York")
    now = datetime.now(et)
    wday, hr, mn = now.weekday(), now.hour, now.minute
    market_open  = (wday < 5) and (9*60+30 <= hr*60+mn <= 16*60)
    mkt          = "🟢 Market Open" if market_open else "🔴 Market Closed"

    st.markdown(
        f"<div style='margin-bottom:1.5rem'>"
        f"<div class='pg-title'>Research Dashboard</div>"
        f"<div class='pg-sub'>{now.strftime('%A, %B %d %Y  ·  %H:%M ET')}  ·  {mkt}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not run_btn:
        col1, col2, col3 = st.columns(3)
        col1.info("**Step 1** — Choose mode (Free or Deep Research) in the sidebar")
        col2.info("**Step 2** — Pick sectors, or leave blank for all")
        col3.info("**Step 3** — Click **▶ Run Research**")
        st.stop()

    if not has_permission(user, "research"):
        st.error("No research permissions — contact your administrator.")
        st.stop()

    config      = load_config()
    email_cfg   = config.get("email") if send_email else None
    sectors_run = sel_sectors if sel_sectors else allowed_keys
    n           = len(sectors_run)

    if mode_choice == "api":
        est = n * 3
        st.info(f"🔬 Deep research on **{n}** sector(s) — est. **{est} min**. Please wait…")
        status_msg = f"Deep research · {n} sector(s) · ~{est} min"
    else:
        status_msg = f"⚡ Screening {n} sector(s)…"

    sections: list[dict] = []
    with st.status(status_msg, expanded=True) as sbox:
        log_slot = st.empty()
        handler  = _UILogHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            sections = run_research(config=config, selected_sectors=sectors_run,
                                    mode=mode_choice, max_price=max_price,
                                    top_n=top_n, email_cfg=email_cfg,
                                    min_market_cap=min_market_cap) or []
            sbox.update(label="✅ Research complete", state="complete", expanded=False)
            try:
                log_audit(user.get("id"), user.get("username",""), "run_research",
                          f"mode={mode_choice} sectors={sectors_run} top_n={top_n}")
            except Exception: pass
        except Exception as exc:
            sbox.update(label=f"❌ {exc}", state="error")
            st.exception(exc)
        finally:
            root_logger.removeHandler(handler)
            if handler.lines:
                log_slot.code("\n".join(handler.lines), language=None)

    if not sections:
        st.warning("No results returned.")
        st.stop()

    # KPI row
    total_picks = sum(
        len((s.get("data") or {}).get("top_picks", []) if isinstance(s.get("data"), dict) else (s.get("data") or []))
        for s in sections
    )
    hits = sum(1 for s in sections if (
        (s.get("data") or {}).get("top_picks") if isinstance(s.get("data"), dict) else s.get("data")
    ))
    st.markdown(
        f"<div class='kpi-grid'>"
        f"<div class='kpi-box'><div class='kpi-val'>{total_picks}</div><div class='kpi-lbl'>Total Picks</div></div>"
        f"<div class='kpi-box'><div class='kpi-val'>{hits}</div><div class='kpi-lbl'>Sectors With Picks</div></div>"
        f"<div class='kpi-box'><div class='kpi-val'>{n}</div><div class='kpi-lbl'>Sectors Scanned</div></div>"
        f"<div class='kpi-box'><div class='kpi-val' style='font-size:1.05rem;margin-top:4px'>{'Deep' if mode_choice=='api' else 'Free Scan'}</div><div class='kpi-lbl'>Mode</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if len(sections) == 1:
        _render_section(sections[0])
    else:
        tabs = st.tabs([_SECTOR_TAB.get(s.get("sector",""), s.get("label","")[:14]) for s in sections])
        for tab, section in zip(tabs, sections):
            with tab:
                _render_section(section)

    st.markdown(
        f"<div class='footer'><span>Research only — no trades placed</span>"
        f"<span>Generated {now.strftime('%Y-%m-%d %H:%M ET')}</span></div>",
        unsafe_allow_html=True,
    )

    if send_email and sections:
        recips = load_config().get("email",{}).get("recipient",[])
        if isinstance(recips, str): recips = [recips]
        st.success(f"📧 Report emailed to {', '.join(recips)}")


# ── Admin page ─────────────────────────────────────────────────────────────────
def show_admin_page(user: dict):
    if not has_permission(user, "admin_panel"):
        st.error("Administrator privileges required.")
        st.stop()

    st.markdown(
        "<div class='pg-title'>Admin Panel</div>"
        "<div class='pg-sub' style='margin-bottom:1.5rem'>Manage users, licenses, and review system activity</div>",
        unsafe_allow_html=True,
    )

    t_ov, t_usr, t_lic, t_aud = st.tabs(["📊 Overview","👥 Users","🔑 Licenses","📋 Audit Log"])

    # ── Overview
    with t_ov:
        try:
            all_u   = get_all_users()
            all_l   = get_all_licenses()
            total   = len(all_u)
            active  = sum(1 for u in all_u if u.get("is_active"))
            cutoff  = (datetime.utcnow()-timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            recent  = sum(1 for u in all_u if u.get("last_login") and str(u["last_login"]) >= cutoff)

            st.markdown(
                f"<div class='kpi-grid'>"
                f"<div class='kpi-box'><div class='kpi-val'>{total}</div><div class='kpi-lbl'>Total Users</div></div>"
                f"<div class='kpi-box'><div class='kpi-val'>{active}</div><div class='kpi-lbl'>Active</div></div>"
                f"<div class='kpi-box'><div class='kpi-val'>{recent}</div><div class='kpi-lbl'>Logins (24h)</div></div>"
                f"<div class='kpi-box'><div class='kpi-val'>{len(all_l)}</div><div class='kpi-lbl'>License Plans</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            role_counts = {}
            for u in all_u:
                r = u.get("role","viewer")
                role_counts[r] = role_counts.get(r,0)+1

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("By Role")
                st.dataframe(pd.DataFrame([
                    {"Role": ROLE_LABELS.get(r,r), "Users": c}
                    for r,c in role_counts.items()
                ]), hide_index=True, use_container_width=True)
            with col_b:
                st.subheader("License Plans")
                st.dataframe(pd.DataFrame([
                    {"Plan": l.get("name",""), "Tier": l.get("tier","").title(),
                     "Users": get_user_count_for_license(l["id"]) if l.get("id") else 0,
                     "Max": l.get("max_users","?")}
                    for l in all_l
                ]), hide_index=True, use_container_width=True)
        except Exception as exc:
            st.error(f"Failed: {exc}")

    # ── Users
    with t_usr:
        with st.expander("➕ Add New User", expanded=False):
            with st.form("cu_form"):
                c1, c2 = st.columns(2)
                cu_fn  = c1.text_input("Full Name")
                cu_em  = c2.text_input("Email")
                cu_un  = c1.text_input("Username")
                cu_pw  = c2.text_input("Password", type="password")
                cu_role = st.selectbox("Role", list(ROLE_LABELS.keys()), format_func=lambda r: ROLE_LABELS.get(r,r))
                try:
                    lics = get_all_licenses()
                    lo   = {f"{l['name']} ({l['tier']})": l["id"] for l in lics if l.get("is_active")}
                except Exception:
                    lo = {}
                cu_lic = st.selectbox("License", list(lo.keys()) or ["None"])
                cu_sub = st.form_submit_button("Create User", type="primary")
            if cu_sub:
                err = (not cu_fn.strip() and "Full name required.") or validate_email(cu_em) \
                      or validate_username(cu_un) or validate_password(cu_pw)
                if err: st.error(err)
                else:
                    try:
                        create_user(email=cu_em, username=cu_un, password=cu_pw,
                                    full_name=cu_fn.strip(), role=cu_role,
                                    license_id=lo.get(cu_lic), created_by=user.get("id"))
                        log_audit(user.get("id"), user.get("username",""), "create_user", f"Created {cu_em}")
                        st.success(f"User '{cu_un}' created.")
                        st.rerun()
                    except ValueError as ve: st.error(str(ve))
                    except Exception as exc: st.error(f"Failed: {exc}")

        try:
            all_u = get_all_users()
        except Exception as exc:
            st.error(f"Failed: {exc}"); all_u = []

        if all_u:
            st.dataframe(pd.DataFrame([{
                "Name": u.get("full_name",""), "Email": u.get("email",""),
                "Username": u.get("username",""),
                "Role": ROLE_LABELS.get(u.get("role","viewer"), u.get("role","")),
                "Status": "Active" if u.get("is_active") else "Inactive",
                "Last Login": str(u.get("last_login",""))[:16] if u.get("last_login") else "—",
            } for u in all_u]), hide_index=True, use_container_width=True)

            st.markdown("---")
            u_opts = {f"{u.get('full_name','')}  ({u.get('email','')})": u for u in all_u}
            sel    = st.selectbox("Select user to edit", list(u_opts.keys()))
            tgt    = u_opts.get(sel)
            if tgt:
                with st.expander(f"Edit — {tgt.get('full_name','')} ({tgt.get('email','')})", expanded=False):
                    with st.form(f"eu_{tgt['id']}"):
                        eu_fn    = st.text_input("Full Name", value=tgt.get("full_name",""))
                        eu_role  = st.selectbox("Role", list(ROLE_LABELS.keys()),
                                                index=list(ROLE_LABELS.keys()).index(tgt.get("role","viewer")) if tgt.get("role") in ROLE_LABELS else 0,
                                                format_func=lambda r: ROLE_LABELS.get(r,r))
                        try:
                            lics_e = get_all_licenses()
                            lo_e   = {"(None)": None}
                            lo_e.update({f"{l['name']} ({l['tier']})": l["id"] for l in lics_e})
                        except Exception:
                            lo_e = {"(None)": None}
                        cur_lbl = next((lbl for lbl,lid in lo_e.items() if lid==tgt.get("license_id")),"(None)")
                        eu_lic   = st.selectbox("License", list(lo_e.keys()),
                                                index=list(lo_e.keys()).index(cur_lbl) if cur_lbl in lo_e else 0)
                        eu_act   = st.checkbox("Active", value=bool(tgt.get("is_active",True)))
                        eu_force = st.checkbox("Force password change", value=bool(tgt.get("must_change_pwd",False)))
                        eu_sub   = st.form_submit_button("Save Changes", type="primary")
                    if eu_sub:
                        try:
                            update_user(tgt["id"], full_name=eu_fn.strip() or None,
                                        role=eu_role, license_id=lo_e.get(eu_lic),
                                        is_active=eu_act, must_change_pwd=eu_force)
                            log_audit(user.get("id"), user.get("username",""), "update_user", f"Updated {tgt['email']}")
                            st.success("Saved."); st.rerun()
                        except Exception as exc: st.error(f"Failed: {exc}")

                is_act = bool(tgt.get("is_active",True))
                if st.button(f"{'Deactivate' if is_act else 'Activate'}  {tgt.get('username','')}",
                             type="secondary" if is_act else "primary"):
                    try:
                        update_user(tgt["id"], is_active=not is_act)
                        log_audit(user.get("id"), user.get("username",""),
                                  f"{'deactivate' if is_act else 'activate'}_user", tgt["email"])
                        st.success(f"{'Deactivated' if is_act else 'Activated'}."); st.rerun()
                    except Exception as exc: st.error(f"Failed: {exc}")

    # ── Licenses
    with t_lic:
        with st.expander("➕ Create License Plan", expanded=False):
            with st.form("cl_form"):
                c1, c2 = st.columns(2)
                cl_name  = c1.text_input("Plan Name", placeholder="Enterprise Plus")
                cl_tier  = c2.selectbox("Tier", ["free","professional","enterprise"])
                cl_mu    = c1.number_input("Max Users", min_value=1, value=5, step=1)
                cl_mp    = c2.number_input("Max Picks", min_value=1, value=5, step=1)
                cl_modes = st.multiselect("Allowed Modes", ["free","api"], default=["free"])
                cl_sects = st.multiselect("Allowed Sectors", _ALL_SECTORS, default=_ALL_SECTORS,
                                          format_func=lambda k: SECTOR_LABELS.get(k,k.title()))
                fc1,fc2,fc3 = st.columns(3)
                cl_em = fc1.checkbox("Email Reports")
                cl_ex = fc2.checkbox("Data Export")
                cl_ad = fc3.checkbox("Admin Access")
                cl_exp = st.date_input("Expiry (leave blank = never)", value=None,
                                       min_value=datetime(2024,1,1).date())
                cl_sub = st.form_submit_button("Create Plan", type="primary")
            if cl_sub:
                if not cl_name.strip(): st.error("Name required.")
                else:
                    try:
                        create_license(name=cl_name.strip(), tier=cl_tier, max_users=int(cl_mu),
                                       allowed_modes=",".join(cl_modes), allowed_sectors=",".join(cl_sects),
                                       max_picks=int(cl_mp), can_email=1 if cl_em else 0,
                                       can_export=1 if cl_ex else 0, can_admin=1 if cl_ad else 0,
                                       expires_at=str(cl_exp) if cl_exp else None)
                        log_audit(user.get("id"), user.get("username",""), "create_license", f"Created {cl_name}")
                        st.success(f"'{cl_name}' created."); st.rerun()
                    except Exception as exc: st.error(f"Failed: {exc}")

        try:
            all_l = get_all_licenses()
        except Exception as exc:
            st.error(f"Failed: {exc}"); all_l = []

        for i in range(0, len(all_l), 3):
            cols = st.columns(3)
            for col, lic in zip(cols, all_l[i:i+3]):
                with col:
                    tier   = lic.get("tier","free")
                    try:   cur_u = get_user_count_for_license(lic["id"])
                    except Exception: cur_u = 0
                    modes_s = lic.get("allowed_modes","") or ""
                    sects_s = lic.get("allowed_sectors","") or ""
                    n_sects = len([s for s in sects_s.split(",") if s])
                    exp     = lic.get("expires_at") or "Never"
                    status  = ("🟢 Active" if lic.get("is_active") else "🔴 Inactive")
                    def feat(on, txt): return "<span class='lic-feat " + ("lic-on" if on else "lic-off") + f"'>{txt}</span>"
                    border_color = TIER_BADGE_COLOR.get(tier, '#6B7280')

                    st.markdown(
                        f"<div class='lic-card' style='border-top:3px solid {border_color}'>"
                        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                        f"<span class='lic-name'>{lic.get('name','')}</span>"
                        f"{_tier_badge(tier)}</div>"
                        f"<div style='font-size:0.72rem;margin-top:4px'>{status}</div>"
                        f"<div class='lic-meta'>"
                        f"Users: <b>{cur_u}/{lic.get('max_users','?')}</b>&nbsp;·&nbsp;"
                        f"Max picks: <b>{lic.get('max_picks','?')}</b><br>"
                        f"Modes: <b>{modes_s or '—'}</b><br>"
                        f"Sectors: <b>{n_sects} allowed</b><br>"
                        f"Expires: <b>{exp}</b></div>"
                        f"<div style='margin-top:8px'>"
                        f"{feat(lic.get('can_email'),'✉ Email')}"
                        f"{feat(lic.get('can_export'),'⬇ Export')}"
                        f"{feat(lic.get('can_admin'),'⚙ Admin')}"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("Edit", key=f"elib_{lic['id']}"):
                        st.session_state[f"elib_{lic['id']}"] = True
                    if st.session_state.get(f"elib_{lic['id']}"):
                        with st.form(f"elib_f_{lic['id']}"):
                            el_name = st.text_input("Name", value=lic.get("name",""))
                            el_mu   = st.number_input("Max Users", min_value=1, value=int(lic.get("max_users",5)), step=1)
                            el_mp   = st.number_input("Max Picks", min_value=1, value=int(lic.get("max_picks",5)), step=1)
                            el_mods = st.multiselect("Modes", ["free","api"],
                                                     default=[m for m in (lic.get("allowed_modes") or "").split(",") if m])
                            el_act  = st.checkbox("Active", value=bool(lic.get("is_active",True)))
                            el_sub  = st.form_submit_button("Save", type="primary")
                        if el_sub:
                            try:
                                update_license(lic["id"], name=el_name.strip(), max_users=int(el_mu),
                                               max_picks=int(el_mp), allowed_modes=",".join(el_mods),
                                               is_active=1 if el_act else 0)
                                log_audit(user.get("id"), user.get("username",""), "update_license", f"Updated {lic['name']}")
                                st.success("Saved.")
                                st.session_state[f"elib_{lic['id']}"] = False
                                st.rerun()
                            except Exception as exc: st.error(f"Failed: {exc}")

    # ── Audit
    with t_aud:
        try:
            au  = get_all_users()
            fo  = {"All Users": None}
            fo.update({f"{u.get('full_name','')} ({u.get('username','')})": u["id"] for u in au})
        except Exception:
            fo = {"All Users": None}

        cf, cr = st.columns([3,1])
        with cf: fl = st.selectbox("Filter by user", list(fo.keys()))
        with cr:
            st.write("")
            if st.button("🔄 Refresh", use_container_width=True): st.rerun()

        try: entries = get_audit_log(limit=200, user_id=fo.get(fl))
        except Exception as exc: st.error(f"Failed: {exc}"); entries = []

        if not entries:
            st.info("No audit entries.")
        else:
            st.dataframe(pd.DataFrame([{
                "Time":    str(e.get("created_at",""))[:19],
                "User":    e.get("username",""),
                "Action":  e.get("action",""),
                "Details": e.get("details",""),
            } for e in reversed(entries) if e]),
            hide_index=True, use_container_width=True,
            column_config={
                "Time":   st.column_config.TextColumn(width="small"),
                "User":   st.column_config.TextColumn(width="small"),
                "Action": st.column_config.TextColumn(width="small"),
            })


# ── Profile page ───────────────────────────────────────────────────────────────
def show_profile_page(user: dict):
    st.markdown(
        "<div class='pg-title'>My Profile</div>"
        "<div class='pg-sub' style='margin-bottom:1.5rem'>Account details and security</div>",
        unsafe_allow_html=True,
    )
    col_info, col_pwd = st.columns([1.3,1])

    with col_info:
        lic = None
        if user.get("license_id"):
            try: lic = get_license_by_id(user["license_id"])
            except Exception: pass

        role = user.get("role","viewer")
        tier = lic.get("tier","free") if lic else "free"

        rows = [
            ("Full Name",    user.get("full_name","—")),
            ("Email",        user.get("email","—")),
            ("Username",     f"@{user.get('username','—')}"),
            ("Member Since", str(user.get("created_at","—"))[:10]),
            ("Last Login",   str(user.get("last_login","—"))[:16] if user.get("last_login") else "—"),
        ]
        rows_html = "".join(
            f"<div class='info-row'><span class='info-key'>{k}</span><span class='info-val'>{v}</span></div>"
            for k,v in rows
        )
        lic_name = lic.get("name","None") if lic else "None"
        st.markdown(
            f"<div style='background:#FFF;border:1px solid #E2E8F0;border-radius:12px;padding:20px'>"
            f"{rows_html}"
            f"<div class='info-row'><span class='info-key'>Role</span><span>{_role_badge(role)}</span></div>"
            f"<div class='info-row' style='border:none'><span class='info-key'>License</span>"
            f"<span>{lic_name} &nbsp;{_tier_badge(tier)}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Access")
        perms = {
            "Free Research":   has_permission(user,"research"),
            "Deep Research":   can_use_mode(user,"api"),
            "All Sectors":     has_permission(user,"all_sectors"),
            "Penny Stocks":    can_use_sector(user,"penny"),
            "Email Reports":   has_permission(user,"email"),
            "Data Export":     has_permission(user,"export"),
            "Admin Panel":     has_permission(user,"admin_panel"),
        }
        p1, p2 = st.columns(2)
        for i,(perm,ok) in enumerate(perms.items()):
            icon  = "✅" if ok else "🔒"
            color = "#15803D" if ok else "#94A3B8"
            (p1 if i%2==0 else p2).markdown(
                f"<div class='perm-row {'perm-on' if ok else 'perm-off'}'>{icon} {perm}</div>",
                unsafe_allow_html=True,
            )

    with col_pwd:
        st.markdown("#### Change Password")
        with st.form("cpwd"):
            old = st.text_input("Current Password",     type="password")
            new = st.text_input("New Password",          type="password")
            cnf = st.text_input("Confirm New Password",  type="password")
            st.caption("Min 8 chars · upper · lower · digit · special")
            sub = st.form_submit_button("Update Password", type="primary", use_container_width=True)
        if sub:
            err = (not old and "Enter current password.") or (not new and "Enter new password.") \
                  or validate_password(new) or (new!=cnf and "Passwords don't match.")
            if err: st.error(err)
            else:
                try:
                    chk, cerr = login(user.get("email",""), old)
                    if cerr or not chk: st.error("Current password incorrect.")
                    elif change_password(user["id"], new):
                        log_audit(user.get("id"), user.get("username",""), "change_password", "Changed")
                        st.success("Password updated.")
                    else: st.error("Failed to update.")
                except Exception as exc: st.error(f"Error: {exc}")


# ── Router ─────────────────────────────────────────────────────────────────────
def show_app():
    user = st.session_state["user"]
    show_sidebar(user)
    page = st.session_state.get("page","research")
    if   page == "research": show_research_page(user)
    elif page == "admin":    show_admin_page(user)
    elif page == "profile":  show_profile_page(user)
    else:
        st.session_state["page"] = "research"
        st.rerun()


if st.session_state.get("user"):
    show_app()
else:
    show_auth_page()
