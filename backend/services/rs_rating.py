"""
Relative Strength (RS) Rating — IBD-style metric measuring price performance
vs the S&P 500.

Formula (weighted):
  RS = 0.4 * (3m_return - SPY_3m) + 0.2 * (6m_return - SPY_6m) + 0.4 * (12m_return - SPY_12m)
  → clipped to -50..+50, then mapped to 1–99 score

A score of 80+ means the stock outperformed 80% of the market.
A score of 90+ is what IBD considers "elite relative strength."
"""

import math
from typing import Optional


def _safe(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _period_return(hist, n_bars: int) -> Optional[float]:
    """Return % change of last n_bars closes."""
    closes = hist["Close"].dropna().tolist()
    if len(closes) < n_bars:
        return None
    start = closes[-n_bars]
    end   = closes[-1]
    if start <= 0:
        return None
    return (end - start) / start * 100


def compute_rs_rating(ticker: str, spy_returns: Optional[dict] = None) -> dict:
    """
    Returns:
      rs_score        : 1–99 RS rating
      vs_spy_3m       : stock 3m return – SPY 3m return (pct pts)
      vs_spy_6m       : stock 6m return – SPY 6m return (pct pts)
      vs_spy_12m      : stock 12m return – SPY 12m return (pct pts)
      stock_3m_return : raw stock return over 3 months
      stock_12m_return: raw stock return over 12 months
    """
    result = {
        "rs_score": 50, "vs_spy_3m": None, "vs_spy_6m": None,
        "vs_spy_12m": None, "stock_3m_return": None, "stock_12m_return": None,
    }

    try:
        import yfinance as yf

        # Fetch SPY benchmarks if not provided
        if spy_returns is None:
            spy_hist = yf.Ticker("SPY").history(period="1y", interval="1d")
            spy_returns = {
                "3m":  _period_return(spy_hist, 63),
                "6m":  _period_return(spy_hist, 126),
                "12m": _period_return(spy_hist, 252),
            }

        tk   = yf.Ticker(ticker.upper())
        hist = tk.history(period="1y", interval="1d")
        if len(hist) < 30:
            return result

        r3m  = _period_return(hist, 63)
        r6m  = _period_return(hist, 126)
        r12m = _period_return(hist, 252)

        result["stock_3m_return"]  = round(r3m,  2) if r3m  is not None else None
        result["stock_12m_return"] = round(r12m, 2) if r12m is not None else None

        spy3  = spy_returns.get("3m",  0) or 0
        spy6  = spy_returns.get("6m",  0) or 0
        spy12 = spy_returns.get("12m", 0) or 0

        vs3  = (r3m  - spy3)  if r3m  is not None else 0
        vs6  = (r6m  - spy6)  if r6m  is not None else 0
        vs12 = (r12m - spy12) if r12m is not None else 0

        result["vs_spy_3m"]  = round(vs3,  2)
        result["vs_spy_6m"]  = round(vs6,  2)
        result["vs_spy_12m"] = round(vs12, 2)

        # Weighted composite relative performance
        composite = 0.4 * vs3 + 0.2 * vs6 + 0.4 * vs12

        # Map -50..+50 ppt range → 1..99 score
        clipped = max(-50, min(50, composite))
        rs_score = round(1 + (clipped + 50) / 100 * 98)
        result["rs_score"] = int(rs_score)

    except Exception:
        pass

    return result


def fetch_spy_returns() -> dict:
    """Fetch SPY benchmark returns once and reuse across many tickers."""
    try:
        import yfinance as yf
        hist = yf.Ticker("SPY").history(period="1y", interval="1d")
        return {
            "3m":  _period_return(hist, 63),
            "6m":  _period_return(hist, 126),
            "12m": _period_return(hist, 252),
        }
    except Exception:
        return {"3m": 0, "6m": 0, "12m": 0}
