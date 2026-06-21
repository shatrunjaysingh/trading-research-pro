import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, status, Depends

import auth as auth_module
from database import invalidate_session, log_audit
from backend.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from backend.services.jwt import create_access_token
from backend.auth_middleware import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user, err = auth_module.login(body.email, body.password)
    if err or not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=err or "Login failed.")
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest):
    if not body.consent:
        raise HTTPException(status_code=400, detail="You must accept the Terms of Use and disclaimer to create an account.")

    err_email = auth_module.validate_email(body.email)
    if err_email:
        raise HTTPException(status_code=400, detail=err_email)
    err_user = auth_module.validate_username(body.username)
    if err_user:
        raise HTTPException(status_code=400, detail=err_user)
    err_pass = auth_module.validate_password(body.password)
    if err_pass:
        raise HTTPException(status_code=400, detail=err_pass)

    user, err = auth_module.register(
        email=body.email, username=body.username,
        password=body.password, full_name=body.full_name,
        role=body.role, license_id=body.license_id,
        consent=body.consent,
    )
    if err or not user:
        raise HTTPException(status_code=400, detail=err or "Registration failed.")
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: dict = Depends(get_current_user)):
    sid = current_user.get("_jwt_sid", "")
    if sid:
        try:
            invalidate_session(sid)
        except Exception:
            pass
    try:
        log_audit(current_user.get("id"), current_user.get("username", ""), "logout", "")
    except Exception:
        pass


@router.get("/me", response_model=UserOut)
def me(current_user: dict = Depends(get_current_user)):
    return current_user
