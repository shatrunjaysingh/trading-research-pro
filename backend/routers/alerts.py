import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

import database as db
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


class DigestPreference(BaseModel):
    enabled: bool


@router.get("/preferences")
async def get_preferences(current_user: dict = Depends(get_current_user)):
    user = db.get_user_by_id(current_user["id"])
    return {"digest_enabled": bool((user or {}).get("digest_enabled", False))}


@router.put("/preferences")
async def set_preferences(body: DigestPreference, current_user: dict = Depends(get_current_user)):
    db.set_digest_enabled(current_user["id"], body.enabled)
    return {"digest_enabled": body.enabled}


@router.post("/send-now")
async def send_digest_now(current_user: dict = Depends(get_current_user)):
    """Admin-only: manually trigger the daily digest immediately."""
    if not current_user.get("can_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        from backend.services.daily_digest import run_daily_digest
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: run_daily_digest(force=True))
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/digest-history")
async def digest_history(current_user: dict = Depends(get_current_user)):
    """Return last 30 digest run records. Admin only."""
    if not current_user.get("can_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    with db.get_db() as conn:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM digest_runs ORDER BY run_date DESC LIMIT 30")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


class PriceAlertCreate(BaseModel):
    ticker: str
    condition: str
    target_price: Optional[float] = None
    note: str = ''


@router.get("/price")
async def list_price_alerts(current_user: dict = Depends(get_current_user)):
    return db.get_price_alerts(current_user["id"])


@router.post("/price")
async def create_price_alert_route(body: PriceAlertCreate, current_user: dict = Depends(get_current_user)):
    VALID_CONDITIONS = {
        'above', 'below', 'breakout_52w_high', 'breakdown_52w_low',
        'cross_sma50_up', 'cross_sma50_down', 'cross_sma200_up', 'cross_sma200_down',
    }
    if body.condition not in VALID_CONDITIONS:
        raise HTTPException(status_code=400, detail=f"Invalid condition. Must be one of: {', '.join(VALID_CONDITIONS)}")
    if body.condition in ('above', 'below') and body.target_price is None:
        raise HTTPException(status_code=400, detail="target_price required for 'above'/'below' conditions")
    return db.create_price_alert(current_user["id"], body.ticker, body.condition, body.target_price, body.note)


@router.delete("/price/{alert_id}")
async def delete_price_alert_route(alert_id: int, current_user: dict = Depends(get_current_user)):
    deleted = db.delete_price_alert(current_user["id"], alert_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"deleted": alert_id}


@router.patch("/price/{alert_id}/toggle")
async def toggle_price_alert_route(alert_id: int, current_user: dict = Depends(get_current_user)):
    alerts = db.get_price_alerts(current_user["id"])
    alert = next((a for a in alerts if a["id"] == alert_id), None)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    new_state = not alert["is_active"]
    db.toggle_price_alert(current_user["id"], alert_id, new_state)
    return {"id": alert_id, "is_active": new_state}
