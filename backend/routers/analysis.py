import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import auth as auth_module
from database import log_audit
from backend.schemas.analysis import StockAnalysisRequest
from backend.services.stock_analyzer import stream_stock_analysis, fetch_price_history, fetch_analyst_snapshot
from backend.services.cache_service import cache_invalidate, cache_stats
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

VALID_INDICATORS = {"rsi", "macd", "sma20", "sma50", "sma200", "bollinger", "volume"}
VALID_PERIODS    = {"1d", "1w", "1m", "3m", "6m", "1y"}
VALID_MODES      = {"free", "api"}


@router.post("/stock")
async def analyze_stock(
    body: StockAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")

    if body.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")

    if body.mode == "api" and not auth_module.can_use_mode(current_user, "api"):
        raise HTTPException(status_code=403, detail="API mode not available on your license.")

    if body.time_period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"time_period must be one of {VALID_PERIODS}")

    indicators = [i for i in body.indicators if i in VALID_INDICATORS]

    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required.")

    try:
        log_audit(
            current_user.get("id"), current_user.get("username", ""),
            "analyze_stock",
            f"ticker={ticker} mode={body.mode} period={body.time_period} indicators={indicators}",
        )
    except Exception:
        pass

    return StreamingResponse(
        stream_stock_analysis(
            ticker=ticker,
            mode=body.mode,
            time_period=body.time_period,
            indicators=indicators,
            include_news=body.include_news,
            include_fundamentals=body.include_fundamentals,
            include_peers=body.include_peers,
            rsi_period=body.rsi_period,
            bb_period=body.bb_period,
            bb_std=body.bb_std,
            macd_fast=body.macd_fast,
            macd_slow=body.macd_slow,
            macd_signal_period=body.macd_signal_period,
            force_refresh=body.force_refresh,
            user_id=current_user.get("id"),
            username=current_user.get("username", ""),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def stock_history(
    ticker: str,
    period: str = "3m",
    current_user: dict = Depends(get_current_user),
):
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {VALID_PERIODS}")
    t = ticker.strip().upper()
    if not t:
        raise HTTPException(status_code=400, detail="ticker is required.")
    result = fetch_price_history(t, period)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/cache/stats")
async def get_cache_stats(current_user: dict = Depends(get_current_user)):
    """Return cache statistics. Admin only."""
    if not current_user.get("can_admin"):
        raise HTTPException(status_code=403, detail="Admin permission required.")
    return cache_stats()


@router.delete("/cache")
async def clear_cache(
    ticker: str | None = None,
    mode: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Purge cache entries by ticker and/or mode. Admin only."""
    if not current_user.get("can_admin"):
        raise HTTPException(status_code=403, detail="Admin permission required.")
    deleted = cache_invalidate(ticker=ticker, mode=mode)
    return {"deleted": deleted, "ticker": ticker, "mode": mode}


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str

class StockChatRequest(BaseModel):
    ticker: str
    message: str
    history: list[ChatMessage] = []
    context: dict = {}

@router.post("/chat")
async def stock_chat(
    body: StockChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream a Claude response for a question about a specific stock."""
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")

    ticker  = body.ticker.strip().upper()
    message = body.message.strip()
    if not ticker or not message:
        raise HTTPException(status_code=400, detail="ticker and message are required.")

    ctx = body.context
    system = f"""You are a financial research assistant helping analyse the stock {ticker}.

Here is the latest data for {ticker}:
{json.dumps(ctx, indent=2)}

Guidelines:
- Answer questions about this stock concisely and accurately using the data above.
- When the data doesn't cover something, say so rather than guessing.
- Never tell the user to buy or sell. Always note this is for research only, not investment advice.
- Format numbers clearly (e.g. $152.30, +3.5%, 45M shares).
- Keep responses focused and under 300 words unless a detailed breakdown is explicitly asked for."""

    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": message})

    async def generate():
        try:
            import anthropic
            client = anthropic.Anthropic()
            with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/snapshot")
async def stock_snapshot(
    ticker: str,
    current_user: dict = Depends(get_current_user),
):
    """Non-streaming endpoint: fundamentals + analyst consensus for report generation."""
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    t = ticker.strip().upper()
    if not t:
        raise HTTPException(status_code=400, detail="ticker is required.")
    result = fetch_analyst_snapshot(t)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result
