"""
database.py — PostgreSQL-backed database layer for the trading research app.
Uses psycopg2 with a ThreadedConnectionPool for Streamlit's multi-threaded env.
"""

import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trading_user:trading_pass@localhost:5432/trading_research",
)

# ---------------------------------------------------------------------------
# Connection pool (lazy-initialised)
# ---------------------------------------------------------------------------

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL,
        )
    return _pool


@contextmanager
def get_db():
    """Context manager that yields a pooled connection with auto commit/rollback."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict | None:
    """Convert a RealDictRow (or None) to a plain dict."""
    if row is None:
        return None
    return dict(row)


def _parse_license_fields(d: dict) -> dict:
    """
    JSONB fields come back as Python objects from psycopg2 — no json.loads needed.
    This is a no-op for PostgreSQL but kept for interface parity.
    """
    return d


# ---------------------------------------------------------------------------
# Schema & seed
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS licenses (
        id              SERIAL PRIMARY KEY,
        name            TEXT NOT NULL,
        tier            TEXT NOT NULL CHECK(tier IN ('free','professional','enterprise')),
        max_users       INTEGER DEFAULT 1,
        allowed_modes   JSONB DEFAULT '["free"]'::jsonb,
        allowed_sectors JSONB DEFAULT '["technology","consumer"]'::jsonb,
        max_picks       INTEGER DEFAULT 3,
        can_email       BOOLEAN DEFAULT FALSE,
        can_export      BOOLEAN DEFAULT FALSE,
        can_admin       BOOLEAN DEFAULT FALSE,
        expires_at      TIMESTAMPTZ,
        is_active       BOOLEAN DEFAULT TRUE,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id              SERIAL PRIMARY KEY,
        email           TEXT UNIQUE NOT NULL,
        username        TEXT UNIQUE NOT NULL,
        password_hash   TEXT NOT NULL,
        full_name       TEXT NOT NULL,
        role            TEXT DEFAULT 'viewer' CHECK(role IN ('admin','analyst','trader','viewer')),
        is_active       BOOLEAN DEFAULT TRUE,
        license_id      INTEGER REFERENCES licenses(id) ON DELETE SET NULL,
        must_change_pwd BOOLEAN DEFAULT FALSE,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        last_login      TIMESTAMPTZ,
        created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token       TEXT UNIQUE NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        expires_at  TIMESTAMPTZ NOT NULL,
        is_active   BOOLEAN DEFAULT TRUE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_token   ON sessions(token)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER,
        username    TEXT,
        action      TEXT NOT NULL,
        details     TEXT,
        ip_address  TEXT,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS analysis_cache (
        cache_key   VARCHAR(24) PRIMARY KEY,
        ticker      VARCHAR(20) NOT NULL,
        mode        VARCHAR(10) NOT NULL,
        result_json TEXT        NOT NULL,
        expires_at  TIMESTAMPTZ NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        hit_count   INTEGER     DEFAULT 0,
        last_hit_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cache_ticker  ON analysis_cache(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_cache_expires ON analysis_cache(expires_at)",
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        id            SERIAL PRIMARY KEY,
        user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
        username      TEXT,
        feature       TEXT NOT NULL,
        ticker        TEXT,
        model         TEXT NOT NULL,
        input_tokens  INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens  INTEGER NOT NULL DEFAULT 0,
        cost_usd      NUMERIC(12,8) DEFAULT 0,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_token_usage_user_id    ON token_usage(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_token_usage_feature    ON token_usage(feature)",
    # Backtest picks — store scored picks so we can measure actual returns later
    """
    CREATE TABLE IF NOT EXISTS backtest_picks (
        id           SERIAL PRIMARY KEY,
        run_date     DATE          NOT NULL,
        sector       TEXT,
        ticker       TEXT          NOT NULL,
        asset_type   TEXT          DEFAULT 'stock',
        score        INTEGER,
        confidence   INTEGER,
        signal       TEXT,
        entry_price  NUMERIC(16,6),
        week_chg_pct NUMERIC(8,2),
        month_chg_pct NUMERIC(8,2),
        qtr_chg_pct  NUMERIC(8,2),
        rs_vs_spy    NUMERIC(8,2),
        breakout_flag BOOLEAN      DEFAULT FALSE,
        earnings_flag TEXT,
        created_at   TIMESTAMPTZ   DEFAULT NOW(),
        UNIQUE(run_date, sector, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_backtest_run_date ON backtest_picks(run_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_backtest_ticker   ON backtest_picks(ticker)",
    # Walk-forward return columns (filled lazily by fill_backtest_returns)
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS price_5d         NUMERIC(16,6)",
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS return_5d_pct    NUMERIC(8,2)",
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS price_30d        NUMERIC(16,6)",
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS return_30d_pct   NUMERIC(8,2)",
    # Scoring signal columns
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS eps_surprise_pct NUMERIC(8,2)",
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS short_pct_float  NUMERIC(6,2)",
    "ALTER TABLE backtest_picks ADD COLUMN IF NOT EXISTS squeeze_flag     BOOLEAN DEFAULT FALSE",
    # Historical backtest — 2-year simulation results
    """
    CREATE TABLE IF NOT EXISTS hist_backtest_meta (
        run_id            TEXT PRIMARY KEY,
        universe          JSONB,
        years_back        INTEGER,
        top_n             INTEGER,
        n_evaluations     INTEGER,
        n_picks_total     INTEGER,
        avg_return_5d     NUMERIC(8,2),
        win_rate_5d       NUMERIC(6,2),
        sharpe_5d         NUMERIC(6,2),
        avg_alpha_5d      NUMERIC(8,2),
        avg_return_21d    NUMERIC(8,2),
        win_rate_21d      NUMERIC(6,2),
        sharpe_21d        NUMERIC(6,2),
        avg_alpha_21d     NUMERIC(8,2),
        optimal_weights   JSONB,
        in_sample_avg     NUMERIC(8,2),
        out_sample_avg    NUMERIC(8,2),
        in_sample_sharpe  NUMERIC(6,2),
        out_sample_sharpe NUMERIC(6,2),
        created_at        TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hist_backtest_runs (
        id          SERIAL PRIMARY KEY,
        run_id      TEXT NOT NULL REFERENCES hist_backtest_meta(run_id) ON DELETE CASCADE,
        eval_date   DATE NOT NULL,
        ticker      TEXT NOT NULL,
        rank        INTEGER,
        score       NUMERIC(6,2),
        entry_price NUMERIC(16,6),
        return_5d   NUMERIC(8,2),
        return_21d  NUMERIC(8,2),
        return_63d  NUMERIC(8,2),
        alpha_5d    NUMERIC(8,2),
        alpha_21d   NUMERIC(8,2),
        factors     JSONB,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(run_id, eval_date, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hist_meta_created ON hist_backtest_meta(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hist_runs_run_id  ON hist_backtest_runs(run_id)",
    # Watchlist
    """
    CREATE TABLE IF NOT EXISTS watchlists (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticker      TEXT NOT NULL,
        notes       TEXT,
        added_at    TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(user_id, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlists(user_id)",
    # Daily digest subscriptions & run log
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS digest_enabled BOOLEAN DEFAULT FALSE",
    """
    CREATE TABLE IF NOT EXISTS digest_runs (
        id          SERIAL PRIMARY KEY,
        run_date    DATE NOT NULL UNIQUE,
        st_count    INTEGER DEFAULT 0,
        lt_count    INTEGER DEFAULT 0,
        users_sent  INTEGER DEFAULT 0,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    # Saved portfolio — persistent holdings per user for daily review
    """
    CREATE TABLE IF NOT EXISTS saved_portfolios (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticker      TEXT NOT NULL,
        shares      NUMERIC(16,6) NOT NULL,
        avg_cost    NUMERIC(16,4) NOT NULL,
        updated_at  TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(user_id, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_saved_portfolio_user ON saved_portfolios(user_id)",
    # Price alerts
    """
    CREATE TABLE IF NOT EXISTS price_alerts (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticker       TEXT NOT NULL,
        condition    TEXT NOT NULL CHECK(condition IN ('above','below','breakout_52w_high','breakdown_52w_low','cross_sma50_up','cross_sma50_down','cross_sma200_up','cross_sma200_down')),
        target_price NUMERIC(16,4),
        note         TEXT DEFAULT '',
        is_active    BOOLEAN DEFAULT TRUE,
        triggered_at TIMESTAMPTZ,
        created_at   TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_price_alerts_user ON price_alerts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_price_alerts_active ON price_alerts(is_active) WHERE is_active = TRUE",
    """
    CREATE TABLE IF NOT EXISTS trade_journal (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticker       TEXT NOT NULL,
        direction    TEXT NOT NULL CHECK(direction IN ('long','short')),
        entry_date   DATE NOT NULL,
        exit_date    DATE,
        entry_price  NUMERIC(16,4) NOT NULL,
        exit_price   NUMERIC(16,4),
        shares       NUMERIC(16,6) NOT NULL,
        setup        TEXT DEFAULT '',
        notes        TEXT DEFAULT '',
        outcome      TEXT CHECK(outcome IN ('win','loss','breakeven','open')),
        realized_pnl NUMERIC(16,4),
        realized_pnl_pct NUMERIC(8,2),
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_journal_user_id ON trade_journal(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_journal_ticker  ON trade_journal(ticker)",
    # Immutable audit log — prevent any DELETE at the database level
    """
    CREATE OR REPLACE FUNCTION _prevent_audit_delete() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'audit_log is immutable for regulatory compliance (SEC 17a-4 / MiFID II Art.16). Contact your DPO to action a lawful erasure request.';
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    DO $$ BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_no_delete' AND tgrelid = 'audit_log'::regclass
      ) THEN
        CREATE TRIGGER trg_audit_no_delete
        BEFORE DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION _prevent_audit_delete();
      END IF;
    END $$
    """,
]


def init_db() -> None:
    """Create schema and seed default data. Safe to call multiple times."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Create schema
        for stmt in _SCHEMA_STATEMENTS:
            cur.execute(stmt)

        # --- Seed licenses if empty ---
        cur.execute("SELECT COUNT(*) AS cnt FROM licenses")
        if cur.fetchone()["cnt"] == 0:
            licenses = [
                (
                    "Free Tier", "free", 1,
                    ["free"],
                    ["technology", "consumer"],
                    3, False, False, False, None,
                ),
                (
                    "Professional", "professional", 5,
                    ["free", "api"],
                    "all",
                    10, True, True, False, None,
                ),
                (
                    "Enterprise", "enterprise", -1,
                    ["free", "api"],
                    "all",
                    10, True, True, True, None,
                ),
            ]
            for lic in licenses:
                cur.execute(
                    """INSERT INTO licenses
                       (name, tier, max_users, allowed_modes, allowed_sectors,
                        max_picks, can_email, can_export, can_admin, expires_at)
                       VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)""",
                    (
                        lic[0], lic[1], lic[2],
                        psycopg2.extras.Json(lic[3]),
                        psycopg2.extras.Json(lic[4]),
                        lic[5], lic[6], lic[7], lic[8], lic[9],
                    ),
                )

        # --- Seed admin user if it doesn't exist ---
        cur.execute("SELECT id FROM users WHERE email='admin@tradingresearch.com'")
        if cur.fetchone() is None:
            cur.execute(
                "SELECT id FROM licenses WHERE tier='enterprise' LIMIT 1"
            )
            ent_row = cur.fetchone()
            ent_id = ent_row["id"] if ent_row else None

            pwd_hash = hash_password("Admin123!")
            cur.execute(
                """INSERT INTO users
                   (email, username, password_hash, full_name, role,
                    license_id, must_change_pwd)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (email) DO UPDATE
                   SET password_hash = EXCLUDED.password_hash,
                       role = 'admin', is_active = TRUE""",
                (
                    "admin@tradingresearch.com", "admin", pwd_hash,
                    "System Administrator", "admin", ent_id, False,
                ),
            )


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        return _row_to_dict(cur.fetchone())


def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _row_to_dict(cur.fetchone())


def get_all_users() -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]


def create_user(
    email: str,
    username: str,
    password: str,
    full_name: str,
    role: str = "viewer",
    license_id: int | None = None,
    created_by: int | None = None,
    consent: bool = False,
) -> dict:
    """Create a new user. Raises ValueError on duplicate email/username."""
    from datetime import timezone as _tz
    pwd_hash = hash_password(password)
    consent_at = datetime.now(_tz.utc) if consent else None
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """INSERT INTO users
                   (email, username, password_hash, full_name, role,
                    license_id, created_by, consent_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (email, username, pwd_hash, full_name, role, license_id, created_by, consent_at),
            )
            return _row_to_dict(cur.fetchone())
    except psycopg2.errors.UniqueViolation as exc:
        detail = str(exc)
        if "email" in detail:
            raise ValueError(f"Email '{email}' is already registered.")
        elif "username" in detail:
            raise ValueError(f"Username '{username}' is already taken.")
        else:
            raise ValueError("A user with that email or username already exists.")


def update_user(
    user_id: int,
    full_name: str | None = None,
    role: str | None = None,
    license_id: int | None = None,
    is_active: bool | None = None,
    must_change_pwd: bool | None = None,
) -> bool:
    """Update user fields. Returns True if a row was updated."""
    fields = []
    values = []
    if full_name is not None:
        fields.append("full_name = %s")
        values.append(full_name)
    if role is not None:
        fields.append("role = %s")
        values.append(role)
    if license_id is not None:
        fields.append("license_id = %s")
        values.append(license_id)
    if is_active is not None:
        fields.append("is_active = %s")
        values.append(bool(is_active))
    if must_change_pwd is not None:
        fields.append("must_change_pwd = %s")
        values.append(bool(must_change_pwd))
    if not fields:
        return False

    values.append(user_id)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = %s",
            values,
        )
        return cur.rowcount > 0


def change_password(user_id: int, new_password: str) -> bool:
    pwd_hash = hash_password(new_password)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_pwd = FALSE WHERE id = %s",
            (pwd_hash, user_id),
        )
        return cur.rowcount > 0


def get_user_preferences(user_id: int) -> dict:
    import json
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT preferences FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row and row.get("preferences"):
            prefs = row["preferences"]
            return dict(prefs) if isinstance(prefs, dict) else json.loads(prefs)
        return {}


def save_user_preferences(user_id: int, prefs: dict) -> None:
    import json
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET preferences = %s::jsonb WHERE id = %s",
            (json.dumps(prefs), user_id),
        )


def export_user_data(user_id: int) -> dict:
    """Return all data held about a user — satisfies GDPR Art.20 data portability."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, email, username, full_name, role, created_at, last_login, consent_at, preferences FROM users WHERE id = %s",
            (user_id,),
        )
        profile = _row_to_dict(cur.fetchone()) or {}

        cur.execute(
            "SELECT action, details, created_at FROM audit_log WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        )
        activity = [dict(r) for r in cur.fetchall()]

    return {
        "export_generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "activity_log": activity,
        "note": "Exported under GDPR Article 20 — Right to Data Portability",
    }


def anonymize_user_gdpr(user_id: int) -> None:
    """
    Pseudonymise a user record to honour a GDPR erasure request (Art.17).
    Audit log entries are retained (legal obligation) but username is nulled.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE users SET
                email        = %s,
                username     = %s,
                full_name    = 'Deleted User',
                password_hash = '',
                is_active    = FALSE,
                preferences  = '{}'::jsonb,
                deleted_at   = NOW()
               WHERE id = %s""",
            (f"deleted_{user_id}@deleted.invalid", f"deleted_{user_id}", user_id),
        )
        # Anonymise PII in audit log (action/timestamps kept for compliance)
        cur.execute(
            "UPDATE audit_log SET username = NULL WHERE user_id = %s",
            (user_id,),
        )
        # Invalidate all sessions
        cur.execute(
            "UPDATE sessions SET is_active = FALSE WHERE user_id = %s",
            (user_id,),
        )


def deactivate_user(user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,)
        )
        return cur.rowcount > 0


def activate_user(user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET is_active = TRUE WHERE id = %s", (user_id,)
        )
        return cur.rowcount > 0


def update_last_login(user_id: int) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,)
        )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(user_id: int, hours: int = 8) -> str:
    """Create a session token and return it."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sessions (user_id, token, expires_at) VALUES (%s, %s, %s)",
            (user_id, token, expires_at),
        )
    return token


def validate_session(token: str) -> dict | None:
    """
    Return a merged user+license dict if the session token is valid and
    not expired, otherwise None.
    """
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT u.*,
                      l.tier AS license_tier, l.name AS license_name,
                      l.allowed_modes, l.allowed_sectors, l.max_picks,
                      l.can_email, l.can_export, l.can_admin,
                      s.expires_at
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               LEFT JOIN licenses l ON u.license_id = l.id
               WHERE s.token = %s AND s.is_active = TRUE AND u.is_active = TRUE""",
            (token,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    if datetime.now(timezone.utc) > row["expires_at"]:
        return None

    user = dict(row)

    # Provide defaults when no license is assigned
    if user.get("license_tier") is None:
        user["license_tier"] = "free"
        user["license_name"] = "Free Tier"
        user["allowed_modes"] = ["free"]
        user["allowed_sectors"] = ["technology", "consumer"]
        user["max_picks"] = 3
        user["can_email"] = False
        user["can_export"] = False
        user["can_admin"] = False

    user["token"] = token
    return user


def invalidate_session(token: str) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sessions SET is_active = FALSE WHERE token = %s", (token,)
        )


def cleanup_expired_sessions() -> None:
    """Delete session rows where expires_at is in the past or session is inactive."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM sessions WHERE expires_at < NOW() OR is_active = FALSE"
        )


# ---------------------------------------------------------------------------
# License CRUD
# ---------------------------------------------------------------------------

def get_all_licenses() -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM licenses ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_license_by_id(license_id: int) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM licenses WHERE id = %s", (license_id,))
        return _row_to_dict(cur.fetchone())


def get_user_count_for_license(license_id: int) -> int:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE license_id = %s", (license_id,)
        )
        return cur.fetchone()["cnt"]


def count_active_users_for_license(license_id: int) -> int:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE license_id = %s AND is_active = TRUE",
            (license_id,),
        )
        return cur.fetchone()["cnt"]


