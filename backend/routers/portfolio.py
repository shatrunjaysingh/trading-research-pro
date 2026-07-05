import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
import math
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.auth_middleware import get_current_user
import database as db

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


# ── Saved Portfolio Endpoints ─────────────────────────────────────────────────

@router.get("/saved")
async def get_saved_portfolio(current_user: dict = Depends(get_current_user)):
    """Return the user's saved portfolio holdings."""
    holdings = db.get_user_portfolio(current_user["id"])
    return {"holdings": holdings}


class SavePortfolioRequest(BaseModel):
    holdings: list[Holding]


@router.post("/save")
async def save_portfolio(body: SavePortfolioRequest, current_user: dict = Depends(get_current_user)):
    """Save (replace) the user's portfolio holdings."""
    if len(body.holdings) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 holdings")
    valid = [h for h in body.holdings if h.ticker.strip() and h.shares > 0 and h.avg_cost > 0]
    if not valid:
        raise HTTPException(status_code=400, detail="No valid holdings to save")

    db.save_user_portfolio(
        current_user["id"],
        [{"ticker": h.ticker, "shares": h.shares, "avg_cost": h.avg_cost} for h in valid],
    )
    return {"saved": len(valid)}


@router.delete("/saved/{ticker}")
async def remove_holding(ticker: str, current_user: dict = Depends(get_current_user)):
    removed = db.remove_portfolio_holding(current_user["id"], ticker.upper())
    if not removed:
        raise HTTPException(status_code=404, detail="Holding not found")
    return {"removed": ticker.upper()}


@router.get("/review")
async def get_portfolio_review(current_user: dict = Depends(get_current_user)):
    """
    Score every saved holding and return actionable recommendations.
    Takes 20–60s for large portfolios — runs in a thread executor.
    """
    from backend.services.portfolio_advisor import analyze_saved_portfolio
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, analyze_saved_portfolio, current_user["id"])
    if result.get("error") and not result.get("holdings"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/backtest")
async def portfolio_backtest(current_user: dict = Depends(get_current_user)):
    """
    For each saved holding, compute historical performance over 1W/1M/3M/6M/1Y
    vs SPY over the same periods.
    """
    holdings = db.get_user_portfolio(current_user["id"])
    if not holdings:
        raise HTTPException(status_code=404, detail="No saved portfolio")

    def _compute(holding: dict) -> dict | None:
        try:
            import yfinance as yf
            tk = yf.Ticker(holding['ticker'])
            hist = tk.history(period="2y", interval="1d", auto_adjust=True)
            if len(hist) < 5:
                return None

            close = hist['Close']
            price = float(close.iloc[-1])

            def pct(n_days: int):
                if len(close) < n_days + 1:
                    return None
                return round((close.iloc[-1] / close.iloc[-(n_days+1)] - 1) * 100, 2)

            # Find approximate purchase date (nearest close to avg_cost)
            avg_cost = holding['avg_cost']
            diffs = (close - avg_cost).abs()
            nearest_idx = diffs.idxmin()
            purchase_date = str(nearest_idx)[:10] if nearest_idx is not None else None

            # Return since avg_cost
            since_purchase_pct = round((price - avg_cost) / avg_cost * 100, 2)

            return {
                "ticker":       holding['ticker'],
                "avg_cost":     avg_cost,
                "shares":       holding['shares'],
                "current_price": price,
                "ret_1w":       pct(5),
                "ret_1m":       pct(21),
                "ret_3m":       pct(63),
                "ret_6m":       pct(126),
                "ret_1y":       pct(252),
                "since_purchase_pct": since_purchase_pct,
                "approx_purchase_date": purchase_date,
            }
        except Exception:
            return None

    def _spy_returns() -> dict:
        try:
            import yfinance as yf
            hist = yf.Ticker('SPY').history(period="2y", interval="1d", auto_adjust=True)
            close = hist['Close']
            def pct(n):
                if len(close) < n + 1: return None
                return round((close.iloc[-1] / close.iloc[-(n+1)] - 1) * 100, 2)
            return {"ret_1w": pct(5), "ret_1m": pct(21), "ret_3m": pct(63), "ret_6m": pct(126), "ret_1y": pct(252)}
        except Exception:
            return {}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_compute, h) for h in holdings]
        spy_fut = ex.submit(_spy_returns)
        results = [f.result() for f in as_completed(futs) if f.result() is not None]
        spy = spy_fut.result()

    return {"holdings": results, "spy": spy}


