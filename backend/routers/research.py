import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi import Query as QParam
from fastapi.responses import StreamingResponse

import auth as auth_module
from research import SECTOR_LABELS, load_config
from database import log_audit
from backend.schemas.research import ResearchRequest, ResearchConfigOut
from backend.services.research_runner import stream_research
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/research", tags=["research"])

_ALL_SECTORS = ["technology","pharma","healthcare","finance","energy","consumer","industrials","crypto","penny"]


@router.get("/config", response_model=ResearchConfigOut)
def research_config(current_user: dict = Depends(get_current_user)):
    avail_modes   = [m for m in ["free","api"] if auth_module.can_use_mode(current_user, m)]
    avail_sectors = [s for s in _ALL_SECTORS if auth_module.can_use_sector(current_user, s)]
    max_picks     = auth_module.get_max_picks(current_user)
    return {
        "available_modes":   avail_modes or ["free"],
        "available_sectors": avail_sectors,
        "max_picks":         max_picks,
        "default_top_n":     min(5, max_picks),
        "sector_labels":     {k: SECTOR_LABELS.get(k, k.title()) for k in _ALL_SECTORS},
    }


@router.post("/run")
async def run_research_sse(
    body: ResearchRequest,
    current_user: dict = Depends(get_current_user),
):
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    if not auth_module.can_use_mode(current_user, body.mode):
        raise HTTPException(status_code=403, detail=f"Mode '{body.mode}' not allowed on your license.")

    config      = load_config()
    allowed_all = [s for s in _ALL_SECTORS if auth_module.can_use_sector(current_user, s)]
    sectors_run = [s for s in body.selected_sectors if auth_module.can_use_sector(current_user, s)] \
                  if body.selected_sectors else allowed_all
    top_n       = min(body.top_n, auth_module.get_max_picks(current_user))
    email_cfg   = config.get("email") if body.send_email and auth_module.has_permission(current_user, "email") else None

    try:
        log_audit(
            current_user.get("id"), current_user.get("username",""),
            "run_research", f"mode={body.mode} sectors={sectors_run} top_n={top_n}",
        )
    except Exception:
        pass

    return StreamingResponse(
        stream_research(
            config=config, selected_sectors=sectors_run, mode=body.mode,
            max_price=body.max_price, top_n=top_n, email_cfg=email_cfg,
            dividend_only=body.dividend_only,
            min_market_cap=body.min_market_cap,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/regime")
def research_regime(current_user: dict = Depends(get_current_user)):
    """Return current market regime for display in the Research Dashboard. Cached 1h."""
    from backend.services.regime_detector import get_market_regime
    return get_market_regime()


@router.get("/screen")
async def screen_stocks(
    min_st:  int = QParam(0,  ge=0, le=100),
    min_lt:  int = QParam(0,  ge=0, le=100),
    min_rs:  int = QParam(0,  ge=0, le=100),
    min_price: float = QParam(5.0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """
    Screen S&P 100 + watchlist tickers by ST, LT, RS thresholds.
    Re-uses the same scoring logic as the daily digest.
    Returns top 50 results sorted by composite score desc.
    """
    from backend.services.rs_rating import fetch_spy_returns
    from backend.services.daily_digest import _score_ticker_for_digest, SP100
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import database as db

    # Universe: S&P 100 + user's watchlist
    try:
        wl = db.get_watchlist(current_user["id"])
        extra = [w["ticker"] for w in wl if w["ticker"] not in SP100]
    except Exception:
        extra = []
    universe = list(set(SP100 + extra))

    loop = asyncio.get_event_loop()

    def _run_screen():
        spy_returns = fetch_spy_returns()
        results = []
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(_score_ticker_for_digest, t, spy_returns): t for t in universe}
            for f in as_completed(futures):
                r = f.result()
                if r is None:
                    continue
                if r["st_score"] < min_st:
                    continue
                if r.get("lt_score") is not None and r["lt_score"] < min_lt:
                    continue
                if r["rs_score"] < min_rs:
                    continue
                if r["price"] < min_price:
                    continue
                r["composite"] = round(r["st_score"] * 0.4 + (r.get("lt_score") or 0) * 0.3 + r["rs_score"] * 0.3, 1)
                results.append(r)
        results.sort(key=lambda x: x["composite"], reverse=True)
        return results[:50]

    results = await loop.run_in_executor(None, _run_screen)
    return {"results": results, "universe_size": len(universe)}
