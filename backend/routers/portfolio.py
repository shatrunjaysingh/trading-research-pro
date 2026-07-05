import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import math
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


class Holding(BaseModel):
    ticker: str
    shares: float
    avg_cost: float


class PortfolioRequest(BaseModel):
    holdings: list[Holding]


@router.post("/analyze")
async def analyze_portfolio(body: PortfolioRequest, current_user: dict = Depends(get_current_user)):
    if not body.holdings:
        raise HTTPException(status_code=400, detail="No holdings provided")
    if len(body.holdings) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 holdings per request")

    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(status_code=500, detail="yfinance not installed")

    holdings_out = []

    for h in body.holdings:
        ticker = h.ticker.strip().upper()
        if not ticker:
            continue
        try:
            tk   = yf.Ticker(ticker)
            info = tk.info
            fi   = tk.fast_info

            price    = _safe(fi.last_price)
            prev     = _safe(fi.previous_close)
            day_chg  = round((price - prev) / prev * 100, 2) if price and prev else None

            current_value = price * h.shares if price else None
            cost_basis    = h.avg_cost * h.shares
            pnl           = (current_value - cost_basis) if current_value is not None else None
            pnl_pct       = (pnl / cost_basis * 100) if (pnl is not None and cost_basis) else None

            holdings_out.append({
                "ticker":        ticker,
                "company":       info.get("shortName") or info.get("longName") or ticker,
                "sector":        info.get("sector") or "Unknown",
                "industry":      info.get("industry") or "",
                "shares":        h.shares,
                "avg_cost":      h.avg_cost,
                "current_price": price,
                "day_change_pct": day_chg,
                "current_value": round(current_value, 2) if current_value else None,
                "cost_basis":    round(cost_basis, 2),
                "pnl":           round(pnl, 2) if pnl is not None else None,
                "pnl_pct":       round(pnl_pct, 2) if pnl_pct is not None else None,
                "beta":          _safe(info.get("beta")) or 1.0,
                "pe_ratio":      _safe(info.get("trailingPE")),
                "market_cap":    _safe(info.get("marketCap")),
                "dividend_yield": _safe(info.get("dividendYield")),
                "weight":        0.0,
                "error":         None,
            })
        except Exception as exc:
            holdings_out.append({
                "ticker": ticker,
                "shares": h.shares,
                "avg_cost": h.avg_cost,
                "cost_basis": h.avg_cost * h.shares,
                "error": str(exc),
                "sector": "Unknown",
                "beta": 1.0,
                "weight": 0.0,
                "current_value": None,
                "pnl": None,
                "pnl_pct": None,
            })

    valid = [h for h in holdings_out if h.get("error") is None and h.get("current_value") is not None]
    total_value = sum(h["current_value"] for h in valid)

    for h in holdings_out:
        if h.get("current_value") and total_value:
            h["weight"] = round(h["current_value"] / total_value * 100, 2)

    # Portfolio-level metrics
    portfolio_beta = round(
        sum(h.get("beta", 1.0) * (h.get("weight", 0) / 100) for h in valid), 3
    ) if valid else 1.0

    # Sector breakdown
    sectors: dict[str, float] = {}
    for h in valid:
        s = h.get("sector") or "Unknown"
        sectors[s] = round(sectors.get(s, 0) + h.get("weight", 0), 2)

    # Top 5 by weight
    top5 = sorted(valid, key=lambda x: x.get("weight", 0), reverse=True)[:5]

    # Diversification score (HHI-based, 0–100 lower is more concentrated)
    hhi = sum((h.get("weight", 0) / 100) ** 2 for h in valid)
    diversification = round((1 - hhi) * 100, 1) if valid else 0.0

    total_cost  = sum(h["cost_basis"] for h in holdings_out if "cost_basis" in h)
    total_pnl   = sum(h["pnl"] for h in valid if h.get("pnl") is not None)
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if (total_cost and total_pnl is not None) else None

    return {
        "holdings": holdings_out,
        "summary": {
            "total_value":      round(total_value, 2),
            "total_cost":       round(total_cost, 2),
            "total_pnl":        round(total_pnl, 2),
            "total_pnl_pct":    total_pnl_pct,
            "portfolio_beta":   portfolio_beta,
            "sector_breakdown": dict(sorted(sectors.items(), key=lambda x: x[1], reverse=True)),
            "num_holdings":     len(valid),
            "diversification":  diversification,
            "top5_by_weight":   [{"ticker": h["ticker"], "weight": h["weight"]} for h in top5],
        },
    }
