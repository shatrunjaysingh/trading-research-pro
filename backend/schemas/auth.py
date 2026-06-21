from datetime import datetime
from typing import Any
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str
    role: str = "viewer"
    license_id: int | None = None
    consent: bool = False


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    full_name: str | None = None
    role: str
    is_active: bool
    license_id: int | None = None
    license_tier: str | None = None
    license_name: str | None = None
    allowed_modes: list[str] | None = None
    allowed_sectors: Any = None
    max_picks: int | None = None
    can_email: bool | None = None
    can_export: bool | None = None
    can_admin: bool | None = None
    must_change_pwd: bool = False
    created_at: datetime | None = None
    last_login: datetime | None = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
