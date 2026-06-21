"""Generate RESEARCH_AND_ANALYSIS_REFERENCE.pdf from the markdown file."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import re

# ── Colour palette ─────────────────────────────────────────────────────────────
NAVY      = colors.HexColor("#1F4E79")
BLUE_LIGHT= colors.HexColor("#DDEBF7")
GREEN     = colors.HexColor("#C6EFCE")
YELLOW    = colors.HexColor("#FFEB9C")
GREY_LIGHT= colors.HexColor("#F2F2F2")
GREY_MID  = colors.HexColor("#D0D0D0")
CODE_BG   = colors.HexColor("#F8F8F8")
CODE_BORDER=colors.HexColor("#CCCCCC")
WHITE     = colors.white
BLACK     = colors.HexColor("#222222")
ORANGE    = colors.HexColor("#ED7D31")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm

# ── Styles ──────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, **kw)

H1 = S("H1", fontSize=20, leading=26, textColor=NAVY,
        spaceAfter=6, spaceBefore=14, fontName="Helvetica-Bold", alignment=TA_LEFT)
H2 = S("H2", fontSize=14, leading=18, textColor=NAVY,
        spaceAfter=4, spaceBefore=12, fontName="Helvetica-Bold",
        borderPad=3, borderColor=NAVY, borderWidth=0)
H3 = S("H3", fontSize=11, leading=15, textColor=NAVY,
        spaceAfter=3, spaceBefore=8, fontName="Helvetica-Bold")
BODY = S("BODY", fontSize=9, leading=13, textColor=BLACK,
         spaceAfter=4, fontName="Helvetica")
BODY_SM = S("BODY_SM", fontSize=8, leading=11, textColor=BLACK,
            spaceAfter=2, fontName="Helvetica")
CODE = S("CODE", fontSize=7.5, leading=10, textColor=BLACK,
         fontName="Courier", spaceAfter=1, spaceBefore=1,
         backColor=CODE_BG, leftIndent=6, rightIndent=6)
BULLET = S("BULLET", fontSize=9, leading=13, textColor=BLACK,
           fontName="Helvetica", leftIndent=12, spaceAfter=2,
           bulletIndent=4)
TH = S("TH", fontSize=8, leading=10, textColor=WHITE,
       fontName="Helvetica-Bold", alignment=TA_CENTER)
TD = S("TD", fontSize=8, leading=10, textColor=BLACK,
       fontName="Helvetica", alignment=TA_LEFT)
TD_CENTER = S("TD_CENTER", fontSize=8, leading=10, textColor=BLACK,
              fontName="Helvetica", alignment=TA_CENTER)
CAPTION = S("CAPTION", fontSize=7.5, leading=10, textColor=colors.grey,
            fontName="Helvetica-Oblique", spaceAfter=4, spaceBefore=2)
SUBTITLE = S("SUBTITLE", fontSize=10, leading=14, textColor=colors.grey,
             fontName="Helvetica-Oblique", spaceAfter=8, spaceBefore=2)


def table(headers, rows, col_widths=None, center_cols=None):
    """Build a styled ReportLab Table from headers + row lists."""
    center_cols = center_cols or []
    th_cells = [Paragraph(h, TH) for h in headers]
    data = [th_cells]
    for ri, row in enumerate(rows):
        cells = []
        for ci, cell in enumerate(row):
            style = TD_CENTER if ci in center_cols else TD
            cells.append(Paragraph(str(cell), style))
        data.append(cells)

    avail = PAGE_W - 2 * MARGIN
    if col_widths is None:
        n = len(headers)
        col_widths = [avail / n] * n
    else:
        total = sum(col_widths)
        col_widths = [w / total * avail for w in col_widths]

    row_bg = []
    for i in range(1, len(data)):
        bg = GREY_LIGHT if i % 2 == 0 else WHITE
        row_bg.append(("BACKGROUND", (0, i), (-1, i), bg))

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GREY_LIGHT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, GREY_MID),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0,0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",(0, 0), (-1, -1), 5),
    ] + row_bg))
    return t


def code_block(lines):
    """Render a list of strings as a shaded code block."""
    flowables = []
    for line in lines:
        # Escape XML special chars
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        flowables.append(Paragraph(safe or " ", CODE))
    # Wrap in a table for the border + background
    inner = [[f] for f in flowables]
    t = Table([[Paragraph(
        "<br/>".join(
            (l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") or " ")
            for l in lines
        ), CODE
    )]], colWidths=[PAGE_W - 2 * MARGIN - 12])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), CODE_BG),
        ("BOX",          (0, 0), (-1, -1), 0.5, CODE_BORDER),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=GREY_MID, spaceAfter=6, spaceBefore=6)


def section_header(text, level=2):
    """Coloured section header with underline rule."""
    style = H2 if level == 2 else H3
    return KeepTogether([Paragraph(text, style), hr()])


# ── Document content ────────────────────────────────────────────────────────────

def build_story():
    s = []

    # Cover / title block
    s.append(Spacer(1, 18 * mm))
    s.append(Paragraph("TradingResearch Pro", H1))
    s.append(Paragraph("Research &amp; Analysis Reference", H1))
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph("Last updated: 2026-06-20  |  Version 2.0", SUBTITLE))
    s.append(Paragraph(
        "Covers: research.py · backend/services/stock_analyzer.py · "
        "sentiment.py · backend/services/regime_detector.py",
        CAPTION,
    ))
    s.append(hr())
    s.append(Spacer(1, 4 * mm))

    # ── 1. Overview ────────────────────────────────────────────────────────────
    s.append(section_header("1.  Overview — Two Analysis Paths"))
    s.append(Paragraph(
        "The app has two distinct analysis paths that share data sources but serve different purposes:",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Feature", "File", "Mode", "Purpose"],
        [
            ["Research", "research.py", "Free (yfinance) or API (Claude Opus)",
             "Rank a universe of assets by opportunity score; generate daily picks report"],
            ["Stock Analysis", "backend/services/stock_analyzer.py", "Always uses Claude Sonnet",
             "Deep single-stock analysis with full technical + fundamental AI narrative"],
        ],
        col_widths=[2.5, 3.5, 3, 5],
    ))
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph(
        "Since the recent update, Research computes and displays the same named technical indicators "
        "(RSI, MACD, Bollinger, SMA, VWAP, ATR) that Stock Analysis shows. "
        "Technical indicator values are also injected into the Claude deep-research prompt "
        "via <i>_build_technical_context()</i> so the AI has quantitative data to reason from.",
        BODY,
    ))

    # ── 2. Market Regime ───────────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("2.  Market Regime Detection"))
    s.append(Paragraph(
        "<b>File:</b> backend/services/regime_detector.py  |  "
        "<b>Sources:</b> VIX (^VIX), SPY — fetched daily, cached 1 hour  |  "
        "<b>Used by:</b> Both Research scoring and Stock Analysis AI prompt",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        "The regime classifier sets a <b>score multiplier</b> applied to every asset's composite score "
        "after all sub-scores are combined.",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Regime", "Condition", "Multiplier", "Effect"],
        [
            ["BULL",    "VIX ≤ 18 AND SPY > SMA50 by >1% AND > SMA200 by >5%", "1.10×", "Scores boosted 10%"],
            ["NEUTRAL", "Default (mixed signals)",                               "1.00×", "No adjustment"],
            ["BEAR",    "VIX ≥ 25 OR (SPY < SMA50 by 3% AND < SMA200 by 5%)",  "0.75×", "Scores dampened 25%"],
            ["CRISIS",  "VIX ≥ 35 OR (VIX ≥ 28 AND deep drawdown)",            "0.60×", "Scores dampened 40%"],
        ],
        col_widths=[1.8, 5.5, 2, 3.5],
        center_cols=[2],
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        'The regime is also passed to the Stock Analysis AI prompt to contextualise position sizing '
        'advice (<i>favour tight stops in a BEAR/CRISIS environment</i>).',
        BODY,
    ))

    # ── 3. Technical Indicators ────────────────────────────────────────────────
    s.append(section_header("3.  Technical Indicators"))

    s.append(Paragraph("3a.  Research (Free Mode) — research.py", H3))
    s.append(Paragraph(
        "Computed inside <i>_score_asset()</i> from 3-month daily OHLCV history (yfinance). "
        "All values appear in the email HTML under each pick and are injected into Claude prompts.",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Indicator", "Parameters", "Display / Notes"],
        [
            ["RSI",             "Period: 14",                       "< 30 = oversold (green), > 70 = overbought (red)"],
            ["MACD",            "Fast 12, Slow 26, Signal 9",       "Line, signal line, histogram shown"],
            ["SMA 20",          "20-day simple moving average",     "Short-term trend"],
            ["SMA 50",          "50-day simple moving average",     "🟢 price above, 🔴 price below"],
            ["SMA 200",         "200-day simple moving average",    "null if < 200 days of history available"],
            ["Bollinger Bands", "Period 20, Std dev 2×",            "Upper / lower / mid band"],
            ["VWAP",            "Full 3-month window",              "Volume-Weighted Average Price; 🟢 if price above"],
            ["ATR",             "Period: 14",                       "Average True Range shown as % of price (volatility)"],
        ],
        col_widths=[2.5, 3.5, 7],
    ))

    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("3b.  Stock Analysis — backend/services/stock_analyzer.py", H3))
    s.append(Paragraph(
        "Computed from user-selected time period (1d / 1w / 1m / 3m / 6m / 1y). "
        "RSI period, Bollinger period/std, and MACD parameters are all user-configurable from the UI.",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Indicator", "Default Params", "User-configurable"],
        [
            ["RSI",             "Period: 14",                 "Yes — RSI period"],
            ["MACD",            "Fast 12, Slow 26, Signal 9", "Yes — all three periods"],
            ["SMA 20",          "20-day",                     "No (fixed)"],
            ["SMA 50",          "50-day",                     "No (fixed)"],
            ["SMA 200",         "200-day",                    "No (fixed)"],
            ["Bollinger Bands", "Period 20, Std 2.0",         "Yes — period and std multiplier"],
            ["VWAP",            "Full selected period",        "No (always computed)"],
            ["ATR",             "Period: 14",                  "No (fixed)"],
        ],
        col_widths=[3, 4, 6],
    ))

    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("Technical Signal Score (Stock Analysis only)", H3))
    s.append(Paragraph(
        "Derived from indicator values to produce a signal (BUY / WATCH / HOLD / SELL) "
        "and a 0–100 score. Confidence = % of active indicator votes aligned with the final signal.",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Indicator Condition", "Bullish?", "Score Impact"],
        [
            ["RSI < 30 (oversold)",          "Yes", "+15"],
            ["RSI < 45",                     "Yes", "+7"],
            ["RSI > 70 (overbought)",        "No",  "−15"],
            ["RSI > 55",                     "No",  "−5"],
            ["MACD > Signal line",           "Yes", "+10"],
            ["MACD < Signal line",           "No",  "−10"],
            ["Price > SMA 50",               "Yes", "+8"],
            ["Price < SMA 50",               "No",  "−8"],
            ["Price > SMA 200",              "Yes", "+7"],
            ["Price < SMA 200",              "No",  "−7"],
            ["Day change > 0",               "Proportional", "±up to 10"],
            ["Volume ratio > 1.5×",          "Yes", "+5"],
            ["Price < Bollinger Lower",      "Oversold bounce", "Vote only"],
            ["Price > Bollinger Upper",      "Overbought reversal", "Vote only"],
            ["Price > VWAP",                 "Yes", "+6"],
            ["Price < VWAP",                 "No",  "−4"],
        ],
        col_widths=[5.5, 2.5, 2.5],
        center_cols=[1, 2],
    ))
    s.append(Paragraph(
        "Final signal: BUY (score ≥ 65) / WATCH (52–64) / HOLD (38–51) / SELL (< 38)",
        CAPTION,
    ))

    # ── 4. Fundamental Factors ─────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("4.  Fundamental Factors"))

    s.append(Paragraph("4a.  Research Scoring Fundamentals", H3))
    s.append(Paragraph("Fetched from yfinance Ticker.info for each asset.", BODY))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Factor", "yfinance Field", "How Used in Scoring"],
        [
            ["Forward EPS growth",  "forwardEps vs trailingEps",    "EPS growth sub-score"],
            ["Earnings Growth",     "earningsGrowth",               "Fallback if forward EPS unavailable"],
            ["Revenue Growth",      "revenueGrowth",                "Part of earnings quality score (20% weight)"],
            ["EPS Surprise",        "earnings_history (surprise%)", "Beat (+) / miss (−) vs analyst estimate"],
            ["Short % of Float",    "shortPercentOfFloat",          "Squeeze potential or bearish signal"],
            ["Short Ratio",         "shortRatio",                   "Days to cover — used in short score"],
            ["Sector",              "sector",                       "Maps to sector ETF for relative strength"],
        ],
        col_widths=[3.5, 4, 6],
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        "<b>Earnings quality sub-score (0–100):</b> "
        "50% × EPS beat/miss  +  30% × EPS growth  +  20% × revenue growth",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph("<b>Short interest score logic:</b>", BODY))
    s.append(Paragraph("• Short > 15% AND price rising → squeeze setup (score 70–92)", BULLET))
    s.append(Paragraph("• Short > 30% AND price falling → confirmed short thesis (score 22)", BULLET))
    s.append(Paragraph("• Short > 20%, no direction → headwind (score 40)", BULLET))
    s.append(Paragraph("• Default neutral → score 50", BULLET))

    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("4b.  Stock Analysis Fundamentals", H3))
    s.append(table(
        ["Field", "Description"],
        [
            ["Company name, sector, industry",  "Identity"],
            ["Market cap",                      "Size classification"],
            ["P/E ratio (trailing & forward)",  "Valuation"],
            ["EPS (trailing & forward)",        "Earnings power"],
            ["EPS growth (fwd vs trailing)",    "Growth trajectory"],
            ["EPS surprise (last quarter)",     "Beat / miss vs consensus estimate"],
            ["Revenue & revenue growth (YoY)", "Top-line momentum"],
            ["Profit margin",                   "Profitability"],
            ["Debt-to-equity",                  "Balance sheet risk"],
            ["Current ratio",                   "Liquidity"],
            ["Return on equity (ROE)",          "Capital efficiency"],
            ["Dividend yield",                  "Income"],
            ["Beta",                            "Market correlation / volatility"],
            ["Short % of float + short ratio",  "Short interest"],
        ],
        col_widths=[5, 8.5],
    ))

    # ── 5. Sentiment ───────────────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("5.  Sentiment Factors"))
    s.append(Paragraph(
        "<b>File:</b> sentiment.py  |  <b>Cache:</b> 30 minutes in-process  |  "
        "<b>Weight in composite:</b> 5%  |  <b>Used by:</b> Research scoring + API prompt injection",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Source", "Type", "API Key?", "What It Provides"],
        [
            ["StockTwits",        "Per-ticker",    "No",       "Bullish/bearish message counts (last 30 messages)"],
            ["CNN Fear & Greed",  "Macro (stocks)","No",       "Score 0–100; cached per session"],
            ["Alternative.me",   "Macro (crypto)", "No",       "Crypto Fear & Greed score 0–100; crypto assets only"],
            ["Reddit",           "Per-ticker",     "Optional", "Post count + bull/bear keyword ratio across WSB, stocks, investing, StockMarket, pennystocks, cryptocurrency"],
        ],
        col_widths=[3, 2.5, 2, 6],
        center_cols=[2],
    ))
    s.append(Paragraph(
        "Reddit requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env to activate.",
        CAPTION,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph("<b>Sentiment Score Blending:</b>", BODY))
    s.append(table(
        ["Data Available", "Formula"],
        [
            ["StockTwits + Fear&Greed + Reddit", "50% StockTwits  +  35% Fear&Greed  +  15% Reddit"],
            ["StockTwits + Fear&Greed (no Reddit)", "60% StockTwits  +  40% Fear&Greed"],
            ["Fear&Greed only", "100% Fear&Greed"],
        ],
        col_widths=[5, 8.5],
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        "<b>Output labels:</b> Bullish (≥65) / Leaning Bullish (55–64) / Neutral (45–54) / "
        "Leaning Bearish (35–44) / Bearish (&lt;35)",
        BODY,
    ))

    # ── 6. Insider & Institutional ─────────────────────────────────────────────
    s.append(section_header("6.  Insider &amp; Institutional Data"))
    s.append(Paragraph(
        "<b>Source:</b> yfinance Ticker.insider_transactions (SEC Form 4) + Ticker.major_holders  |  "
        "<b>Lookback:</b> Last 90 days  |  <b>Weight in composite:</b> 5%  |  "
        "<b>Stocks only</b> (skipped for crypto)",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Net Shares Bought (last 90 days)", "Insider Score", "Interpretation"],
        [
            ["> 100,000",           "85", "Strong insider buying — very bullish signal"],
            ["20,001 – 100,000",    "70", "Moderate buying"],
            ["1 – 20,000",          "58", "Slight buying"],
            ["0 (neutral)",         "50", "No notable activity"],
            ["−1 to −50,000",       "42", "Slight selling"],
            ["−50,001 to −200,000", "33", "Moderate selling"],
            ["< −200,000",          "22", "Heavy selling — red flag"],
        ],
        col_widths=[5.5, 2.5, 5.5],
        center_cols=[1],
    ))
    s.append(Paragraph(
        'Automatic sales (Rule 10b5-1 plans) are excluded from the sell count.',
        CAPTION,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph("<b>Institutional Ownership Bonus:</b>", BODY))
    s.append(table(
        ["Institutional Ownership", "Score Bonus"],
        [
            ["> 75%",   "+8 points"],
            ["50%–75%", "+4 points"],
            ["< 50%",   "No adjustment"],
        ],
        col_widths=[5, 8.5],
        center_cols=[1],
    ))

    # ── 7. Analyst Consensus ───────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("7.  Analyst Consensus"))
    s.append(Paragraph(
        "<b>Source:</b> yfinance Ticker.info  |  "
        "<b>Fields:</b> targetMeanPrice, recommendationMean (1=Strong Buy → 5=Sell), numberOfAnalystOpinions  |  "
        "<b>Weight in composite:</b> 10%  |  <b>Minimum analysts:</b> 2",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph("<b>Analyst Score Formula:</b>", BODY))
    s.append(Spacer(1, 1 * mm))
    s.append(code_block([
        "price_score   = clamp(50 + analyst_upside_pct × 1.5,  0, 100)",
        "rec_score     = clamp(100 − (recommendationMean − 1) × 22.5, 0, 100)",
        "reliability   = min(num_analysts / 8, 1.0)",
        "analyst_score = (price_score × 0.5 + rec_score × 0.5) × reliability",
        "              + 50 × (1 − reliability)",
    ]))
    s.append(Paragraph(
        "The reliability factor scales from 0→1 as analyst count goes from 0→8+, "
        "so a single analyst opinion does not dominate the score.",
        CAPTION,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["recommendationMean", "Label", "rec_score"],
        [
            ["1.0", "Strong Buy",   "100"],
            ["1.5", "Buy",          "88.75"],
            ["2.0", "Buy",          "77.5"],
            ["2.5", "Hold",         "66.25"],
            ["3.0", "Hold",         "55"],
            ["3.5", "Underperform", "33.75"],
            ["4.0", "Underperform", "22.5"],
            ["5.0", "Sell",         "0"],
        ],
        col_widths=[3.5, 4, 3],
        center_cols=[0, 2],
    ))

    # ── 8. Earnings Calendar ───────────────────────────────────────────────────
    s.append(section_header("8.  Earnings Calendar Awareness"))
    s.append(Paragraph(
        "<b>Source:</b> yfinance Ticker.calendar  |  <b>Lookback:</b> Next 7 days  |  "
        "<b>Applied as:</b> Score penalty after composite × regime multiplier",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        "Stocks with imminent earnings are flagged and penalised because the outcome is binary "
        "and unpredictable — holding into earnings is speculation, not analysis.",
        BODY,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Days to Earnings", "Score Penalty", "Display"],
        [
            ["0–1 day",  "−15 points", "⚠ Earnings tomorrow"],
            ["2–3 days", "−10 points", "⚠ Earnings in X days"],
            ["4–7 days", "−5 points",  "⚠ Earnings this week"],
            ["> 7 days", "0",           "(no flag)"],
        ],
        col_widths=[3.5, 3, 7],
        center_cols=[1],
    ))
    s.append(Paragraph(
        "Formula: score = composite × regime_multiplier − earnings_penalty",
        CAPTION,
    ))

    # ── 9. Composite Scoring ───────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("9.  Composite Scoring — Research Free Mode"))
    s.append(Paragraph(
        "<b>Function:</b> _score_asset() in research.py  |  "
        "<b>Scale:</b> 0–100  |  "
        "<b>Signal:</b> BUY ≥ 65  /  WATCH 45–64  /  HOLD &lt; 45",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph("<b>Sub-score Formulas (each normalised 0–100):</b>", BODY))
    s.append(Spacer(1, 1 * mm))
    s.append(table(
        ["Sub-score", "Formula"],
        [
            ["mom_1d",        "day_change_pct × 5 + 50"],
            ["mom_1w",        "week_change_pct × 3 + 50"],
            ["mom_1m",        "month_change_pct × 2 + 50"],
            ["mom_3m",        "qtr_change_pct × 1.5 + 50"],
            ["vol_scr",       "min(vol_ratio × 40, 100)"],
            ["pos_scr",       "52w_position × 100  (0 = at 52w low, 100 = at 52w high)"],
            ["rs_spy",        "(qtr_change − SPY_3m) × 2 + 50"],
            ["rs_sector",     "(qtr_change − sector_ETF_3m) × 2 + 50"],
            ["earn_qual_scr", "EPS_beat×0.5 + EPS_growth×0.3 + rev_growth×0.2"],
            ["short_scr",     "See short interest logic in Section 4a"],
            ["sent_scr",      "From sentiment.py (0–100)"],
            ["analyst_score", "See Section 7 formula"],
            ["insider_score", "See Section 6 table"],
        ],
        col_widths=[3.5, 10],
    ))
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph("<b>Composite Weights (sum = 100%):</b>", BODY))
    s.append(Spacer(1, 1 * mm))
    s.append(table(
        ["Factor", "Weight"],
        [
            ["3-month momentum",                   "18%"],
            ["1-month momentum",                   "14%"],
            ["1-week momentum",                    " 9%"],
            ["1-day change",                       " 2%"],
            ["Volume surge",                       " 9%"],
            ["Relative strength vs SPY",           " 7%"],
            ["Relative strength vs sector ETF",    " 7%"],
            ["52-week position",                   " 3%"],
            ["Earnings quality (EPS + revenue)",   " 7%"],
            ["Short interest / squeeze potential", " 4%"],
            ["Social sentiment",                   " 5%"],
            ["Analyst consensus + price target",   "10%"],
            ["Insider / institutional signal",     " 5%"],
            ["TOTAL",                              "100%"],
        ],
        col_widths=[9, 2],
        center_cols=[1],
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(Paragraph(
        "<b>Confidence score:</b> percentage of sub-scores above 50 "
        "(how many factors agree the asset is above average):  "
        "confidence = count(sub_score > 50) / total_sub_scores × 100",
        BODY,
    ))

    # ── 10. AI Prompts ─────────────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("10.  AI Prompts"))

    # 10a
    s.append(Paragraph("10a.  Research — Simple Dual-Category Prompt  (SYSTEM_PROMPT)", H3))
    s.append(Paragraph(
        "Used in run_api() for the All Stocks + Penny Stocks scheduled report mode. "
        "Model: claude-opus-4-8 with extended thinking and web_search tool.",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(code_block([
        "You are a quantitative trading analyst. Research a given universe",
        "of stocks and cryptocurrencies using live market data and news, then rank them by",
        "short-term opportunity score for today.",
        "",
        "IMPORTANT QUALITY BAR: Only include picks where you have 90%+ confidence.",
        "Prefer returning fewer than 5 picks over including a low-conviction one.",
        "",
        "For each asset, research ALL of the following:",
        "1. Price momentum, volume vs 30-day average, and today's % change.",
        "2. News sentiment from the last 48 hours.",
        "3. Analyst consensus: current buy/hold/sell ratings and mean price target.",
        "4. Earnings calendar: flag any earnings within the next 7 days (high event risk).",
        "5. Insider activity: any notable Form 4 purchases or sales in the last 30 days.",
        "6. Institutional ownership: is it rising or falling (13F signals)?",
        "7. Technical signals and upcoming catalysts.",
        "",
        "Penalise stocks reporting earnings within 3 days.",
        "Treat recent insider buying as a strong positive; heavy selling as a red flag.",
        "",
        "JSON output per pick: rank, ticker, asset_type, current_price, day_change_pct,",
        "score, confidence_pct, signal, reasoning, key_catalyst, analyst_sentiment,",
        "insider_activity, earnings_warning, suggested_entry, target_price, stop_loss,",
        "time_horizon, risk_note",
        "",
        "Signal: BUY | HOLD | WATCH. Score >= 90 to include. Rank descending.",
    ]))

    # 10b
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("10b.  Research — Penny Stock Prompt  (CHEAP_STOCK_SYSTEM_PROMPT)", H3))
    s.append(Paragraph(
        "Used in run_api() for penny stocks (price < $5).",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(code_block([
        "You are a small-cap stock analyst specialising in low-price, high-potential",
        "equities (under $5). Identify stocks that are cheap but have strong future",
        "growth potential — NOT just momentum plays.",
        "",
        "For each stock consider:",
        "- Business model: real problem, viable path to profitability?",
        "- Catalysts: earnings, product launches, FDA approvals, contracts",
        "- Financial health: debt levels, cash runway, revenue trend",
        "- News sentiment: positive developments in the last 7 days?",
        "- Insider/institutional activity: any notable buying?",
        "- Risk: temporary headwind or structural decline?",
        "",
        "AVOID: pump plays, zero-revenue shells, terminal-decline companies.",
        "",
        "JSON output per pick includes target_price, time_horizon (3-6 months),",
        "why_its_cheap, business_viability, financial_health.",
    ]))

    # 10c
    s.append(PageBreak())
    s.append(Paragraph("10c.  Research — Sector Deep Research Prompt  (DEEP_RESEARCH_PROMPT_TEMPLATE)", H3))
    s.append(Paragraph(
        "Used in run_sector_api() for sector-by-sector analysis. "
        "Sector guidance is injected per sector. Pre-computed technical indicators "
        "are also injected via _build_technical_context().",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(code_block([
        "You are a senior equity research analyst at a top-tier investment fund.",
        "Conduct rigorous, data-driven research on the {sector} assets provided.",
        "",
        "SECTOR FOCUS: {sector_guidance}",
        "",
        "RESEARCH PROCESS — execute ALL steps via web search:",
        "1. Fetch live price, today's % change, volume vs 30-day average, 52-week range.",
        "2. Search news from the last 7 days for each ticker.",
        "3. Check analyst ratings and mean price target changes in the last 30 days.",
        "4. Identify upcoming catalysts in next 60-90 days.",
        "5. Review latest earnings: EPS beat/miss, revenue growth, guidance, margins.",
        "6. Assess balance sheet: cash vs debt, free cash flow.",
        "7. Check insider transactions (SEC Form 4) in the last 30 days.",
        "8. Note institutional ownership trend — rising or falling.",
        "9. Flag stocks with earnings within 7 days — reduce confidence accordingly.",
        "",
        "QUALITY BAR: score >= 90 AND confidence >= 90%. Return UP TO {top_n} picks.",
        "",
        "JSON output per pick: rank, ticker, company_name, current_price, day_change_pct,",
        "week_change_pct, score, confidence_pct, signal, why_picked, technical_analysis,",
        "fundamental_snapshot, key_catalyst, sector_tailwind, analyst_sentiment,",
        "insider_activity, earnings_warning, news_summary, news_sentiment,",
        "suggested_entry, target_price, stop_loss, upside_pct, time_horizon, risk_factors[]",
    ]))

    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("<b>Sector Guidance Injected Per Sector:</b>", BODY))
    s.append(Spacer(1, 2 * mm))
    s.append(table(
        ["Sector", "Key Focus Areas"],
        [
            ["Technology",      "AI/ML adoption, semiconductor demand, cloud ARR growth, software innovation, competitive moats, valuation vs growth"],
            ["Pharma & Biotech","FDA calendar (next 90 days), Phase 2/3 trials, patent cliffs, pipeline value, M&A activity, drug pricing"],
            ["Healthcare",      "Insurance reimbursement, hospital utilization, medical device innovation, Medicare/Medicaid policy, managed care margins"],
            ["Finance",         "Net interest margin, loan growth vs credit losses, capital adequacy, fee income, Fed rate trajectory"],
            ["Energy",          "Crude/nat-gas futures curve, production guidance, refining spreads, capex discipline, OPEC+ decisions, energy transition"],
            ["Consumer",        "Consumer confidence, same-store sales, gross margin recovery, inventory normalization, e-commerce, brand strength"],
            ["Industrials",     "Order backlog, defense budget, infrastructure spending, supply chain, pricing power, international exposure"],
            ["Crypto",          "On-chain metrics, institutional inflows, regulatory developments, network upgrades, DeFi activity"],
        ],
        col_widths=[3, 10.5],
    ))

    # 10d
    s.append(PageBreak())
    s.append(Paragraph("10d.  Research — Penny Stocks Sector Prompt  (PENNY_DEEP_RESEARCH_PROMPT_TEMPLATE)", H3))
    s.append(Spacer(1, 1 * mm))
    s.append(code_block([
        "You are a small-cap and penny stock specialist.",
        "Research the provided stocks (all priced under ${max_price}) for",
        "high-conviction recovery or growth plays.",
        "",
        "KEY QUESTIONS FOR EACH STOCK:",
        "- Why is it cheap? Temporary headwind or structural decline?",
        "- Is the business viable? Real revenue, path to profitability?",
        "- What catalyst could re-rate it?",
        "- Financial runway: cash months, revenue trajectory, debt burden.",
        "- Market interest: insider buying, institutional accumulation, short squeeze?",
        "",
        "AVOID: pump plays, zero-revenue shells, terminal decline, fraudulent operators.",
        "",
        "JSON output per pick includes: why_its_cheap, business_viability,",
        "key_catalyst, financial_health, technical_analysis, target_price,",
        "stop_loss, upside_pct, time_horizon, risk_factors[]",
    ]))

    # 10e
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("10e.  Stock Analysis — AI Narrative Prompt", H3))
    s.append(Paragraph(
        "Used in _ai_analysis() in backend/services/stock_analyzer.py. "
        "Model: claude-sonnet-4-6 (max 600 tokens — concise and actionable).",
        BODY_SM,
    ))
    s.append(Spacer(1, 2 * mm))
    s.append(code_block([
        "You are a professional equity analyst. Analyze {ticker} ({company})",
        "based on the following data and provide a concise, actionable analysis.",
        "",
        "TECHNICAL DATA:",
        "- Current Price / Day Change / RSI (14) / MACD",
        "- 50-day SMA / 200-day SMA / VWAP (above/below — bullish/bearish intraday)",
        "- ATR (14) as $ and % of price  /  Momentum Score: {score}/100",
        "- Signal: {BUY | WATCH | HOLD | SELL}",
        "",
        "FUNDAMENTAL DATA:",
        "- Sector / P/E (trailing & forward) / Beta",
        "- Profit Margin / Revenue Growth (YoY)",
        "- EPS: trailing → forward ({growth}% expected)",
        "- EPS Surprise (last quarter) vs estimate",
        "- Short Interest: % of float + days to cover",
        "",
        "ANALYST DATA:",
        "- Consensus rating ({num_analysts} analysts)",
        "- Price Target (mean): ${target} ({upside}% upside)",
        "- Target Range: ${low} – ${high}",
        "",
        "MARKET REGIME:",
        "- Regime: {BULL|NEUTRAL|BEAR|CRISIS} (VIX={vix})",
        "- SPY vs SMA50 / SMA200",
        "- Score multiplier + regime-appropriate sizing advice",
        "",
        "Provide:",
        "1. Summary (2-3 sentences, includes regime context)",
        "2. Technical Outlook (indicators + VWAP position)",
        "3. Analyst Consensus (targets vs current price)",
        "4. Key Risks (2-3 bullet points)",
        "5. Trade Setup (entry, target, stop = 1.5× ATR, size for regime)",
    ]))

    # ── Appendix ───────────────────────────────────────────────────────────────
    s.append(PageBreak())
    s.append(section_header("Appendix — Data Sources Summary"))
    s.append(table(
        ["Data", "Source", "API Key?", "Cache"],
        [
            ["Price, OHLCV, fundamentals",    "yfinance (Yahoo Finance)",     "No",       "Per request"],
            ["Earnings calendar",             "yfinance Ticker.calendar",     "No",       "Per request"],
            ["Analyst targets & consensus",   "yfinance Ticker.info",         "No",       "Per request"],
            ["Insider transactions (Form 4)", "yfinance insider_transactions","No",       "Per request"],
            ["Institutional holders",         "yfinance major_holders",       "No",       "Per request"],
            ["StockTwits sentiment",          "StockTwits public API",        "No",       "30 min"],
            ["CNN Fear & Greed",              "CNN dataviz API",              "No",       "30 min"],
            ["Crypto Fear & Greed",           "Alternative.me API",           "No",       "30 min"],
            ["Reddit mentions",               "Reddit OAuth API",             "Optional", "Per request"],
            ["Market regime (VIX/SPY)",       "yfinance",                     "No",       "1 hour"],
            ["Deep research + web search",    "Claude Opus 4.8 + web_search", "Required", "Per run"],
            ["Stock Analysis AI narrative",   "Claude Sonnet 4.6",            "Required", "Per request"],
        ],
        col_widths=[4, 4, 2.2, 2],
    ))

    s.append(Spacer(1, 6 * mm))
    s.append(hr())
    s.append(Paragraph(
        "TradingResearch Pro  |  Research &amp; Analysis Reference  |  2026-06-20  |  "
        "Re-generate after significant changes to research.py, stock_analyzer.py, or sentiment.py",
        CAPTION,
    ))

    return s


# ── Page template with header/footer ──────────────────────────────────────────

def on_first_page(canvas, doc):
    pass

def on_later_pages(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(MARGIN, 12 * mm, "TradingResearch Pro — Research & Analysis Reference")
    canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ── Build PDF ──────────────────────────────────────────────────────────────────

OUTPUT = "/Users/shatrunjaysingh/trading-agent/RESEARCH_AND_ANALYSIS_REFERENCE.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=MARGIN,
    rightMargin=MARGIN,
    topMargin=20 * mm,
    bottomMargin=20 * mm,
    title="TradingResearch Pro — Research & Analysis Reference",
    author="TradingResearch Pro",
)

doc.build(build_story(), onFirstPage=on_first_page, onLaterPages=on_later_pages)
print(f"PDF saved → {OUTPUT}")
