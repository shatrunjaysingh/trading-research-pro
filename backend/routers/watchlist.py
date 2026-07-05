import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

import database as db
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    ticker: str
    notes: str = ""


def _enrich(item: dict) -> dict:
    """Add live price/change to a watchlist row."""
    ticker = item["ticker"]
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        price    = float(fi.last_price)  if fi.last_price    else None
        prev     = float(fi.previous_close) if fi.previous_close else None
        day_chg  = round((price - prev) / prev * 100, 2) if price and prev else None
        mktcap   = float(fi.market_cap) if fi.market_cap else None
        return {**item, "price": price, "day_change_pct": day_chg, "market_cap": mktcap,
                "added_at": item["added_at"].isoformat() if hasattr(item.get("added_at"), "isoformat") else str(item.get("added_at"))}
    except Exception:
        return {**item, "price": None, "day_change_pct": None, "market_cap": None,
                "added_at": str(item.get("added_at", ""))}


@router.get("")
async def get_watchlist(current_user: dict = Depends(get_current_user)):
    items = db.get_watchlist(current_user["id"])
    return [_enrich(it) for it in items]


@router.post("")
async def add_to_watchlist(body: WatchlistAdd, current_user: dict = Depends(get_current_user)):
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    # Verify ticker exists
    try:
        import yfinance as yf
        price = yf.Ticker(ticker).fast_info.last_price
        if not price:
            raise HTTPException(status_code=404, detail=f"No price data for {ticker}. Check the ticker symbol.")
    except HTTPException:
        raise
    except Exception:
        pass
    item = db.add_watchlist_item(current_user["id"], ticker, body.notes)
    return _enrich(item)


@router.delete("/{ticker}")
async def remove_from_watchlist(ticker: str, current_user: dict = Depends(get_current_user)):
    removed = db.remove_watchlist_item(current_user["id"], ticker.upper())
    if not removed:
        raise HTTPException(status_code=404, detail="Item not in watchlist")
    return {"status": "removed", "ticker": ticker.upper()}


@router.get("/check/{ticker}")
async def check_watchlist(ticker: str, current_user: dict = Depends(get_current_user)):
    in_list = db.is_in_watchlist(current_user["id"], ticker.upper())
    return {"ticker": ticker.upper(), "in_watchlist": in_list}
