import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from backend.services.market_data import fetch_market_overview
from backend.auth_middleware import get_current_user
import auth as auth_module

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview")
def market_overview(market: str = "all", current_user: dict = Depends(get_current_user)):
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    try:
        return fetch_market_overview(market=market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Market data fetch failed: {exc}")


@router.get("/fear-greed")
def fear_greed_index(current_user: dict = Depends(get_current_user)):
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    try:
        from backend.services.fear_greed import compute_fear_greed
        return compute_fear_greed()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Fear & Greed computation failed: {exc}")


@router.get("/sectors")
def sector_rotation(current_user: dict = Depends(get_current_user)):
    """Sector rotation heatmap — RS scores and week-over-week changes for all 11 GICS sectors."""
    if not auth_module.has_permission(current_user, "research"):
        raise HTTPException(status_code=403, detail="Research permission required.")
    try:
        from backend.services.sector_rotation import compute_sector_rotation
        return compute_sector_rotation()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
