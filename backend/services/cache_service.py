"""
Enterprise two-tier analysis cache.

L1  — in-process dict (per-worker, fast, cleared on restart)
L2  — PostgreSQL analysis_cache table (persistent, shared across workers)

TTL strategy:
  api mode : 4 h during market hours / 12 h outside
  free mode: 2 h during market hours /  6 h outside
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── L1 in-process cache ───────────────────────────────────────────────────────
_L1: dict[str, dict[str, Any]] = {}
_L1_MAX = 100


# ── TTL helpers ───────────────────────────────────────────────────────────────

def _market_open() -> bool:
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except ImportError:
        import pytz
        et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    return (now.hour > 9 or (now.hour == 9 and now.minute >= 30)) and now.hour < 16


def _ttl(mode: str) -> int:
    if mode == "api":
        return 4 * 3600 if _market_open() else 12 * 3600
    return 2 * 3600 if _market_open() else 6 * 3600


# ── Cache key ─────────────────────────────────────────────────────────────────

def make_cache_key(
    ticker: str,
    mode: str,
    time_period: str,
    indicators: list[str],
    rsi_period: int,
    bb_period: int,
    bb_std: float,
    macd_fast: int,
    macd_slow: int,
    macd_signal_period: int,
    include_news: bool,
    include_fundamentals: bool,
    include_peers: bool,
) -> str:
    raw = json.dumps({
        "t":  ticker.upper(),
        "m":  mode,
        "p":  time_period,
        "i":  sorted(indicators),
        "r":  rsi_period,
        "b":  bb_period,
        "bs": bb_std,
        "mf": macd_fast,
        "ms": macd_slow,
        "mg": macd_signal_period,
        "n":  include_news,
        "f":  include_fundamentals,
        "pe": include_peers,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ── L1 helpers ────────────────────────────────────────────────────────────────

def _l1_evict_oldest() -> None:
    if len(_L1) >= _L1_MAX:
        oldest = min(_L1, key=lambda k: _L1[k]["exp"])
        _L1.pop(oldest, None)


def _l1_set(key: str, result: dict, exp: datetime) -> None:
    _l1_evict_oldest()
    _L1[key] = {"result": result, "exp": exp}


def _l1_get(key: str) -> dict | None:
    entry = _L1.get(key)
    if entry and entry["exp"] > datetime.now(timezone.utc):
        return entry["result"]
    _L1.pop(key, None)
    return None


# ── Cache annotation ──────────────────────────────────────────────────────────

def _annotate(result: dict) -> dict:
    """Return a copy of result with cached=True and cache_age_seconds injected."""
    out = dict(result)
    out["cached"] = True
    cached_at = result.get("cached_at")
    if cached_at:
        try:
            dt = datetime.fromisoformat(cached_at)
            out["cache_age_seconds"] = int((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            out["cache_age_seconds"] = None
    return out


def _db_bump_hits(cache_key: str) -> None:
    try:
        from database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE analysis_cache SET hit_count = hit_count + 1, last_hit_at = NOW() WHERE cache_key = %s",
                (cache_key,),
            )
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def cache_get(cache_key: str) -> dict | None:
    """Return annotated cached result or None on miss/expiry."""
    # L1 fast path
    hit = _l1_get(cache_key)
    if hit:
        _db_bump_hits(cache_key)
        return _annotate(hit)

    # L2 PostgreSQL
    try:
        from database import get_db
        import psycopg2.extras
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT result_json, expires_at
                   FROM analysis_cache
                   WHERE cache_key = %s AND expires_at > NOW()""",
                (cache_key,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """UPDATE analysis_cache
                       SET hit_count = hit_count + 1, last_hit_at = NOW()
                       WHERE cache_key = %s""",
                    (cache_key,),
                )
                result = json.loads(row["result_json"])
                _l1_set(cache_key, result, row["expires_at"])
                return _annotate(result)
    except Exception as exc:
        logger.warning("Cache L2 read error: %s", exc)

    return None


def cache_set(cache_key: str, ticker: str, mode: str, result: dict) -> None:
    """Write to L1 and L2, stamping cached_at on the stored payload."""
    now = datetime.now(timezone.utc)
    stored = {**result, "cached_at": now.isoformat()}
    exp = now + timedelta(seconds=_ttl(mode))

    _l1_set(cache_key, stored, exp)

    try:
        from database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO analysis_cache
                     (cache_key, ticker, mode, result_json, expires_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (cache_key) DO UPDATE SET
                     result_json = EXCLUDED.result_json,
                     expires_at  = EXCLUDED.expires_at,
                     created_at  = NOW(),
                     hit_count   = 0,
                     last_hit_at = NULL""",
                (cache_key, ticker.upper(), mode, json.dumps(stored), exp),
            )
    except Exception as exc:
        logger.warning("Cache L2 write error: %s", exc)


def cache_invalidate(ticker: str | None = None, mode: str | None = None) -> int:
    """Purge cache entries. Returns number of DB rows deleted."""
    to_del = []
    for k, v in _L1.items():
        r = v["result"]
        if ticker and r.get("ticker", "").upper() != ticker.upper():
            continue
        if mode and r.get("mode") != mode:
            continue
        to_del.append(k)
    for k in to_del:
        _L1.pop(k, None)

    try:
        from database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            if ticker and mode:
                cur.execute(
                    "DELETE FROM analysis_cache WHERE ticker = %s AND mode = %s",
                    (ticker.upper(), mode),
                )
            elif ticker:
                cur.execute("DELETE FROM analysis_cache WHERE ticker = %s", (ticker.upper(),))
            elif mode:
                cur.execute("DELETE FROM analysis_cache WHERE mode = %s", (mode,))
            else:
                cur.execute("DELETE FROM analysis_cache")
            return cur.rowcount
    except Exception as exc:
        logger.warning("Cache invalidation error: %s", exc)
        return 0


def cache_stats() -> dict:
    """Return cache statistics for admin dashboards."""
    try:
        from database import get_db
        import psycopg2.extras
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT
                    COUNT(*)                                      AS total_entries,
                    COUNT(*) FILTER (WHERE expires_at > NOW())   AS active_entries,
                    COALESCE(SUM(hit_count), 0)                  AS total_hits,
                    MIN(created_at)                              AS oldest_entry,
                    MAX(created_at)                              AS newest_entry
                FROM analysis_cache
            """)
            stats = dict(cur.fetchone())
            cur.execute("""
                SELECT ticker, mode, SUM(hit_count) AS hits, COUNT(*) AS entries
                FROM analysis_cache
                WHERE expires_at > NOW()
                GROUP BY ticker, mode
                ORDER BY hits DESC
                LIMIT 10
            """)
            stats["top_tickers"] = [dict(r) for r in cur.fetchall()]
            stats["l1_size"] = len(_L1)
            for key in ("oldest_entry", "newest_entry"):
                val = stats.get(key)
                if val and hasattr(val, "isoformat"):
                    stats[key] = val.isoformat()
            return stats
    except Exception as exc:
        return {"error": str(exc), "l1_size": len(_L1)}