def create_license(
    name: str,
    tier: str,
    max_users: int,
    allowed_modes: list,
    allowed_sectors,  # list or "all"
    max_picks: int,
    can_email: bool,
    can_export: bool,
    can_admin: bool,
    expires_at: str | None = None,
) -> dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """INSERT INTO licenses
               (name, tier, max_users, allowed_modes, allowed_sectors,
                max_picks, can_email, can_export, can_admin, expires_at)
               VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
               RETURNING *""",
            (
                name, tier, max_users,
                psycopg2.extras.Json(allowed_modes),
                psycopg2.extras.Json(allowed_sectors),
                max_picks,
                bool(can_email),
                bool(can_export),
                bool(can_admin),
                expires_at,
            ),
        )
        return _row_to_dict(cur.fetchone())


def update_license(license_id: int, **kwargs) -> bool:
    """Update arbitrary license fields supplied as kwargs."""
    if not kwargs:
        return False

    # JSONB fields: pass Python objects directly wrapped in Json adapter
    for field in ("allowed_modes", "allowed_sectors"):
        if field in kwargs:
            kwargs[field] = psycopg2.extras.Json(kwargs[field])

    fields = [f"{k} = %s" for k in kwargs]
    values = list(kwargs.values())
    values.append(license_id)

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE licenses SET {', '.join(fields)} WHERE id = %s",
            values,
        )
        return cur.rowcount > 0


