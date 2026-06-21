import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.services.jwt import decode_access_token
from database import get_db
import psycopg2.extras
from datetime import timezone

_bearer = HTTPBearer()


def _get_user_with_license(user_id: int) -> dict | None:
    """Fetch user joined with license — same shape as validate_session()."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT u.*,
                      l.tier AS license_tier, l.name AS license_name,
                      l.allowed_modes, l.allowed_sectors, l.max_picks,
                      l.can_email, l.can_export, l.can_admin
               FROM users u
               LEFT JOIN licenses l ON u.license_id = l.id
               WHERE u.id = %s AND u.is_active = TRUE""",
            (user_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    user = dict(row)
    if user.get("license_tier") is None:
        user.update(license_tier="free", license_name="Free Tier",
                    allowed_modes=["free"], allowed_sectors=["technology","consumer"],
                    max_picks=3, can_email=False, can_export=False, can_admin=False)
    return user


def get_all_users_with_licenses() -> list[dict]:
    """Return all users joined with their license tier — used by admin listing."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT u.*,
                      l.tier AS license_tier, l.name AS license_name,
                      l.allowed_modes, l.allowed_sectors, l.max_picks,
                      l.can_email, l.can_export, l.can_admin
               FROM users u
               LEFT JOIN licenses l ON u.license_id = l.id
               ORDER BY u.id"""
        )
        rows = cur.fetchall()

    result = []
    for row in rows:
        user = dict(row)
        if user.get("license_tier") is None:
            user.update(license_tier="free", license_name="Free Tier",
                        allowed_modes=["free"], allowed_sectors=["technology","consumer"],
                        max_picks=3, can_email=False, can_export=False, can_admin=False)
        result.append(user)
    return result


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    token   = creds.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

    user_id = int(payload["sub"])
    user    = _get_user_with_license(user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")

    user["_jwt_sid"] = payload.get("sid", "")
    return user
