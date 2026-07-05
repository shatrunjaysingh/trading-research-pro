import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

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
        result = await loop.run_in_executor(None, run_daily_digest)
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
