from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from backend.config import settings


def create_access_token(user: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.access_token_expire_hours)
    payload = {
        "sub":           str(user["id"]),
        "role":          user.get("role", "viewer"),
        "license_tier":  user.get("license_tier", "free"),
        "sid":           user.get("token", ""),   # original session token for logout
        "exp":           expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
