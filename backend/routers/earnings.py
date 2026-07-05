import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
import logging
from fastapi import APIRouter, Depends
from backend.auth_middleware import get_current_user
import database as db

router = APIRouter(prefix="/earnings", tags=["earnings"])
logger = logging.getLogger(__name__)


def _fetch_earnings(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        from datetime import datetime, timezone
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        info = tk.info

        earnings_date = None
        eps_estimate  = None
        rev_estimate  = None

        if cal is not None:
            if hasattr(cal, 'columns'):
                # DataFrame form
                if 'Earnings Date' in cal.columns:
                    ed = cal['Earnings Date'].iloc[0] if len(cal) else None
                    earnings_date = str(ed)[:10] if ed else None
                if 'Earnings Average' in cal.columns:
                    eps_estimate = float(cal['Earnings Average'].iloc[0]) if len(cal) else None
                if 'Revenue Average' in cal.columns:
                    rev_estimate = float(cal['Revenue Average'].iloc[0]) if len(cal) else None
            elif isinstance(cal, dict):
                ed = cal.get('Earnings Date')
                if hasattr(ed, '__iter__') and not isinstance(ed, str):
                    ed = list(ed)[0] if ed else None
                earnings_date = str(ed)[:10] if ed else None
                eps_estimate  = cal.get('Earnings Average') or cal.get('EPS Estimate')
                rev_estimate  = cal.get('Revenue Average') or cal.get('Revenue Estimate')

        # Days until earnings
        days_out = None
        if earnings_date:
            from datetime import date
            try:
                ed_date = date.fromisoformat(earnings_date)
                days_out = (ed_date - date.today()).days
            except Exception:
                pass

        return {
            "ticker":        ticker,
            "company":       info.get("shortName") or info.get("longName") or ticker,
            "sector":        info.get("sector") or "Unknown",
            "earnings_date": earnings_date,
            "days_out":      days_out,
            "eps_estimate":  float(eps_estimate) if eps_estimate is not None else None,
            "rev_estimate":  float(rev_estimate) if rev_estimate is not None else None,
            "eps_actual":    info.get("trailingEps"),
            "pe_ratio":      info.get("trailingPE"),
            "forward_pe":    info.get("forwardPE"),
            "eps_surprise_pct": info.get("earningQuarterlyGrowth"),
            "risk_level":    (
                "high"   if days_out is not None and 0 <= days_out <= 7 else
                "medium" if days_out is not None and 0 <= days_out <= 21 else
                "low"
            ),
        }
    except Exception as exc:
        logger.debug("Earnings fetch failed for %s: %s", ticker, exc)
        return None


@router.get("/calendar")
async def earnings_calendar(current_user: dict = Depends(get_current_user)):
    """
    Return upcoming earnings for the user's watchlist + saved portfolio.
    Results sorted by days until earnings.
    """
    user_id = current_user["id"]

    wl_tickers = [item["ticker"] for item in db.get_watchlist(user_id)]
    pf_tickers = [item["ticker"] for item in db.get_user_portfolio(user_id)]
    tickers    = list(set(wl_tickers + pf_tickers))

    if not tickers:
        return []

    loop = asyncio.get_event_loop()
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_fetch_earnings, t): t for t in tickers}
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: (x.get("days_out") is None, x.get("days_out") or 9999))
    return results
