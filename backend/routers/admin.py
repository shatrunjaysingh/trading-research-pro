import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException, Depends, status, Body, BackgroundTasks

import auth as auth_module
import database as db
from database import (
    get_all_users, create_user, update_user, deactivate_user, activate_user,
    delete_user, change_password, get_all_licenses, create_license, update_license,
    deactivate_license, get_audit_log, get_user_count_for_license, log_audit,
    get_token_stats, get_backtest_results, fill_backtest_returns,
    save_hist_backtest, get_hist_backtest_latest,
)
from backend.schemas.admin import (
    CreateUserRequest, UpdateUserRequest, LicenseOut,
    CreateLicenseRequest, UpdateLicenseRequest, AuditLogOut, ResetPasswordRequest,
)
from backend.schemas.auth import UserOut
from backend.auth_middleware import get_current_user, get_all_users_with_licenses

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not auth_module.has_permission(user, "admin_panel"):
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return user


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
def list_users(admin: dict = Depends(_require_admin)):
    return get_all_users_with_licenses()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user_admin(body: CreateUserRequest, admin: dict = Depends(_require_admin)):
    for validator, val in [
        (auth_module.validate_email,    body.email),
        (auth_module.validate_username, body.username),
        (auth_module.validate_password, body.password),
    ]:
        err = validator(val)
        if err:
            raise HTTPException(status_code=400, detail=err)
    try:
        user = create_user(
            email=body.email, username=body.username, password=body.password,
            full_name=body.full_name, role=body.role,
            license_id=body.license_id, created_by=admin.get("id"),
        )
        log_audit(admin.get("id"), admin.get("username",""), "admin_create_user", f"Created {body.email}")
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user_admin(user_id: int, body: UpdateUserRequest, admin: dict = Depends(_require_admin)):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = update_user(user_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    log_audit(admin.get("id"), admin.get("username",""), "admin_update_user", f"Updated user {user_id}")
    from database import get_user_by_id
    return get_user_by_id(user_id)


@router.post("/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user_admin(user_id: int, admin: dict = Depends(_require_admin)):
    deactivate_user(user_id)
    log_audit(admin.get("id"), admin.get("username",""), "admin_deactivate_user", f"Deactivated {user_id}")


@router.post("/users/{user_id}/activate", status_code=status.HTTP_204_NO_CONTENT)
def activate_user_admin(user_id: int, admin: dict = Depends(_require_admin)):
    activate_user(user_id)
    log_audit(admin.get("id"), admin.get("username",""), "admin_activate_user", f"Activated {user_id}")


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_admin(user_id: int, admin: dict = Depends(_require_admin)):
    if user_id == admin.get("id"):
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    ok = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    log_audit(admin.get("id"), admin.get("username",""), "admin_delete_user", f"Deleted user {user_id}")


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password_admin(user_id: int, body: ResetPasswordRequest, admin: dict = Depends(_require_admin)):
    err = auth_module.validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    change_password(user_id, body.new_password)
    log_audit(admin.get("id"), admin.get("username",""), "admin_reset_password", f"Reset password for {user_id}")


# ── Licenses ───────────────────────────────────────────────────────────────────

def _attach_user_count(lic: dict) -> dict:
    try:
        lic["user_count"] = get_user_count_for_license(lic["id"])
    except Exception:
        lic["user_count"] = 0
    return lic


@router.get("/licenses", response_model=list[LicenseOut])
def list_licenses(admin: dict = Depends(_require_admin)):
    return [_attach_user_count(l) for l in get_all_licenses()]


@router.post("/licenses", response_model=LicenseOut, status_code=status.HTTP_201_CREATED)
def create_license_admin(body: CreateLicenseRequest, admin: dict = Depends(_require_admin)):
    lic = create_license(
        name=body.name, tier=body.tier, max_users=body.max_users,
        allowed_modes=body.allowed_modes, allowed_sectors=body.allowed_sectors,
        max_picks=body.max_picks, can_email=1 if body.can_email else 0,
        can_export=1 if body.can_export else 0, can_admin=1 if body.can_admin else 0,
        expires_at=body.expires_at,
    )
    log_audit(admin.get("id"), admin.get("username",""), "admin_create_license", f"Created {body.name}")
    return _attach_user_count(lic)


@router.patch("/licenses/{license_id}", response_model=LicenseOut)
def update_license_admin(license_id: int, body: UpdateLicenseRequest, admin: dict = Depends(_require_admin)):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    # Map bool is_active to int for DB
    if "is_active" in kwargs:
        kwargs["is_active"] = 1 if kwargs["is_active"] else 0
    update_license(license_id, **kwargs)
    log_audit(admin.get("id"), admin.get("username",""), "admin_update_license", f"Updated {license_id}")
    from database import get_license_by_id
    return _attach_user_count(get_license_by_id(license_id))


@router.post("/licenses/{license_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_license_admin(license_id: int, admin: dict = Depends(_require_admin)):
    deactivate_license(license_id)
    log_audit(admin.get("id"), admin.get("username",""), "admin_deactivate_license", f"Deactivated {license_id}")


# ── Audit log ──────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=list[AuditLogOut])
def list_audit(limit: int = 200, user_id: int | None = None, admin: dict = Depends(_require_admin)):
    return get_audit_log(limit=limit, user_id=user_id)


# ── Token usage ────────────────────────────────────────────────────────────────

@router.get("/token-usage")
def token_usage(admin: dict = Depends(_require_admin)):
    """Return token consumption and cost statistics. Admin only."""
    return get_token_stats()


# ── Backtesting ────────────────────────────────────────────────────────────────

@router.get("/backtest")
def backtest(days_back: int = 60, admin: dict = Depends(_require_admin)):
    """Return stored research picks with walk-forward returns. Auto-fills mature picks."""
    # Fill any picks that now have enough history
    try:
        fill_backtest_returns()
    except Exception:
        pass

    rows = get_backtest_results(days_back=days_back)
    if not rows:
        return {"picks": [], "summary": {}}

    # Attach live "current price" for very recent picks (<8 days old) that don't have 5D yet
    recent_tickers = list({r["ticker"] for r in rows if r.get("return_5d_pct") is None})
    live_prices: dict[str, float] = {}
    if recent_tickers:
        try:
            import yfinance as yf
            raw   = yf.download(recent_tickers, period="1d", progress=False,
                                auto_adjust=True, threads=True)
            close = raw["Close"] if "Close" in raw else None
            if close is not None:
                for t in recent_tickers:
                    try:
                        live_prices[t] = float(close[t].dropna().iloc[-1])
                    except Exception:
                        pass
        except Exception:
            pass

    for r in rows:
        entry = r.get("entry_price")
        if r.get("return_5d_pct") is None:
            cur = live_prices.get(r["ticker"])
            r["current_price"] = round(cur, 4) if cur else None
            r["return_current_pct"] = round((cur - entry) / entry * 100, 2) if (cur and entry and entry > 0) else None
        else:
            r["current_price"]      = None
            r["return_current_pct"] = None

    # ── Summary stats using proper forward returns ─────────────────────────────
    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _win(vals):
        v = [x for x in vals if x is not None]
        return round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None

    buy  = [r for r in rows if (r.get("signal") or "").upper() == "BUY"]
    bkot = [r for r in rows if r.get("breakout_flag")]
    sqz  = [r for r in rows if r.get("squeeze_flag")]

    return {
        "picks": rows,
        "fill_stats": {"message": "Returns auto-filled for mature picks"},
        "summary": {
            "total_picks":          len(rows),
            # 5-day forward returns
            "with_5d":              sum(1 for r in rows if r.get("return_5d_pct") is not None),
            "avg_5d_all_pct":       _avg(r.get("return_5d_pct") for r in rows),
            "avg_5d_buy_pct":       _avg(r.get("return_5d_pct") for r in buy),
            "win_rate_5d_buy_pct":  _win(r.get("return_5d_pct") for r in buy),
            # 30-day forward returns
            "with_30d":             sum(1 for r in rows if r.get("return_30d_pct") is not None),
            "avg_30d_all_pct":      _avg(r.get("return_30d_pct") for r in rows),
            "avg_30d_buy_pct":      _avg(r.get("return_30d_pct") for r in buy),
            "win_rate_30d_buy_pct": _win(r.get("return_30d_pct") for r in buy),
            # Signal counts
            "buy_picks":            len(buy),
            # Special flag performance
            "breakout_avg_5d":      _avg(r.get("return_5d_pct") for r in bkot),
            "squeeze_avg_5d":       _avg(r.get("return_5d_pct") for r in sqz),
        },
    }


@router.post("/backtest/fill", status_code=200)
def backtest_fill(admin: dict = Depends(_require_admin)):
    """Manually trigger filling of walk-forward returns. Returns counts updated."""
    return fill_backtest_returns()


# ── Market regime ──────────────────────────────────────────────────────────────

@router.get("/regime")
def market_regime(admin: dict = Depends(_require_admin)):
    """Return current market regime (VIX, SPY trend, score multiplier). Cached 1h."""
    from backend.services.regime_detector import get_market_regime
    return get_market_regime()


# ── Historical backtest ────────────────────────────────────────────────────────

@router.post("/historical-backtest", status_code=200)
def run_hist_backtest(
    years_back: int = 2,
    top_n: int = 5,
    admin: dict = Depends(_require_admin),
):
    """
    Run the 2-year historical backtest simulation.
    Downloads data once, evaluates monthly, optimises factor weights.
    Takes ~20-40 seconds. Results are saved to DB and returned.
    """
    import yaml, os
    from backend.services.historical_backtest import run_historical_backtest

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config.yaml",
    )
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        universe = cfg.get("assets", {}).get("stocks", [])
    except Exception:
        universe = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
                    "TSLA", "LLY", "AVGO", "JPM", "V", "XOM", "UNH",
                    "MA", "JNJ", "PG", "COST", "HD", "MRK", "NFLX"]

    result = run_historical_backtest(universe=universe, years_back=years_back, top_n=top_n)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    from datetime import datetime, timezone
    run_id = datetime.now(timezone.utc).strftime("hist_%Y%m%d_%H%M%S")
    try:
        save_hist_backtest(run_id, result)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not save hist backtest: %s", exc)

    result["run_id"] = run_id
    return result


@router.get("/historical-backtest")
def get_hist_backtest(admin: dict = Depends(_require_admin)):
    """Return the most recent historical backtest result from DB."""
    data = get_hist_backtest_latest()
    if not data:
        return {"message": "No historical backtest results yet. Run POST /admin/historical-backtest."}
    return data


@router.get("/digest-emails")
def list_digest_emails(admin: dict = Depends(_require_admin)):
    return db.get_digest_email_list()


@router.post("/digest-emails")
def add_digest_email(body: dict = Body(...), admin: dict = Depends(_require_admin)):
    email = (body.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    return db.add_digest_email(email, body.get("name", ""))


@router.patch("/digest-emails/{email_id}")
def toggle_digest_email(email_id: int, body: dict = Body(...), admin: dict = Depends(_require_admin)):
    db.toggle_digest_email(email_id, bool(body.get("is_active", True)))
    return {"ok": True}


@router.delete("/digest-emails/{email_id}")
def delete_digest_email(email_id: int, admin: dict = Depends(_require_admin)):
    db.delete_digest_email(email_id)
    return {"ok": True}


@router.post("/test-email")
def test_email(body: dict = Body(...), admin: dict = Depends(_require_admin)):
    """Send a plain test email and return success/error immediately."""
    from backend.config import settings

    to = (body.get("to") or "").strip()
    if not to or "@" not in to:
        raise HTTPException(status_code=400, detail="Provide a valid 'to' email address")

    sg_key = settings.sendgrid_api_key.strip()
    sender = settings.email_sender.strip()

    if not sg_key and not (sender and settings.email_app_password.strip()):
        return {"ok": False, "error": "No email provider configured. Set SENDGRID_API_KEY on Render."}

    try:
        from backend.services.email_service import send_email
        send_email(to, "TradingResearch Pro — Email test", "<h2>It works!</h2><p>Email delivery is configured correctly.</p>")
        method = "SendGrid" if sg_key else "SMTP"
        return {"ok": True, "sent_to": to, "from": sender or "via SendGrid", "method": method}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _run_digest_background() -> None:
    import logging
    log = logging.getLogger(__name__)
    try:
        from backend.services.daily_digest import run_daily_digest
        result = run_daily_digest(force=True)
        log.info("Background digest complete: %s", result)
    except Exception as exc:
        log.error("Background digest failed: %s", exc)


@router.post("/send-digest")
def send_digest_now(background_tasks: BackgroundTasks, admin: dict = Depends(_require_admin)):
    """Kick off the daily digest in the background and return immediately."""
    background_tasks.add_task(_run_digest_background)
    return {"status": "started", "message": "Digest is running — check your inbox in 2–3 minutes."}