def deactivate_license(license_id: int) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE licenses SET is_active = FALSE WHERE id = %s", (license_id,)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_audit(
    user_id: int | None,
    username: str,
    action: str,
    details: str = "",
    ip: str = "",
) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO audit_log
               (user_id, username, action, details, ip_address)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, username, action, details, ip),
        )


def get_audit_log(limit: int = 200, user_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if user_id is not None:
            cur.execute(
                "SELECT * FROM audit_log WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                (user_id, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,)
            )
        return [_row_to_dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------

# Pricing per million tokens (update when Anthropic changes rates)
_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":  (3.00, 15.00),   # (input $/1M, output $/1M)
    "claude-opus-4-8":    (15.00, 75.00),
    "claude-haiku-4-5":   (0.80, 4.00),
}
_DEFAULT_PRICE = (3.00, 15.00)


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _TOKEN_PRICES.get(model, _DEFAULT_PRICE)
    return (input_tokens / 1_000_000 * in_price) + (output_tokens / 1_000_000 * out_price)


def log_token_usage(
    user_id: int | None,
    username: str | None,
    feature: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    ticker: str | None = None,
) -> None:
    total = input_tokens + output_tokens
    cost  = _calc_cost(model, input_tokens, output_tokens)
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO token_usage
                   (user_id, username, feature, ticker, model,
                    input_tokens, output_tokens, total_tokens, cost_usd)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (user_id, username, feature, ticker, model,
                 input_tokens, output_tokens, total, round(cost, 8)),
            )
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("log_token_usage failed: %s", exc)


