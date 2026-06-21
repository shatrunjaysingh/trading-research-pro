import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Request
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
