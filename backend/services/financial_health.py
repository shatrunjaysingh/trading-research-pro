"""
Financial-health metrics — the fundamental-quality signals institutions lean on
that go beyond a single ratio. Computed from yfinance financial statements:

  • Piotroski F-score (0–9) — a 9-point checklist of profitability, leverage, and
    efficiency trends. High scores identify improving, financially sound firms;
    it's one of the most durable quality signals in the literature.
  • Altman Z-score — distress/bankruptcy risk. >3 safe, <1.8 distress zone.
  • ROIC — return on invested capital (NOPAT / invested capital). The truest test
    of whether a business creates value above its cost of capital.
  • FCF yield — free cash flow / market cap (a cleaner "cheapness" gauge than P/E).
  • FCF conversion — free cash flow / net income (earnings quality: are profits
    real cash or accounting?).

Every metric degrades gracefully to None when a statement line item is missing,
so a thin-data ticker never breaks the caller.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Assumed cost of capital when comparing ROIC (a reasonable large-cap WACC proxy;
# ROIC materially above this = value creation).
ASSUMED_WACC = 0.09


def _row(df, *names, idx: int = 0) -> float | None:
    """Fetch a statement value by trying candidate row labels, at column `idx`
    (0 = most recent year). Returns float or None."""
    if df is None or getattr(df, "empty", True):
        return None
    try:
        import math
        cols = list(df.columns)
        if idx >= len(cols):
            return None
        for name in names:
            if name in df.index:
                val = df.loc[name].iloc[idx]
                if val is None:
                    return None
                f = float(val)
                return None if math.isnan(f) else f
    except Exception:
        return None
    return None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _piotroski(inc, bal, cf) -> int | None:
    """9-point Piotroski F-score. Needs current + prior year on each statement."""
    ni      = _row(inc, "Net Income", "Net Income Common Stockholders")
    ni_p    = _row(inc, "Net Income", "Net Income Common Stockholders", idx=1)
    ta      = _row(bal, "Total Assets")
    ta_p    = _row(bal, "Total Assets", idx=1)
    ocf     = _row(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
    if ni is None or ta is None or ta_p is None or ocf is None:
        return None

    roa   = _safe_div(ni, ta)
    roa_p = _safe_div(ni_p, ta_p)

    ltd    = _row(bal, "Long Term Debt")
    ltd_p  = _row(bal, "Long Term Debt", idx=1)
    ca     = _row(bal, "Current Assets", "Total Current Assets")
    cl     = _row(bal, "Current Liabilities", "Total Current Liabilities")
    ca_p   = _row(bal, "Current Assets", "Total Current Assets", idx=1)
    cl_p   = _row(bal, "Current Liabilities", "Total Current Liabilities", idx=1)
    shares    = _row(bal, "Ordinary Shares Number", "Share Issued")
    shares_p  = _row(bal, "Ordinary Shares Number", "Share Issued", idx=1)
    gp     = _row(inc, "Gross Profit")
    gp_p   = _row(inc, "Gross Profit", idx=1)
    rev    = _row(inc, "Total Revenue", "Operating Revenue")
    rev_p  = _row(inc, "Total Revenue", "Operating Revenue", idx=1)

    score = 0
    # Profitability
    if ni > 0: score += 1
    if ocf > 0: score += 1
    if roa is not None and roa_p is not None and roa > roa_p: score += 1
    if ocf is not None and ni is not None and ocf > ni: score += 1   # accrual quality
    # Leverage / liquidity
    if ltd is not None and ltd_p is not None and ltd <= ltd_p: score += 1
    cr   = _safe_div(ca, cl)
    cr_p = _safe_div(ca_p, cl_p)
    if cr is not None and cr_p is not None and cr > cr_p: score += 1
    if shares is not None and shares_p is not None and shares <= shares_p * 1.01: score += 1  # no dilution
    # Efficiency
    gm   = _safe_div(gp, rev)
    gm_p = _safe_div(gp_p, rev_p)
    if gm is not None and gm_p is not None and gm > gm_p: score += 1
    at   = _safe_div(rev, ta)
    at_p = _safe_div(rev_p, ta_p)
    if at is not None and at_p is not None and at > at_p: score += 1
    return score


def _altman_z(inc, bal, market_cap: float | None) -> float | None:
    """Altman Z-score (classic 5-factor). >3 safe, 1.8–3 grey, <1.8 distress."""
    ta   = _row(bal, "Total Assets")
    if not ta or ta <= 0:
        return None
    ca   = _row(bal, "Current Assets", "Total Current Assets")
    cl   = _row(bal, "Current Liabilities", "Total Current Liabilities")
    re   = _row(bal, "Retained Earnings")
    ebit = _row(inc, "EBIT", "Operating Income")
    tl   = _row(bal, "Total Liabilities Net Minority Interest", "Total Liab")
    rev  = _row(inc, "Total Revenue", "Operating Revenue")
    wc   = (ca - cl) if (ca is not None and cl is not None) else None

    if None in (re, ebit, tl, rev) or wc is None or not tl or tl <= 0 or not market_cap:
        return None
    z = (1.2 * (wc / ta) + 1.4 * (re / ta) + 3.3 * (ebit / ta)
         + 0.6 * (market_cap / tl) + 1.0 * (rev / ta))
    return round(z, 2)


def _roic(inc, bal) -> float | None:
    """ROIC = NOPAT / invested capital. NOPAT = EBIT × (1 − effective tax rate)."""
    ebit = _row(inc, "EBIT", "Operating Income")
    if ebit is None:
        return None
    pretax = _row(inc, "Pretax Income", "Income Before Tax")
    tax    = _row(inc, "Tax Provision", "Income Tax Expense")
    tax_rate = 0.21
    if pretax and tax is not None and pretax != 0:
        tr = tax / pretax
        if 0 <= tr <= 0.6:
            tax_rate = tr
    nopat = ebit * (1 - tax_rate)

    debt   = _row(bal, "Total Debt")
    equity = _row(bal, "Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
    cash   = _row(bal, "Cash And Cash Equivalents", "Cash And Cash Equivalents And Short Term Investments")
    if equity is None:
        return None
    invested = (debt or 0) + equity - (cash or 0)
    if invested <= 0:
        return None
    return round(nopat / invested, 4)


def get_financial_health(ticker: str) -> dict:
    """
    Compute all financial-health metrics for a ticker. Returns a dict with any
    of: piotroski (0-9), altman_z, roic, roic_excess (ROIC − WACC), fcf_yield,
    fcf_conversion. Missing values are omitted / None.
    """
    out: dict = {}
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker.strip().upper())
        inc = getattr(tk, "income_stmt", None)
        bal = getattr(tk, "balance_sheet", None)
        cf  = getattr(tk, "cashflow", None)
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            info = {}

        market_cap = info.get("marketCap")
        fcf = info.get("freeCashflow")
        if fcf is None:
            fcf = _row(cf, "Free Cash Flow")
        ni = _row(inc, "Net Income", "Net Income Common Stockholders")

        out["piotroski"] = _piotroski(inc, bal, cf)
        out["altman_z"]  = _altman_z(inc, bal, market_cap)
        roic = _roic(inc, bal)
        out["roic"] = roic
        out["roic_excess"] = round(roic - ASSUMED_WACC, 4) if roic is not None else None
        out["fcf_yield"] = round(fcf / market_cap, 4) if (fcf and market_cap) else None
        out["fcf_conversion"] = round(fcf / ni, 3) if (fcf and ni and ni > 0) else None
    except Exception as exc:
        logger.debug("financial_health failed for %s: %s", ticker, exc)
    return out


def revision_score_from_ratings(ratings: list[dict] | None) -> float | None:
    """
    Estimate-revision momentum from recent analyst upgrades/downgrades.
    Net = (# upgrades − # downgrades) over the fetched window. Positive = analysts
    getting more bullish (one of the most robust public-data alpha signals).
    """
    if not ratings:
        return None
    up = down = 0
    for r in ratings:
        action = str(r.get("action", "")).lower()
        if action in ("up", "upgrade"):
            up += 1
        elif action in ("down", "downgrade"):
            down += 1
    if up == 0 and down == 0:
        return None
    return float(up - down)
