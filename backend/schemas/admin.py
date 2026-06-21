from datetime import datetime
from typing import Any
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str
    role: str = "viewer"
    license_id: int | None = None


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: str | None = None
    license_id: int | None = None
    is_active: bool | None = None
    must_change_pwd: bool | None = None


class CreateLicenseRequest(BaseModel):
    name: str
    tier: str
    max_users: int = 5
    allowed_modes: str = "free"
    allowed_sectors: str = ""
    max_picks: int = 5
    can_email: bool = False
    can_export: bool = False
    can_admin: bool = False
    expires_at: str | None = None


class UpdateLicenseRequest(BaseModel):
    name: str | None = None
    max_users: int | None = None
    max_picks: int | None = None
    allowed_modes: str | None = None
    is_active: bool | None = None


class LicenseOut(BaseModel):
    id: int
    name: str
    tier: str
    max_users: int
    allowed_modes: Any
    allowed_sectors: Any
    max_picks: int
    can_email: bool
    can_export: bool
    can_admin: bool
    expires_at: Any
    is_active: bool
    created_at: datetime | None
    user_count: int = 0


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    username: str | None
    action: str | None
    details: str | None
    ip_address: str | None
    created_at: datetime | None


class ResetPasswordRequest(BaseModel):
    new_password: str