@router.get("/benchmark")
async def portfolio_benchmark(current_user: dict = Depends(get_current_user)):
    """Compare saved portfolio return to SPY, QQQ, DIA, and sector ETFs."""
    holdings = db.get_user_portfolio(current_user["id"])
    if not holdings:
        raise HTTPException(status_code=404, detail="No saved portfolio")

    BENCHMARKS = {
        'SPY': 'S&P 500',
        'QQQ': 'Nasdaq 100',
        'DIA': 'Dow Jones',
        'IWM': 'Russell 2000',
        'VTI': 'Total Market',
    }

    def _bench(symbol: str) -> dict | None:
        try:
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
            close = hist['Close']
            def pct(n):
                if len(close) < n + 1: return None
                return round((close.iloc[-1] / close.iloc[-(n+1)] - 1) * 100, 2)
            return {
                "symbol": symbol,
                "name":   BENCHMARKS.get(symbol, symbol),
                "ret_1w": pct(5), "ret_1m": pct(21), "ret_3m": pct(63),
                "ret_6m": pct(126), "ret_1y": pct(252),
            }
        except Exception:
            return None

    def _holding_perf(h: dict) -> dict | None:
        try:
            import yfinance as yf
            fi = yf.Ticker(h['ticker']).fast_info
            price = float(fi.last_price) if fi.last_price else None
            if not price:
                return None
            pnl_pct = round((price - h['avg_cost']) / h['avg_cost'] * 100, 2)
            return {"ticker": h['ticker'], "shares": h['shares'],
                    "avg_cost": h['avg_cost'], "current_price": price, "pnl_pct": pnl_pct,
                    "value": round(price * h['shares'], 2)}
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=10) as ex:
        bench_futs   = {ex.submit(_bench, s): s for s in BENCHMARKS}
        holding_futs = [ex.submit(_holding_perf, h) for h in holdings]
        benchmarks   = [f.result() for f in as_completed(bench_futs) if f.result()]
        h_results    = [f.result() for f in as_completed(holding_futs) if f.result()]

    total_value = sum(h['value'] for h in h_results)
    total_cost  = sum(h['avg_cost'] * h['shares'] for h in h_results)
    portfolio_return = round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0.0

    benchmarks.sort(key=lambda x: x.get('ret_1y', -999) or -999, reverse=True)

    return {
        "portfolio_return": portfolio_return,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "benchmarks": benchmarks,
        "holdings": h_results,
    }


@router.get("/news")
async def portfolio_news(current_user: dict = Depends(get_current_user)):
    """News + AI sentiment for each saved portfolio holding."""
    holdings = db.get_user_portfolio(current_user["id"])
    if not holdings:
        raise HTTPException(status_code=404, detail="No saved portfolio")

    def _fetch_news(ticker: str) -> dict:
        try:
            import yfinance as yf
            from datetime import datetime, timezone
            news = yf.Ticker(ticker).news or []
            articles = []
            for n in news[:5]:
                pub_ts = n.get('providerPublishTime') or n.get('published')
                pub_date = None
                if pub_ts:
                    try:
                        pub_date = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        pub_date = str(pub_ts)
                articles.append({
                    "title":     n.get('title', ''),
                    "publisher": n.get('publisher', ''),
                    "link":      n.get('link', ''),
                    "published": pub_date,
                })
            return {"ticker": ticker, "articles": articles}
        except Exception:
            return {"ticker": ticker, "articles": []}

    def _score_sentiment(ticker_news: dict) -> dict:
        """Use Claude Haiku to score overall sentiment from headlines."""
        articles = ticker_news.get('articles', [])
        if not articles:
            ticker_news['sentiment'] = 'neutral'
            ticker_news['sentiment_score'] = 50
            ticker_news['sentiment_reason'] = 'No recent news'
            return ticker_news
        try:
            import anthropic
            from backend.config import settings
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            headlines = "\n".join(f"- {a['title']}" for a in articles)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                messages=[{"role": "user", "content":
                    f"These are recent news headlines for stock {ticker_news['ticker']}:\n{headlines}\n\n"
                    "Reply with JSON only (no markdown): {\"sentiment\": \"bullish|bearish|neutral\", \"score\": 0-100, \"reason\": \"one sentence\"}"
                }]
            )
            import json, re
            text = msg.content[0].text.strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                data = json.loads(m.group())
                ticker_news['sentiment']        = data.get('sentiment', 'neutral')
                ticker_news['sentiment_score']  = int(data.get('score', 50))
                ticker_news['sentiment_reason'] = data.get('reason', '')
            else:
                ticker_news['sentiment'] = 'neutral'; ticker_news['sentiment_score'] = 50
                ticker_news['sentiment_reason'] = 'Could not parse sentiment'
        except Exception:
            ticker_news['sentiment'] = 'neutral'; ticker_news['sentiment_score'] = 50
            ticker_news['sentiment_reason'] = 'Sentiment analysis unavailable'
        return ticker_news

    from concurrent.futures import ThreadPoolExecutor, as_completed
    tickers = [h['ticker'] for h in holdings]

    with ThreadPoolExecutor(max_workers=6) as ex:
        news_futs = {ex.submit(_fetch_news, t): t for t in tickers}
        news_data = [f.result() for f in as_completed(news_futs)]

    # Score sentiment in parallel
    with ThreadPoolExecutor(max_workers=4) as ex:
        sent_futs = [ex.submit(_score_sentiment, nd) for nd in news_data]
        scored = [f.result() for f in as_completed(sent_futs)]

    scored.sort(key=lambda x: x.get('sentiment_score', 50), reverse=True)
    return scored
