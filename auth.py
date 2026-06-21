"""
auth.py — Thin authentication layer on top of database.py.
Handles login, logout, registration, permission checks, and input validation.
"""

import re

from database import (
    create_user as db_create_user,
    create_session,
    get_user_by_email,
    invalidate_session,
    log_audit,
    update_last_login,
    validate_session,
    verify_password,
)

# ---------------------------------------------------------------------------
# Role permission map
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "research", "deep_research", "all_sectors", "penny", "email",
        "export", "admin_panel", "audit_log", "user_mgmt", "license_mgmt",
    },
    "analyst": {
        "research", "deep_research", "all_sectors", "penny", "email", "export",
    },
    "trader": {"research", "deep_research"},
    "viewer": {"research"},
}

ROLE_LABELS: dict[str, str] = {
    "admin":   "Administrator",
    "analyst": "Analyst",
    "trader":  "Trader",
    "viewer":  "Viewer",
}

TIER_BADGE_COLOR: dict[str, str] = {
    "free":         "#6B7280",
    "professional": "#2563EB",
    "enterprise":   "#7C3AED",
}

# ---------------------------------------------------------------------------
# Auth functions
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> tuple[dict | None, str]:
    """
    Attempt login. Returns (user_dict_with_token, "") on success,
    or (None, error_message) on failure.
    """
    email = email.strip().lower()

    err = validate_email(email)
    if err:
        return None, err

    user = get_user_by_email(email)
    if user is None:
        return None, "Invalid email or password."

    if not user.get("is_active"):
        return None, "Account is deactivated. Please contact your administrator."

    if not verify_password(password, user["password_hash"]):
        log_audit(
            user_id=user["id"],
            username=user["username"],
            action="login_failed",
            details="Invalid password attempt",
        )
        return None, "Invalid email or password."

    # Create session
    token = create_session(user["id"], hours=8)
    update_last_login(user["id"])

    # Re-fetch via validate_session to get full license context
    full_user = validate_session(token)
    if full_user is None:
        return None, "Session creation failed."

    log_audit(
        user_id=user["id"],
        username=user["username"],
        action="login_success",
        details="",
    )

    return full_user, ""


def logout(token: str, user: dict) -> None:
    """Invalidate session and log the logout action."""
    invalidate_session(token)
    log_audit(
        user_id=user.get("id"),
        username=user.get("username", "unknown"),
        action="logout",
        details="",
    )


def register(
    email: str,
    username: str,
    password: str,
    full_name: str,
    role: str = "viewer",
    license_id: int | None = None,
    consent: bool = False,
) -> tuple[dict | None, str]:
    """
    Register a new user. Returns (user_dict, "") on success,
    or (None, error_message) on failure.
    """
    email = email.strip().lower()
    username = username.strip()
    full_name = full_name.strip()

    err = validate_email(email)
    if err:
        return None, err

    err = validate_username(username)
    if err:
        return None, err

    err = validate_password(password)
    if err:
        return None, err

    if not full_name:
        return None, "Full name is required."

    valid_roles = {"admin", "analyst", "trader", "viewer"}
    if role not in valid_roles:
        return None, f"Invalid role '{role}'. Must be one of: {', '.join(sorted(valid_roles))}."

    try:
        user = db_create_user(
            email=email,
            username=username,
            password=password,
            full_name=full_name,
            role=role,
            license_id=license_id,
            consent=consent,
        )
    except ValueError as exc:
        return None, str(exc)

    log_audit(
        user_id=user["id"],
        username=username,
        action="user_registered",
        details=f"email={email}, role={role}",
    )

    return user, ""


def validate_token(token: str) -> dict | None:
    """Validate a session token. Returns the full user dict or None."""
    return validate_session(token)


def has_permission(user: dict, permission: str) -> bool:
    """
    Check whether the user's role grants the given permission.
    Admins always have all permissions.
    """
    role = user.get("role", "viewer")
    if role == "admin":
        return True
    return permission in ROLE_PERMISSIONS.get(role, set())


def can_use_mode(user: dict, mode: str) -> bool:
    """Return True if the user's license allows the requested research mode."""
    allowed = user.get("allowed_modes", ["free"])
    if isinstance(allowed, list):
        return mode in allowed
    return False


def can_use_sector(user: dict, sector: str) -> bool:
    """Return True if the user's license allows the requested sector."""
    allowed = user.get("allowed_sectors", [])
    if allowed == "all":
        return True
    if isinstance(allowed, list):
        if "all" in allowed:
            return True
        return sector in allowed
    return False


def get_max_picks(user: dict) -> int:
    """Return the maximum number of picks allowed by the user's license."""
    return int(user.get("max_picks", 3))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email: str) -> str:
    """Return an error string, or '' if the email is valid."""
    if not email:
        return "Email is required."
    if not _EMAIL_RE.match(email):
        return "Invalid email address."
    return ""


def validate_password(password: str) -> str:
    """
    Return an error string, or '' if the password meets requirements.
    Rules: min 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 special char.
    """
    if not password:
        return "Password is required."
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one digit."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character."
    return ""


_USERNAME_RE = re.compile(r"^\w+$")


def validate_username(username: str) -> str:
    """
    Return an error string, or '' if the username is valid.
    Rules: 3–30 chars, alphanumeric + underscore only, no spaces.
    """
    if not username:
        return "Username is required."
    if len(username) < 3:
        return "Username must be at least 3 characters long."
    if len(username) > 30:
        return "Username must be 30 characters or fewer."
    if not _USERNAME_RE.match(username):
        return "Username may only contain letters, numbers, and underscores."
    return ""