def get_token_stats() -> dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                COUNT(*)                        AS total_calls,
                COALESCE(SUM(input_tokens),  0) AS total_input_tokens,
                COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                COALESCE(SUM(total_tokens),  0) AS total_tokens,
                COALESCE(SUM(cost_usd),      0) AS total_cost
            FROM token_usage
        """)
        summary = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT
                COUNT(*)                        AS today_calls,
                COALESCE(SUM(total_tokens),  0) AS today_tokens,
                COALESCE(SUM(cost_usd),      0) AS today_cost
            FROM token_usage
            WHERE created_at >= CURRENT_DATE
        """)
        today = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT
                COUNT(*)                        AS this_month_calls,
                COALESCE(SUM(total_tokens),  0) AS this_month_tokens,
                COALESCE(SUM(cost_usd),      0) AS month_cost
            FROM token_usage
            WHERE created_at >= DATE_TRUNC('month', NOW())
        """)
        this_month = dict(cur.fetchone() or {})

        cur.execute("""
            SELECT feature,
                   COUNT(*)                        AS call_count,
                   COALESCE(SUM(total_tokens),  0) AS total_tokens,
                   COALESCE(SUM(cost_usd),      0) AS total_cost
            FROM token_usage
            GROUP BY feature
            ORDER BY total_cost DESC
        """)
        by_feature = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT username,
                   COUNT(*)                        AS call_count,
                   COALESCE(SUM(total_tokens),  0) AS total_tokens,
                   COALESCE(SUM(cost_usd),      0) AS total_cost,
                   MAX(created_at)                 AS last_used
            FROM token_usage
            GROUP BY username
            ORDER BY total_cost DESC
            LIMIT 50
        """)
        by_user = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT DATE(created_at AT TIME ZONE 'UTC') AS date,
                   COUNT(*)                        AS call_count,
                   COALESCE(SUM(total_tokens),  0) AS total_tokens,
                   COALESCE(SUM(cost_usd),      0) AS total_cost
            FROM token_usage
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at AT TIME ZONE 'UTC')
            ORDER BY date DESC
        """)
        daily = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, username, feature, ticker, model,
                   input_tokens, output_tokens, total_tokens, cost_usd, created_at
            FROM token_usage
            ORDER BY id DESC
            LIMIT 100
        """)
        recent = [dict(r) for r in cur.fetchall()]

    return {
        "summary":    {**summary, **today, **this_month},
        "by_feature": by_feature,
        "by_user":    by_user,
        "daily":      daily,
        "recent":     recent,
    }


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

