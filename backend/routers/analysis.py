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

    if body.mode == "api" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="AI Deep Dive is restricted to admin users.")

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

    # News headlines (injected at call time)
    news = ctx.get("_news_headlines", [])
    if news:
        lines += ["", "RECENT NEWS HEADLINES"]
        for item in news:
            lines.append(f"  • [{item.get('publisher', '')}] {item.get('title', '')}")

    return "\n".join(lines)


def _fetch_news_headlines(ticker: str, limit: int = 8) -> list[dict]:
    """Fetch recent news headlines from yfinance for a ticker."""
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).news or []
        out = []
        for item in raw[:limit]:
            title = item.get("title") or ""
            pub   = item.get("publisher") or ""
            if title:
                out.append({"title": title, "publisher": pub})
        return out
    except Exception:
        return []


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

    ctx = dict(body.context)
    ctx["_news_headlines"] = _fetch_news_headlines(ticker)
    brief  = _fmt_context(ticker, ctx)
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


@router.post("/verdict")
async def get_verdict(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    Feed all analysis metrics to Claude and return a structured, carefully-reasoned verdict.
    Expects the full analysis result dict from the frontend.
    """
    import anthropic
    from backend.config import settings

    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Final Verdict is restricted to admin users.")

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="AI verdict requires ANTHROPIC_API_KEY to be configured")

    ticker = (body.get("ticker") or "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")

    st   = body.get("st_analysis") or {}
    lt   = body.get("lt_analysis") or {}
    tech = body.get("technical") or {}
    fund = body.get("fundamentals") or {}
    rs   = (body.get("rs_rating") or {}).get("rs_score", 50)
    weekly = body.get("weekly") or {}
    analyst = body.get("analyst") or {}
    patterns = body.get("patterns") or []

    price = tech.get("current_price", 0)

    # Build a compact but comprehensive data brief for Claude
    brief = f"""
STOCK: {ticker}   CURRENT PRICE: ${price:.2f}

=== MOMENTUM SCORES (your own scoring system) ===
Short-term score (1-4 weeks):  {st.get('score', 'N/A')}/100 — {st.get('signal', 'N/A').upper()}
Long-term score  (3-12 months): {lt.get('score', 'N/A') if lt else 'N/A (fundamentals not loaded)'}/100 — {lt.get('signal', 'N/A').upper() if lt else 'N/A'}
RS Rating (vs S&P 500):        {rs}/100  (80+ = outperforming 80% of stocks)

=== TECHNICAL INDICATORS ===
RSI (14):        {tech.get('rsi', 'N/A')}   (30=oversold, 70=overbought; ideal buy zone 50-65)
MACD:            {tech.get('macd', 'N/A'):.4f} vs signal {tech.get('macd_signal', 'N/A'):.4f} — histogram {tech.get('macd_hist', 'N/A'):.4f}
50-day SMA:      ${tech.get('sma50', 'N/A')}   (price {'ABOVE' if price and tech.get('sma50') and price > tech['sma50'] else 'BELOW'})
200-day SMA:     ${tech.get('sma200', 'N/A')}  (price {'ABOVE' if price and tech.get('sma200') and price > tech['sma200'] else 'BELOW'})
52W High/Low:    ${tech.get('high_52w', 'N/A')} / ${tech.get('low_52w', 'N/A')}
Volume ratio:    {tech.get('vol_ratio', 'N/A')}x average  ({tech.get('vol_signal', 'neutral')} trend)
Weekly trend:    {weekly.get('trend_w', 'N/A')}   MACD weekly: {'bullish' if weekly.get('macd_above_signal_w') else 'bearish'}
Bollinger Bands: upper ${tech.get('bb_upper', 'N/A')}, lower ${tech.get('bb_lower', 'N/A')}
Day change:      {tech.get('day_change_pct', 'N/A')}%

=== FUNDAMENTALS ===
P/E (TTM):       {fund.get('pe_ratio', 'N/A')}    Forward P/E: {fund.get('forward_pe', 'N/A')}
EPS growth (YoY):{f"{fund['eps_growth']*100:.1f}%" if fund.get('eps_growth') is not None else 'N/A'}
Revenue growth:  {f"{fund['revenue_growth']*100:.1f}%" if fund.get('revenue_growth') is not None else 'N/A'}
Net margin:      {f"{fund['profit_margin']*100:.1f}%" if fund.get('profit_margin') is not None else 'N/A'}
ROE:             {f"{fund['return_on_equity']*100:.1f}%" if fund.get('return_on_equity') is not None else 'N/A'}
Debt/Equity:     {fund.get('debt_to_equity', 'N/A')}
Short interest:  {f"{fund['short_pct_float']*100:.1f}%" if fund.get('short_pct_float') is not None else 'N/A'}

=== ANALYST CONSENSUS ===
{analyst.get('recommendation', 'N/A')}  —  Buy: {analyst.get('strong_buy', 0)+analyst.get('buy', 0)}  Hold: {analyst.get('hold', 0)}  Sell: {analyst.get('sell', 0)+analyst.get('strong_sell', 0)}
Mean target: ${analyst.get('target_mean', 'N/A')}   High: ${analyst.get('target_high', 'N/A')}   Low: ${analyst.get('target_low', 'N/A')}

=== ST SIGNAL REASONS ===
{chr(10).join(f"• {r}" for r in (st.get('reasoning') or [])[:8])}

=== LT SIGNAL REASONS ===
{chr(10).join(f"• {r}" for r in (lt.get('reasoning') or [])[:8]) if lt else "• Run analysis with Fundamentals enabled for LT data"}

=== CHART PATTERNS ===
{chr(10).join(f"• {p.get('name','')}: {p.get('description','')}" for p in patterns[:5]) or "None detected"}
""".strip()

    # ── Ground the verdict in the cross-sectional factor decomposition ────────
    factor = body.get("factor_analysis") or {}
    health = body.get("financial_health") or {}
    if factor.get("families"):
        fams = factor["families"]
        def _fp(k: str) -> str:
            v = (fams.get(k) or {}).get("percentile")
            return f"{v:.0f}th pct" if v is not None else "n/a"
        basis = "vs {} large-caps".format(factor.get("universe_n")) if factor.get("basis") == "cross-sectional" else "vs baseline norms"
        brief += f"""

=== CROSS-SECTIONAL FACTOR RANKING ({basis}) ===
Composite: {factor.get('composite')}/100   Conviction (factor breadth): {factor.get('conviction')}%
Momentum {_fp('momentum')} | Value {_fp('value')} | Quality {_fp('quality')} | Growth {_fp('growth')} | Revisions {_fp('revisions')} | Low-Vol {_fp('low_vol')}"""
    if health:
        hp = []
        if health.get("piotroski") is not None:       hp.append(f"Piotroski {health['piotroski']}/9")
        if health.get("altman_z") is not None:         hp.append(f"Altman-Z {health['altman_z']}")
        if health.get("roic") is not None:             hp.append(f"ROIC {health['roic']*100:.0f}%")
        if health.get("fcf_yield") is not None:        hp.append(f"FCF yield {health['fcf_yield']*100:.1f}%")
        if health.get("fcf_conversion") is not None:   hp.append(f"FCF conversion {health['fcf_conversion']*100:.0f}%")
        if health.get("revision_score") is not None:   hp.append(f"Net analyst revisions {health['revision_score']:+.0f}")
        if hp:
            brief += "\n\n=== FINANCIAL HEALTH ===\n" + "   ".join(hp)

    cat = body.get("catalysts") or {}
    if cat.get("earnings_days_out") is not None:
        d = cat["earnings_days_out"]
        if 0 <= d <= 21:
            brief += (f"\n\n=== EVENT RISK ===\nNext earnings in {d} days ({cat.get('next_earnings_date')}). "
                      "Treat the short-term call cautiously around this binary event.")

    prompt = f"""{brief}

---
You are a senior portfolio manager writing a decision memo. Reason like an institutional investor: form a differentiated thesis, name the variant perception, and define exactly what would prove you wrong. Anchor every claim to the factor percentiles and metrics above — do not hand-wave.

Think step by step:
1. Which factors is this stock strong/weak on (use the percentile ranking)? Is it a leader (broad strength), a value trap (cheap but weak momentum/quality), or a crowded momentum name (strong momentum, poor value/quality)?
2. What does the trend structure (SMA50/200, weekly) and financial health (Piotroski, Altman-Z, ROIC, FCF) say about durability and downside?
3. What is the VARIANT PERCEPTION — what might the market be mispricing here, and why (bull or bear)?
4. What concrete, observable events would INVALIDATE this thesis (specific factor/price/fundamental triggers)?
5. Weigh bull vs bear — how decisively, and how does that map to conviction?

Return ONLY valid JSON in this exact schema (no markdown, no extra text):
{{
  "overall": "STRONG BUY|BUY|WATCH|HOLD|SELL",
  "conviction": "HIGH|MEDIUM|LOW",
  "thesis_type": "<one of: Leader | Value Trap | Crowded Momentum | Turnaround | Falling Knife | Quality Compounder | Deep Value>",
  "variant_perception": "<1-2 sentences: what the market may be mispricing and why — the edge>",
  "st_verdict": "BUY|WATCH|HOLD|SELL",
  "st_target": <number — realistic 4-week price target>,
  "st_stop": <number — stop-loss level>,
  "st_reasoning": "<2 sentences explaining the short-term call, citing factors>",
  "lt_verdict": "BUY|WATCH|HOLD|SELL",
  "lt_target": <number — realistic 12-month price target>,
  "lt_support": <number — key long-term support>,
  "lt_reasoning": "<2 sentences explaining the long-term call, citing factors>",
  "key_catalysts": ["<catalyst 1 with rough timing if known>", "<catalyst 2>", "<catalyst 3>"],
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "invalidation": ["<concrete trigger that would prove the thesis wrong>", "<trigger 2>"],
  "sell_rules": ["<explicit rule for exiting, e.g. 'exit if composite < 45 for 3 days' or 'trim below 200-day MA'>", "<rule 2>"],
  "summary": "<3-4 sentence PM-style assessment weighing all evidence>"
}}"""

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,   # was 1024 — the expanded verdict schema was truncating mid-JSON
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (msg.content[0].text or "").strip()

        # Strip markdown fences, then isolate the outermost JSON object so any
        # stray prose before/after the braces can't break the parse.
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw.strip("`")
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start:end + 1]

        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError:
            # Most common failure is truncation when the model hits the token cap.
            if getattr(msg, "stop_reason", None) == "max_tokens":
                raise HTTPException(
                    status_code=502,
                    detail="AI verdict was cut off (response too long). Please retry.",
                )
            raise
        verdict["ticker"] = ticker
        verdict["price"]  = price
        return verdict
    except HTTPException:
        raise
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/evidence")
async def rating_evidence(current_user: dict = Depends(get_current_user)):
    """Forward-return + win-rate by rating bucket — proof the rating has an edge."""
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    from database import get_rating_bucket_stats
    return get_rating_bucket_stats()


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
