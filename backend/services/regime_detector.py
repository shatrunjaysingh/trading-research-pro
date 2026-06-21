"""
Market regime detector — classifies current market as BULL/NEUTRAL/BEAR/CRISIS.

Sources:
  - VIX (^VIX): fear gauge
  - SPY vs SMA50 / SMA200: trend filter

Cached for 1 hour so parallel research workers all share the same fetch.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_LOCK  = threading.Lock()
_TTL   = 3600  # 1 hour


def _classify(vix: float, vs50: float, vs200: float) -> tuple[str, float, str, str]:
    """Return (regime, score_multiplier, color, description)."""
    if vix >= 35 or (vix >= 28 and vs50 < -5 and vs200 < -10):
        return "CRISIS", 0.60, "red",    f"VIX {vix:.0f} — extreme fear; reduce risk sharply"
    if vix >= 25 or (vs50 < -3 and vs200 < -5):
        return "BEAR",   0.75, "orange", f"VIX {vix:.0f} — elevated risk; be selective"
    if vix <= 18 and vs50 > 1 and vs200 > 5:
        return "BULL",   1.10, "green",  f"VIX {vix:.0f} — calm market, uptrend intact"
    return     "NEUTRAL", 1.00, "yellow", f"VIX {vix:.0f} — mixed signals; standard caution"


def get_market_regime() -> dict:
    """
    Fetch and classify current market regime. Cached for 1 hour.
    Falls back to NEUTRAL with multiplier=1.0 on any error.
    """
    now = time.time()
    with _LOCK:
        cached = _CACHE.get("regime")
        if cached and now - cached.get("_ts", 0) < _TTL:
            return {k: v for k, v in cached.items() if k != "_ts"}

    try:
        import yfinance as yf

        raw = yf.download(
            ["^VIX", "SPY"],
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        closes = raw["Close"]

        vix_s = closes["^VIX"].dropna()
        spy_s = closes["SPY"].dropna()

        if len(vix_s) < 5 or len(spy_s) < 50:
            raise ValueError("Insufficient data")

        vix = float(vix_s.iloc[-1])
        spy = float(spy_s.iloc[-1])

        sma50  = float(spy_s.iloc[-50:].mean())
        sma200 = float(spy_s.mean()) if len(spy_s) >= 200 else sma50

        vs50  = (spy - sma50)  / sma50  * 100
        vs200 = (spy - sma200) / sma200 * 100

        regime, multiplier, color, description = _classify(vix, vs50, vs200)

        from datetime import datetime, timezone
        result = {
            "regime":           regime,
            "vix":              round(vix, 1),
            "spy_price":        round(spy, 2),
            "spy_vs_sma50":     round(vs50, 1),
            "spy_vs_sma200":    round(vs200, 1),
            "score_multiplier": multiplier,
            "color":            color,
            "description":      description,
            "updated_at":       datetime.now(timezone.utc).isoformat(),
            "_ts":              time.time(),
        }
        with _LOCK:
            _CACHE["regime"] = result

        logger.info("Regime: %s (VIX=%.1f, vs SMA50=%.1f%%, vs SMA200=%.1f%%)",
                    regime, vix, vs50, vs200)
        return {k: v for k, v in result.items() if k != "_ts"}

    except Exception as exc:
        logger.warning("Regime detection failed: %s", exc)
        from datetime import datetime, timezone
        return {
            "regime":           "NEUTRAL",
            "vix":              0.0,
            "spy_price":        0.0,
            "spy_vs_sma50":     0.0,
            "spy_vs_sma200":    0.0,
            "score_multiplier": 1.0,
            "color":            "yellow",
            "description":      "Regime data unavailable — using NEUTRAL defaults",
            "updated_at":       datetime.now(timezone.utc).isoformat(),
        }
