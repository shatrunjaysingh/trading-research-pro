import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

import auth as auth_module
from database import get_user_by_id, update_user, change_password, verify_password, get_audit_log, log_audit, get_user_preferences, save_user_preferences, export_user_data, anonymize_user_gdpr
from backend.schemas.auth import UserOut
from backend.schemas.profile import ChangePasswordRequest, UpdateProfileRequest
from backend.schemas.admin import AuditLogOut
from backend.auth_middleware import get_current_user


class MarketPreferencesRequest(BaseModel):
    market_country: Optional[str] = None
    market_exchanges: Optional[List[str]] = None

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserOut)
def get_profile(current_user: dict = Depends(get_current_user)):
    return current_user


@router.patch("", response_model=UserOut)
def update_profile(body: UpdateProfileRequest, current_user: dict = Depends(get_current_user)):
    if body.full_name is not None:
        update_user(current_user["id"], full_name=body.full_name.strip() or None)
        log_audit(current_user.get("id"), current_user.get("username",""), "profile_update", "Updated full_name")
    return get_user_by_id(current_user["id"])


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password_route(body: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    user = get_user_by_id(current_user["id"])
    if not verify_password(body.current_password, user.get("password_hash","") or user.get("pwd_hash","")):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    err = auth_module.validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    change_password(current_user["id"], body.new_password)
    log_audit(current_user.get("id"), current_user.get("username",""), "password_change", "Changed password")


@router.get("/audit", response_model=list[AuditLogOut])
def my_audit(limit: int = 50, current_user: dict = Depends(get_current_user)):
    return get_audit_log(limit=limit, user_id=current_user["id"])


@router.get("/preferences")
def get_preferences(current_user: dict = Depends(get_current_user)):
    return get_user_preferences(current_user["id"])


@router.put("/preferences", status_code=status.HTTP_204_NO_CONTENT)
def save_preferences(body: MarketPreferencesRequest, current_user: dict = Depends(get_current_user)):
    prefs = body.model_dump(exclude_none=True)
    save_user_preferences(current_user["id"], prefs)


@router.get("/export")
def export_data(current_user: dict = Depends(get_current_user)):
    """GDPR Art.20 — export all data held about the authenticated user."""
    data = export_user_data(current_user["id"])
    log_audit(current_user.get("id"), current_user.get("username", ""), "data_export", "User downloaded their personal data")
    return data


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: str  # must equal "DELETE MY ACCOUNT"


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(body: DeleteAccountRequest, current_user: dict = Depends(get_current_user)):
    """GDPR Art.17 — right to erasure. Pseudonymises the account; audit log retained."""
    if body.confirm != "DELETE MY ACCOUNT":
        raise HTTPException(status_code=400, detail="Confirmation phrase must be exactly: DELETE MY ACCOUNT")
    user = get_user_by_id(current_user["id"])
    if not verify_password(body.password, user.get("password_hash", "") or user.get("pwd_hash", "")):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    log_audit(current_user.get("id"), current_user.get("username", ""), "account_deleted", "User requested GDPR erasure")
    anonymize_user_gdpr(current_user["id"])