_log = __import__("logging")


def log_backtest_picks(run_date: str, sector: str, picks: list) -> None:
    """Persist free-mode scored picks so actual returns can be measured later."""
    if not picks:
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            for p in picks:
                ticker = (p.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                try:
                    cur.execute(
                        """
                        INSERT INTO backtest_picks
                            (run_date, sector, ticker, asset_type, score, confidence,
                             signal, entry_price, week_chg_pct, month_chg_pct,
                             qtr_chg_pct, rs_vs_spy, breakout_flag, earnings_flag,
                             eps_surprise_pct, short_pct_float, squeeze_flag)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_date, sector, ticker) DO NOTHING
                        """,
                        (
                            run_date, sector, ticker,
                            p.get("type", "stock"),
                            p.get("score"),
                            p.get("confidence"),
                            p.get("signal"),
                            p.get("current_price"),
                            p.get("week_change_pct"),
                            p.get("month_change_pct"),
                            p.get("qtr_change_pct"),
                            p.get("rs_vs_spy"),
                            bool(p.get("breakout_flag", False)),
                            p.get("earnings_flag"),
                            p.get("eps_surprise_pct"),
                            p.get("short_pct_float"),
                            bool(p.get("squeeze_flag", False)),
                        ),
                    )
                except Exception as exc:
                    _log.getLogger(__name__).warning("backtest insert failed %s: %s", ticker, exc)


def get_backtest_results(days_back: int = 60, limit: int = 300) -> list:
    """Return stored backtest picks from the last N days, newest first."""
    _FLOAT_COLS = (
        "entry_price", "week_chg_pct", "month_chg_pct", "qtr_chg_pct",
        "rs_vs_spy", "price_5d", "return_5d_pct", "price_30d", "return_30d_pct",
        "eps_surprise_pct", "short_pct_float",
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, run_date, sector, ticker, asset_type,
                       score, confidence, signal, entry_price,
                       week_chg_pct, month_chg_pct, qtr_chg_pct,
                       rs_vs_spy, breakout_flag, earnings_flag,
                       price_5d, return_5d_pct, price_30d, return_30d_pct,
                       eps_surprise_pct, short_pct_float, squeeze_flag,
                       created_at
                FROM backtest_picks
                WHERE run_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
                ORDER BY run_date DESC, score DESC NULLS LAST
                LIMIT %s
                """,
                (days_back, limit),
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                if hasattr(d.get("run_date"), "isoformat"):
                    d["run_date"] = d["run_date"].isoformat()
                if hasattr(d.get("created_at"), "isoformat"):
                    d["created_at"] = d["created_at"].isoformat()
                for k in _FLOAT_COLS:
                    if d.get(k) is not None:
                        d[k] = float(d[k])
                rows.append(d)
            return rows


def fill_backtest_returns() -> dict:
    """
    For mature picks (>8 days old for 5D, >35 days for 30D), fetch the actual
    forward prices from yfinance and store them so we have real walk-forward returns.
    Returns {"filled_5d": N, "filled_30d": N}.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {"filled_5d": 0, "filled_30d": 0}

    from datetime import date, timedelta

    # Fetch rows that still need fills
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, ticker, run_date, entry_price, price_5d, price_30d
                FROM backtest_picks
                WHERE entry_price > 0
                  AND (
                    (price_5d  IS NULL AND run_date <= CURRENT_DATE - INTERVAL '8 days')
                    OR
                    (price_30d IS NULL AND run_date <= CURRENT_DATE - INTERVAL '35 days')
                  )
                ORDER BY ticker, run_date
                """
            )
            pending = [dict(r) for r in cur.fetchall()]

    if not pending:
        return {"filled_5d": 0, "filled_30d": 0}

    # Group by ticker to minimise yfinance calls
    from collections import defaultdict
    by_ticker: dict = defaultdict(list)
    for row in pending:
        by_ticker[row["ticker"]].append(row)

    filled_5d = filled_30d = 0

    for ticker, rows in by_ticker.items():
        try:
            earliest = min(
                r["run_date"] if isinstance(r["run_date"], date)
                else date.fromisoformat(str(r["run_date"]))
                for r in rows
            )
            hist = yf.Ticker(ticker).history(
                start=str(earliest + timedelta(days=1)),
                end=str(date.today() + timedelta(days=1)),
                interval="1d",
                auto_adjust=True,
            )
            if hist.empty:
                continue

            closes = hist["Close"].dropna()

            for row in rows:
                run_dt = (
                    row["run_date"] if isinstance(row["run_date"], date)
                    else date.fromisoformat(str(row["run_date"]))
                )
                entry = float(row["entry_price"])
                if entry <= 0:
                    continue

                future = closes[closes.index.normalize() > pd.Timestamp(run_dt)]
                updates: dict = {}

                if row["price_5d"] is None and len(future) >= 5:
                    p5 = float(future.iloc[4])
                    updates["price_5d"]      = p5
                    updates["return_5d_pct"] = round((p5 - entry) / entry * 100, 2)

                if row["price_30d"] is None and len(future) >= 21:
                    p30 = float(future.iloc[20])
                    updates["price_30d"]      = p30
                    updates["return_30d_pct"] = round((p30 - entry) / entry * 100, 2)

                if not updates:
                    continue

                set_clause = ", ".join(f"{k} = %s" for k in updates)
                vals = list(updates.values()) + [row["id"]]
                try:
                    with get_db() as conn2:
                        with conn2.cursor() as cur2:
                            cur2.execute(
                                f"UPDATE backtest_picks SET {set_clause} WHERE id = %s",
                                vals,
                            )
                    if "return_5d_pct" in updates:
                        filled_5d += 1
                    if "return_30d_pct" in updates:
                        filled_30d += 1
                except Exception as exc:
                    _log.getLogger(__name__).warning("fill update %s: %s", ticker, exc)

        except Exception as exc:
            _log.getLogger(__name__).warning("fill_backtest_returns %s: %s", ticker, exc)

    return {"filled_5d": filled_5d, "filled_30d": filled_30d}


# ---------------------------------------------------------------------------
# Historical backtest persistence
# ---------------------------------------------------------------------------

def save_hist_backtest(run_id: str, result: dict) -> None:
    """Persist a historical backtest result (meta + last 60 picks) to DB."""
    s5  = result.get("stats_5d",  {})
    s21 = result.get("stats_21d", {})
    a5  = result.get("alpha_5d",  {})
    a21 = result.get("alpha_21d", {})
    opt = result.get("optimization_result") or {}

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO hist_backtest_meta
              (run_id, universe, years_back, top_n, n_evaluations, n_picks_total,
               avg_return_5d, win_rate_5d, sharpe_5d, avg_alpha_5d,
               avg_return_21d, win_rate_21d, sharpe_21d, avg_alpha_21d,
               optimal_weights, in_sample_avg, out_sample_avg,
               in_sample_sharpe, out_sample_sharpe)
            VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
              n_evaluations     = EXCLUDED.n_evaluations,
              n_picks_total     = EXCLUDED.n_picks_total,
              avg_return_5d     = EXCLUDED.avg_return_5d,
              win_rate_5d       = EXCLUDED.win_rate_5d,
              sharpe_5d         = EXCLUDED.sharpe_5d,
              avg_alpha_5d      = EXCLUDED.avg_alpha_5d,
              avg_return_21d    = EXCLUDED.avg_return_21d,
              win_rate_21d      = EXCLUDED.win_rate_21d,
              sharpe_21d        = EXCLUDED.sharpe_21d,
              avg_alpha_21d     = EXCLUDED.avg_alpha_21d,
              optimal_weights   = EXCLUDED.optimal_weights,
              in_sample_avg     = EXCLUDED.in_sample_avg,
              out_sample_avg    = EXCLUDED.out_sample_avg,
              in_sample_sharpe  = EXCLUDED.in_sample_sharpe,
              out_sample_sharpe = EXCLUDED.out_sample_sharpe,
              created_at        = NOW()
        """, (
            run_id,
            psycopg2.extras.Json(result.get("universe", [])),
            result.get("years_back", 2), result.get("top_n", 5),
            result.get("n_evaluations", 0), result.get("n_picks_total", 0),
            s5.get("avg"), s5.get("win_rate"), s5.get("sharpe"), a5.get("avg"),
            s21.get("avg"), s21.get("win_rate"), s21.get("sharpe"), a21.get("avg"),
            psycopg2.extras.Json(result.get("optimal_weights")),
            opt.get("in_sample_avg"), opt.get("out_sample_avg"),
            opt.get("in_sample_sharpe"), opt.get("out_sample_sharpe"),
        ))

        for p in result.get("picks", []):
            cur.execute("""
                INSERT INTO hist_backtest_runs
                  (run_id, eval_date, ticker, rank, score, entry_price,
                   return_5d, return_21d, return_63d, alpha_5d, alpha_21d, factors)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (run_id, eval_date, ticker) DO NOTHING
            """, (
                run_id, p["eval_date"], p["ticker"], p["rank"], p["score"], p["entry"],
                p.get("return_5d"), p.get("return_21d"), p.get("return_63d"),
                p.get("alpha_5d"), p.get("alpha_21d"),
                psycopg2.extras.Json(p.get("factors", {})),
            ))


def get_hist_backtest_latest() -> dict | None:
    """Return the most recent historical backtest meta + sample picks."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM hist_backtest_meta ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            return None
        meta = dict(row)
        run_id = meta["run_id"]

        cur.execute("""
            SELECT * FROM hist_backtest_runs
            WHERE run_id = %s
            ORDER BY eval_date DESC, rank ASC
            LIMIT 60
        """, (run_id,))
        picks = []
        for r in cur.fetchall():
            p = dict(r)
            if hasattr(p.get("eval_date"), "isoformat"):
                p["eval_date"] = p["eval_date"].isoformat()
            for k in ("created_at",):
                if hasattr(p.get(k), "isoformat"):
                    p[k] = p[k].isoformat()
            picks.append(p)

        if hasattr(meta.get("created_at"), "isoformat"):
            meta["created_at"] = meta["created_at"].isoformat()

        meta["picks"] = picks
        return meta


def get_optimal_weights() -> dict | None:
    """Return optimal factor weights from the most recent historical backtest, if < 30 days old."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT optimal_weights, created_at
                    FROM hist_backtest_meta
                    WHERE optimal_weights IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                """)
                row = cur.fetchone()
        if not row:
            return None
        age_days = (datetime.utcnow() - row["created_at"].replace(tzinfo=None)).days
        if age_days > 30:
            return None
        w = row["optimal_weights"]
        return w if isinstance(w, dict) else None
    except Exception:
        return None


def get_track_record_scores(min_picks: int = 3, lookback_days: int = 90) -> dict:
    """
    Return per-ticker track record based on logged picks that have 5-day forward returns.
    Dict maps ticker → {"win_rate": float, "avg_return": float, "n": int}
    Only tickers with >= min_picks data points are included.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT ticker,
                           COUNT(*)                                   AS n,
                           AVG(return_5d_pct)                         AS avg_return,
                           SUM(CASE WHEN return_5d_pct > 0 THEN 1 ELSE 0 END)::float
                             / COUNT(*)                               AS win_rate
                    FROM backtest_picks
                    WHERE return_5d_pct IS NOT NULL
                      AND run_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
                    GROUP BY ticker
                    HAVING COUNT(*) >= %s
                """, (lookback_days, min_picks))
                rows = cur.fetchall()
        return {
            r["ticker"]: {
                "win_rate":   float(r["win_rate"]),
                "avg_return": float(r["avg_return"]),
                "n":          int(r["n"]),
            }
            for r in rows
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------

def get_watchlist(user_id: int) -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM watchlists WHERE user_id = %s ORDER BY added_at DESC",
            (user_id,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def add_watchlist_item(user_id: int, ticker: str, notes: str = "") -> dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """INSERT INTO watchlists (user_id, ticker, notes)
               VALUES (%s, %s, %s)
               ON CONFLICT (user_id, ticker) DO UPDATE SET notes = EXCLUDED.notes
               RETURNING *""",
            (user_id, ticker.upper(), notes),
        )
        return dict(cur.fetchone())


def remove_watchlist_item(user_id: int, ticker: str) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM watchlists WHERE user_id = %s AND ticker = %s",
            (user_id, ticker.upper()),
        )
        return cur.rowcount > 0


def is_in_watchlist(user_id: int, ticker: str) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM watchlists WHERE user_id = %s AND ticker = %s",
            (user_id, ticker.upper()),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------

def get_digest_subscribers() -> list[dict]:
    """Return all users with digest_enabled=True and a valid email."""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, email, username, full_name FROM users WHERE digest_enabled = TRUE AND is_active = TRUE AND email <> ''",
        )
        return [dict(r) for r in cur.fetchall()]


def set_digest_enabled(user_id: int, enabled: bool) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET digest_enabled = %s WHERE id = %s", (enabled, user_id))
        return cur.rowcount > 0


def get_all_watchlist_tickers() -> list[str]:
    """Return all distinct tickers across all watchlists (for digest universe)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT ticker FROM watchlists")
        return [r[0] for r in cur.fetchall()]


def log_digest_run(run_date, st_count: int, lt_count: int, users_sent: int) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO digest_runs (run_date, st_count, lt_count, users_sent)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (run_date) DO UPDATE
               SET st_count=EXCLUDED.st_count, lt_count=EXCLUDED.lt_count,
                   users_sent=EXCLUDED.users_sent, created_at=NOW()""",
            (run_date, st_count, lt_count, users_sent),
        )


# ---------------------------------------------------------------------------
# Saved Portfolio CRUD
# ---------------------------------------------------------------------------

def get_user_portfolio(user_id: int) -> list[dict]:
    """Return the user's saved portfolio holdings."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT ticker, shares::float, avg_cost::float FROM saved_portfolios WHERE user_id = %s ORDER BY ticker",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def save_user_portfolio(user_id: int, holdings: list[dict]) -> None:
    """Replace all holdings for a user atomically."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_portfolios WHERE user_id = %s", (user_id,))
            seen: set[str] = set()
            for h in holdings:
                t = h["ticker"].upper().strip()
                if t in seen:
                    continue
                seen.add(t)
                cur.execute(
                    """INSERT INTO saved_portfolios (user_id, ticker, shares, avg_cost, updated_at)
                       VALUES (%s, %s, %s, %s, NOW())
                       ON CONFLICT (user_id, ticker) DO UPDATE
                         SET shares = EXCLUDED.shares, avg_cost = EXCLUDED.avg_cost, updated_at = NOW()""",
                    (user_id, t, float(h["shares"]), float(h["avg_cost"])),
                )


def remove_portfolio_holding(user_id: int, ticker: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM saved_portfolios WHERE user_id = %s AND ticker = %s",
                (user_id, ticker.upper()),
            )
            return cur.rowcount > 0


def get_all_saved_portfolios() -> list[dict]:
    """Return all users with saved portfolios and their holdings (for daily digest)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT u.id AS user_id, u.email, u.full_name, u.username,
                       sp.ticker, sp.shares::float, sp.avg_cost::float
                FROM saved_portfolios sp
                JOIN users u ON u.id = sp.user_id
                WHERE u.is_active = TRUE AND u.email <> ''
                ORDER BY u.id, sp.ticker
            """)
            rows = cur.fetchall()

    users: dict[int, dict] = {}
    for row in rows:
        uid = row["user_id"]
        if uid not in users:
            users[uid] = {
                "user_id":   uid,
                "email":     row["email"],
                "full_name": row["full_name"],
                "username":  row["username"],
                "holdings":  [],
            }
        users[uid]["holdings"].append({
            "ticker":   row["ticker"],
            "shares":   row["shares"],
            "avg_cost": row["avg_cost"],
        })
    return list(users.values())


# ---------------------------------------------------------------------------
# Price Alert CRUD
# ---------------------------------------------------------------------------

def get_price_alerts(user_id: int) -> list[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM price_alerts WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def create_price_alert(user_id: int, ticker: str, condition: str, target_price=None, note: str = '') -> dict:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO price_alerts (user_id, ticker, condition, target_price, note)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (user_id, ticker.upper(), condition, target_price, note)
            )
            return dict(cur.fetchone())

def delete_price_alert(user_id: int, alert_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM price_alerts WHERE id=%s AND user_id=%s", (alert_id, user_id))
            return cur.rowcount > 0

def toggle_price_alert(user_id: int, alert_id: int, is_active: bool) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE price_alerts SET is_active=%s WHERE id=%s AND user_id=%s", (is_active, alert_id, user_id))
            return cur.rowcount > 0

def get_active_price_alerts() -> list[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT pa.*, u.email, u.full_name FROM price_alerts pa
                   JOIN users u ON u.id = pa.user_id
                   WHERE pa.is_active = TRUE AND pa.triggered_at IS NULL AND u.is_active = TRUE""")
            return [dict(r) for r in cur.fetchall()]

