"""
Live price endpoints backed by Polygon.io.

GET  /prices/quote/{ticker}         — latest quote (cache → REST fallback)
POST /prices/subscribe              — add tickers to the live WS subscription
GET  /prices/stream?tickers=A,B,C  — SSE stream of live price updates
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.auth_middleware import get_current_user
from backend.services.polygon_client import get_polygon_client, price_cache

router = APIRouter(prefix="/prices", tags=["prices"])
logger = logging.getLogger(__name__)

CACHE_STALE_SECS = 300   # quote older than 5 min is considered stale


def _require_research(current_user: dict = Depends(get_current_user)) -> dict:
    import auth as auth_module
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    return current_user


@router.get("/quote/{ticker}")
def get_quote(ticker: str, _: dict = Depends(_require_research)) -> dict:
    """Latest price for one ticker. Checks live cache first, then Polygon REST."""
    q = price_cache.get(ticker)
    if q and (time.time() - q.updated_at) < CACHE_STALE_SECS:
        return {
            "ticker":     q.ticker,
            "price":      q.price,
            "change_pct": q.change_pct,
            "volume":     q.volume,
            "vwap":       q.vwap,
            "open":       q.open,
            "high":       q.high,
            "low":        q.low,
            "source":     "live_cache",
        }
    client = get_polygon_client()
    if client:
        snap = client.get_snapshot(ticker)
        if snap:
            return snap
    return {"ticker": ticker.upper(), "price": None, "source": "unavailable"}


@router.post("/subscribe")
def subscribe_tickers(tickers: list[str], _: dict = Depends(_require_research)) -> dict:
    """Add tickers to the WebSocket live subscription."""
    client = get_polygon_client()
    if not client:
        return {"status": "polygon_not_configured"}
    client.subscribe(tickers)
    return {"status": "ok", "subscribed": tickers}


@router.get("/stream")
async def stream_prices(
    tickers: str,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream of live price updates for the requested tickers."""
    import auth as auth_module
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")

    ticker_set = {t.strip().upper() for t in tickers.split(",") if t.strip()}
    client = get_polygon_client()
    if client:
        client.subscribe(list(ticker_set))

    async def event_gen():
        last_sent: dict[str, float] = {}
        try:
            while True:
                for ticker in ticker_set:
                    q = price_cache.get(ticker)
                    if q and q.updated_at != last_sent.get(ticker):
                        payload = json.dumps({
                            "ticker":     q.ticker,
                            "price":      q.price,
                            "change_pct": q.change_pct,
                            "volume":     q.volume,
                            "vwap":       q.vwap,
                            "open":       q.open,
                            "high":       q.high,
                            "low":        q.low,
                        })
                        yield f"data: {payload}\n\n"
                        last_sent[ticker] = q.updated_at
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
