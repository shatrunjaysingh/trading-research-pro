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


def _fmt_context(ticker: str, ctx: dict) -> str:
    """Convert raw context dict into a readable analyst brief."""
    def money(v, decimals=2):
        if v is None: return "N/A"
        if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.2f}M"
        return f"${v:,.{decimals}f}"

    price  = ctx.get("price")
    lines  = [f"=== {ticker} — {ctx.get('company', ticker)} ==="]

    # Price & momentum
    if price:
        lines += [
            "",
            "PRICE & MOMENTUM",
            f"  Current Price : {money(price)}",
            f"  Day Change    : {ctx.get('day_change_pct', 0):+.2f}%",
            f"  Week Change   : {ctx.get('week_change_pct', 0):+.2f}%",
            f"  Month Change  : {ctx.get('month_change_pct', 0):+.2f}%",
            f"  52-Week Range : {money(ctx.get('low_52w'))} – {money(ctx.get('high_52w'))}",
            f"  Signal        : {(ctx.get('signal') or 'N/A').upper()}  (score {ctx.get('score', '—')}/100)",
        ]

    # Technicals
    rsi = ctx.get("rsi")
    lines += ["", "TECHNICAL INDICATORS"]
    if rsi is not None:
        interp = "oversold — bullish" if rsi < 30 else "overbought — bearish" if rsi > 70 else "neutral"
        lines.append(f"  RSI           : {rsi:.1f}  ({interp})")
    macd = ctx.get("macd")
    if macd is not None:
        lines.append(f"  MACD          : {macd:.4f}")
    sma50 = ctx.get("sma50")
    if sma50 and price:
        rel = "above ▲ bullish" if price > sma50 else "below ▼ bearish"
        lines.append(f"  50-day SMA    : {money(sma50)}  (price is {rel})")
    sma200 = ctx.get("sma200")
    if sma200 and price:
        rel = "above ▲ bull market" if price > sma200 else "below ▼ bear territory"
        lines.append(f"  200-day SMA   : {money(sma200)}  (price is {rel})")
    vol_sig = ctx.get("vol_signal")
    if vol_sig:
        vt = ctx.get("vol_trend_pct")
        lines.append(f"  Volume (30d)  : {vol_sig}  ({vt:+.1f}% vs prior 30d)" if vt is not None else f"  Volume signal : {vol_sig}")

    # Fundamentals
    mc = ctx.get("market_cap")
    if mc:
        lines += ["", "FUNDAMENTALS"]
        lines.append(f"  Market Cap    : {money(mc)}")
    pe = ctx.get("pe_ratio")
    if pe:  lines.append(f"  P/E (TTM)     : {pe:.1f}x")
    fpe = ctx.get("forward_pe")
    if fpe: lines.append(f"  Forward P/E   : {fpe:.1f}x")
    eps = ctx.get("eps")
    if eps is not None: lines.append(f"  EPS (TTM)     : ${eps:.2f}")
    rev = ctx.get("revenue")
    if rev: lines.append(f"  Revenue (TTM) : {money(rev)}")
    pm = ctx.get("profit_margin")
    if pm is not None: lines.append(f"  Profit Margin : {pm*100:.1f}%")
    de = ctx.get("debt_to_equity")
    if de is not None: lines.append(f"  Debt/Equity   : {de:.2f}")
    roe = ctx.get("return_on_equity")
    if roe is not None: lines.append(f"  ROE           : {roe*100:.1f}%")
    beta = ctx.get("beta")
    if beta is not None: lines.append(f"  Beta          : {beta:.2f}")
    dy = ctx.get("dividend_yield")
    if dy: lines.append(f"  Dividend Yield: {dy*100:.2f}%")

    # Analyst consensus
    lines += ["", "ANALYST CONSENSUS"]
    ar = ctx.get("analyst_rating")
    na = ctx.get("num_analysts")
    if ar:
        lines.append(f"  Rating        : {ar}  ({na or '?'} analysts)")
    at = ctx.get("analyst_target")
    au = ctx.get("analyst_upside")
    if at:
        lines.append(f"  Price Target  : {money(at)}  ({au:+.1f}% upside)" if au is not None else f"  Price Target  : {money(at)}")

    # SEC insider activity
    ins = ctx.get("insider_signal")
    if ins:
        net = ctx.get("insider_net_shares")
        net_str = f"  net {net:+,} shares (90d)" if net else ""
        lines += ["", "SEC INSIDER ACTIVITY (FORM 4, 90 DAYS)"]
        lines.append(f"  Signal        : {ins.replace('_', ' ').upper()}{net_str}")

    # Narrative AI analysis
    ai_text = ctx.get("ai_analysis")
    if ai_text:
        lines += ["", "EXISTING AI NARRATIVE ANALYSIS"]
        lines.append(ai_text[:3000])

    return "\n".join(lines)


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

    brief  = _fmt_context(ticker, body.context)
    system = f"""You are a financial research assistant helping a user analyse the stock {ticker}.

{brief}

Guidelines:
- Answer questions using the data above. Be specific — quote actual numbers from the data.
- If the data doesn't cover something, say so rather than guessing.
- Interpret indicators: e.g. RSI < 30 = oversold, price above 200-day SMA = uptrend.
- Never recommend buying or selling. This is for research purposes only.
- Keep responses concise and clear. Use bullet points for multi-part answers."""

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