def mark_alert_triggered(alert_id: int) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE price_alerts SET triggered_at=NOW(), is_active=FALSE WHERE id=%s", (alert_id,))


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return a bcrypt hash of the given password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True if password matches the bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Trade Journal ──────────────────────────────────────────────────────────────

def get_trade_journal(user_id: int) -> list[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM trade_journal WHERE user_id = %s
                   ORDER BY entry_date DESC, created_at DESC""",
                (user_id,)
            )
            return [dict(r) for r in cur.fetchall()]


def create_trade(user_id: int, data: dict) -> dict:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Auto-compute realized P&L if exit_price provided
            realized_pnl = None
            realized_pnl_pct = None
            if data.get("exit_price") and data.get("entry_price") and data.get("shares"):
                ep  = float(data["entry_price"])
                xp  = float(data["exit_price"])
                sh  = float(data["shares"])
                direction = data.get("direction", "long")
                if direction == "long":
                    realized_pnl = (xp - ep) * sh
                else:
                    realized_pnl = (ep - xp) * sh
                realized_pnl_pct = round((xp - ep) / ep * 100 * (1 if direction == "long" else -1), 2)

            outcome = data.get("outcome")
            if outcome is None and data.get("exit_price"):
                if realized_pnl and realized_pnl > 0:
                    outcome = "win"
                elif realized_pnl and realized_pnl < 0:
                    outcome = "loss"
                else:
                    outcome = "breakeven"
            elif outcome is None:
                outcome = "open"

            cur.execute(
                """INSERT INTO trade_journal
                   (user_id, ticker, direction, entry_date, exit_date, entry_price,
                    exit_price, shares, setup, notes, outcome, realized_pnl, realized_pnl_pct)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING *""",
                (
                    user_id,
                    data["ticker"].upper().strip(),
                    data.get("direction", "long"),
                    data["entry_date"],
                    data.get("exit_date"),
                    float(data["entry_price"]),
                    float(data["exit_price"]) if data.get("exit_price") else None,
                    float(data["shares"]),
                    data.get("setup", ""),
                    data.get("notes", ""),
                    outcome,
                    realized_pnl,
                    realized_pnl_pct,
                )
            )
            return dict(cur.fetchone())


def update_trade(user_id: int, trade_id: int, data: dict) -> dict | None:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Recompute P&L
            realized_pnl = None
            realized_pnl_pct = None
            if data.get("exit_price") and data.get("entry_price") and data.get("shares"):
                ep  = float(data["entry_price"])
                xp  = float(data["exit_price"])
                sh  = float(data["shares"])
                direction = data.get("direction", "long")
                if direction == "long":
                    realized_pnl = (xp - ep) * sh
                else:
                    realized_pnl = (ep - xp) * sh
                realized_pnl_pct = round((xp - ep) / ep * 100 * (1 if direction == "long" else -1), 2)

            outcome = data.get("outcome")
            if outcome is None and data.get("exit_price"):
                if realized_pnl and realized_pnl > 0:
                    outcome = "win"
                elif realized_pnl and realized_pnl < 0:
                    outcome = "loss"
                else:
                    outcome = "breakeven"
            elif outcome is None:
                outcome = "open"

            cur.execute(
                """UPDATE trade_journal SET
                   ticker=%(ticker)s, direction=%(direction)s, entry_date=%(entry_date)s,
                   exit_date=%(exit_date)s, entry_price=%(entry_price)s, exit_price=%(exit_price)s,
                   shares=%(shares)s, setup=%(setup)s, notes=%(notes)s,
                   outcome=%(outcome)s, realized_pnl=%(realized_pnl)s,
                   realized_pnl_pct=%(realized_pnl_pct)s, updated_at=NOW()
                   WHERE id=%(id)s AND user_id=%(user_id)s
                   RETURNING *""",
                {
                    "ticker": data["ticker"].upper().strip(),
                    "direction": data.get("direction", "long"),
                    "entry_date": data["entry_date"],
                    "exit_date": data.get("exit_date"),
                    "entry_price": float(data["entry_price"]),
                    "exit_price": float(data["exit_price"]) if data.get("exit_price") else None,
                    "shares": float(data["shares"]),
                    "setup": data.get("setup", ""),
                    "notes": data.get("notes", ""),
                    "outcome": outcome,
                    "realized_pnl": realized_pnl,
                    "realized_pnl_pct": realized_pnl_pct,
                    "id": trade_id,
                    "user_id": user_id,
                }
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_trade(user_id: int, trade_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trade_journal WHERE id = %s AND user_id = %s",
                (trade_id, user_id)
            )
            return cur.rowcount > 0
