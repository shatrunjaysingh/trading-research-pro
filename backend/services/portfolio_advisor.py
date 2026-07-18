"""
Portfolio Advisor — scores each holding and recommends:
  add_more | hold | reduce | sell

Called both from the API router (on-demand) and from the daily digest (automated).
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

ACTION_LABELS = {
    "add_more": "ADD MORE",
    "hold":     "HOLD",
    "reduce":   "REDUCE",
    "sell":     "SELL",
}

ACTION_COLORS = {
    "add_more": "#16a34a",   # green
    "hold":     "#2563eb",   # blue
    "reduce":   "#d97706",   # amber
    "sell":     "#dc2626",   # red
}


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _recommend_action(
    st_score: float,
    lt_score: float,
    rs_score: float,
    pnl_pct: float | None,
    weight: float,
) -> dict:
    """Return {action, confidence, reasons} for a single holding."""
    reasons: list[str] = []

    # SELL — poor across all dimensions
    if st_score < 35 and lt_score < 38 and rs_score < 40:
        reasons.append(f"Poor momentum across all timeframes (ST: {st_score:.0f}, LT: {lt_score:.0f})")
        reasons.append(f"Significantly underperforming the market (RS: {rs_score})")
        return {"action": "sell", "confidence": "high", "reasons": reasons}

    # SELL — deep loss with no recovery signal
    if pnl_pct is not None and pnl_pct < -20 and st_score < 42:
        reasons.append(f"Down {abs(pnl_pct):.1f}% with deteriorating momentum (ST: {st_score:.0f})")
        reasons.append("Cut losses — no near-term recovery signal detected")
        return {"action": "sell", "confidence": "medium", "reasons": reasons}

    # ADD MORE — high conviction: all signals strong, not overweight
    if st_score >= 70 and lt_score >= 65 and rs_score >= 75 and weight < 20:
        reasons.append(f"Strong momentum across all timeframes (ST: {st_score:.0f}, LT: {lt_score:.0f})")
        reasons.append(f"Outperforming the market strongly (RS: {rs_score})")
        if weight < 8:
            reasons.append("Position is underweight — room to build a larger position")
        return {"action": "add_more", "confidence": "high", "reasons": reasons}

    # ADD MORE — good signals, lighter position
    if st_score >= 65 and lt_score >= 58 and rs_score >= 68 and weight < 15:
        reasons.append(f"Good near-term momentum (ST: {st_score:.0f}) with solid long-term quality (LT: {lt_score:.0f})")
        reasons.append(f"Outperforming SPY (RS: {rs_score}) — trend is in your favour")
        return {"action": "add_more", "confidence": "medium", "reasons": reasons}

    # REDUCE — overweight position (concentration risk)
    if weight > 25:
        reasons.append(f"Oversized position ({weight:.1f}% of portfolio) — concentration risk")
        if pnl_pct is not None and pnl_pct > 15:
            reasons.append(f"Up {pnl_pct:.1f}% — consider taking some profits and rebalancing")
        else:
            reasons.append("Trim to ≤20% to reduce single-stock risk")
        return {"action": "reduce", "confidence": "high", "reasons": reasons}

    # REDUCE — extended gain with fading momentum
    if pnl_pct is not None and pnl_pct > 35 and st_score < 55:
        reasons.append(f"Up {pnl_pct:.1f}% but near-term momentum is fading (ST: {st_score:.0f})")
        reasons.append("Take partial profits — protect gains while momentum is cooling")
        return {"action": "reduce", "confidence": "medium", "reasons": reasons}

    # REDUCE — weakening signals on all axes
    if st_score < 42 and lt_score < 48 and rs_score < 55:
        reasons.append(f"Deteriorating signals (ST: {st_score:.0f}, LT: {lt_score:.0f})")
        reasons.append(f"Underperforming the market (RS: {rs_score}) — trim exposure before signals worsen")
        return {"action": "reduce", "confidence": "medium", "reasons": reasons}

    # HOLD — positive signals
    if st_score >= 55 and lt_score >= 55:
        reasons.append(f"Solid across timeframes (ST: {st_score:.0f}, LT: {lt_score:.0f})")
        reasons.append("Maintain current position — signals support holding")
    elif st_score >= 50 or lt_score >= 50:
        reasons.append(f"Mixed signals (ST: {st_score:.0f}, LT: {lt_score:.0f}) — wait for confirmation before adding")
        reasons.append("Hold and monitor for a clearer breakout or breakdown signal")
    else:
        reasons.append(f"Neutral / borderline signals (ST: {st_score:.0f}, LT: {lt_score:.0f})")
        reasons.append("Monitor closely — set a stop if it breaks below key support")

    return {"action": "hold", "confidence": "medium", "reasons": reasons}


def _score_one_holding(
    holding: dict, spy_returns: dict,
    prior_rows: list[dict] | None = None, universe_stats: dict | None = None,
) -> dict | None:
    """Score a single holding. Returns None on failure.

    `prior_rows` / `universe_stats` are pre-fetched once by the caller so the
    per-holding scoring can be stabilized (smoothing + hysteresis) and ranked
    cross-sectionally — the same engine the stock-analysis page uses.
    """
    ticker = holding["ticker"]
    try:
        from backend.services.rs_rating import compute_rs_rating
        from backend.services.stock_analyzer import (
            _fetch_stock_data, _compute_weekly_confirmation,
            _compute_st_score, _compute_lt_score, _fetch_fundamentals,
        )
        from backend.services import factor_engine as fe
        from backend.services.financial_health import get_financial_health
        from backend.services.signal_stabilizer import stabilize
        import yfinance as yf

        tech_result = _fetch_stock_data(ticker, "3mo", "1d",
                                        ["rsi", "macd", "sma50", "sma200", "volume"])
        if "error" in tech_result or not tech_result.get("technical"):
            return None

        tech  = tech_result["technical"]
        price = _safe(tech.get("current_price"))
        if not price:
            return None

        rs_data  = compute_rs_rating(ticker, spy_returns=spy_returns)
        rs_score = rs_data.get("rs_score", 50)
        weekly   = _compute_weekly_confirmation(ticker)
        st       = _compute_st_score(tech, rs_score, weekly)
        fund     = _fetch_fundamentals(ticker)
        lt       = _compute_lt_score(tech, fund, rs_score) if fund else None

        tk   = yf.Ticker(ticker)
        info = tk.info
        fi   = tk.fast_info
        prev = _safe(fi.previous_close)
        day_chg = round((price - prev) / prev * 100, 2) if price and prev and prev else None

        current_value = price * holding["shares"]
        cost_basis    = holding["avg_cost"] * holding["shares"]
        pnl           = current_value - cost_basis
        pnl_pct       = round(pnl / cost_basis * 100, 2) if cost_basis else None

        # ── Stabilize ST/LT (no day-to-day flip-flop) ─────────────────────────
        row = stabilize(
            prior_rows or [],
            {"tech": tech.get("raw_score", 50.0),
             "st": st["score"], "lt": lt["score"] if lt else None},
            {"tech": tech.get("agreement", 0.5)},
        )
        st_score  = row["st_smoothed"] if row.get("st_smoothed") is not None else st["score"]
        st_signal = row["st_signal"] or st["signal"]
        lt_score  = row.get("lt_smoothed") if lt else None
        lt_signal = row.get("lt_signal") if lt else None

        # ── Cross-sectional factor decomposition + financial health ───────────
        health = {}
        factor_analysis = None
        try:
            health = get_financial_health(ticker)
            analyst_min = {
                "upside_pct": (round((_safe(info.get("targetMeanPrice")) - price) / price * 100, 1)
                               if _safe(info.get("targetMeanPrice")) and price else None),
                "recommendation_mean": _safe(info.get("recommendationMean")),
            }
            data = fe.merge_factor_data(tech, fund, analyst_min, rs_score)
            data.update({k: v for k, v in health.items() if v is not None})
            factor_analysis = fe.analyze(data, universe_stats=universe_stats)
        except Exception:
            pass

        return {
            "ticker":        ticker,
            "company":       info.get("shortName") or info.get("longName") or ticker,
            "sector":        info.get("sector") or "Unknown",
            "shares":        holding["shares"],
            "avg_cost":      holding["avg_cost"],
            "current_price": price,
            "day_change_pct": day_chg,
            "current_value": round(current_value, 2),
            "cost_basis":    round(cost_basis, 2),
            "pnl":           round(pnl, 2),
            "pnl_pct":       pnl_pct,
            "weight":        0.0,  # filled in after we know total value
            "rs_score":      rs_score,
            "st_score":      st_score,
            "st_signal":     st_signal,
            "lt_score":      lt_score,
            "lt_signal":     lt_signal,
            "beta":          _safe(info.get("beta")) or 1.0,
            "earnings_soon": False,
            "factor_analysis":  factor_analysis,
            "financial_health": health or None,
            "_signal_row":   {"ticker": ticker, **row},
        }
    except Exception as exc:
        logger.debug("Portfolio advisor failed for %s: %s", ticker, exc)
        return None


def analyze_saved_portfolio(user_id: int) -> dict:
    """
    Score all holdings in the user's saved portfolio and produce
    per-holding recommendations + portfolio-level health summary.
    """
    import database as db
    from backend.services.rs_rating import fetch_spy_returns

    holdings = db.get_user_portfolio(user_id)
    if not holdings:
        return {"error": "No saved portfolio found", "holdings": [], "summary": None}

    spy_returns = fetch_spy_returns()

    # Pre-fetch signal history + the latest universe distribution ONCE (main
    # thread) so worker threads stay off the DB and every holding is stabilized
    # + ranked with the same engine the stock-analysis page uses.
    from datetime import date
    today = date.today()
    tickers = [h["ticker"] for h in holdings]
    try:
        history_map = db.get_recent_signal_history_bulk(tickers, lookback_days=10, before=today)
    except Exception:
        history_map = {}
    try:
        uni = db.get_latest_factor_universe_stats()
        universe_stats = (uni or {}).get("stats")
    except Exception:
        universe_stats = None

    # Score all holdings in parallel
    scored: list[dict] = []
    errors: list[dict] = []

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {
            ex.submit(_score_one_holding, h, spy_returns,
                      history_map.get(h["ticker"].upper()), universe_stats): h
            for h in holdings
        }
        for f in as_completed(futures):
            h = futures[f]
            result = f.result()
            if result:
                scored.append(result)
            else:
                errors.append({
                    "ticker":   h["ticker"],
                    "shares":   h["shares"],
                    "avg_cost": h["avg_cost"],
                    "error":    "Could not score this ticker",
                })

    # Persist today's stabilized signal rows in one batch.
    try:
        rows = [s["_signal_row"] for s in scored if s.get("_signal_row")]
        if rows:
            db.upsert_signal_history_bulk([{"as_of": today, **r} for r in rows])
    except Exception as exc:
        logger.warning("Portfolio signal_history upsert failed: %s", exc)
    for s in scored:
        s.pop("_signal_row", None)

    # Compute portfolio weights
    total_value = sum(h["current_value"] for h in scored)
    for h in scored:
        h["weight"] = round(h["current_value"] / total_value * 100, 2) if total_value else 0.0

    # Apply action recommendations
    for h in scored:
        advice = _recommend_action(
            st_score = h["st_score"],
            lt_score = h["lt_score"] or 50,
            rs_score = h["rs_score"],
            pnl_pct  = h["pnl_pct"],
            weight   = h["weight"],
        )
        h["action"]          = advice["action"]
        h["action_label"]    = ACTION_LABELS[advice["action"]]
        h["action_color"]    = ACTION_COLORS[advice["action"]]
        h["action_confidence"] = advice["confidence"]
        h["action_reasons"]  = advice["reasons"]

        # Check if earnings are within 7 days
        ticker = h["ticker"]
        try:
            import yfinance as yf
            cal = yf.Ticker(ticker).calendar
            earn_date = None
            if isinstance(cal, dict):
                earn_date = cal.get("Earnings Date")
                if isinstance(earn_date, list) and earn_date:
                    earn_date = earn_date[0]
            elif hasattr(cal, 'columns') and not cal.empty:
                if "Earnings Date" in cal.columns:
                    earn_date = cal["Earnings Date"].iloc[0]
            if earn_date is not None:
                import pandas as pd
                from datetime import datetime, timezone
                if hasattr(earn_date, 'to_pydatetime'):
                    earn_date = earn_date.to_pydatetime()
                if earn_date.tzinfo is None:
                    earn_date = earn_date.replace(tzinfo=timezone.utc)
                days_out = (earn_date - datetime.now(timezone.utc)).days
                if 0 <= days_out <= 7:
                    h["action_reasons"].append(f"⚠️ Earnings in {days_out} day{'s' if days_out != 1 else ''} — elevated event risk")
                    h["earnings_soon"] = True
                    h["earnings_days_out"] = days_out
        except Exception:
            pass

    # Sort: sells first (need attention), then add_more, then reduce, then hold
    action_order = {"sell": 0, "add_more": 1, "reduce": 2, "hold": 3}
    scored.sort(key=lambda h: action_order.get(h["action"], 9))

    # Portfolio health score — weighted average of ST scores
    health_score = 0.0
    if scored and total_value:
        health_score = sum(
            h["st_score"] * (h["weight"] / 100) for h in scored
        )
        health_score = round(health_score, 1)

    # Counts
    action_counts = {a: 0 for a in ACTION_LABELS}
    for h in scored:
        action_counts[h["action"]] = action_counts.get(h["action"], 0) + 1

    # Top recommendation
    sells    = [h for h in scored if h["action"] == "sell"]
    adds     = [h for h in scored if h["action"] == "add_more"]
    reduces  = [h for h in scored if h["action"] == "reduce"]

    if sells:
        top_rec = f"Exit {', '.join(h['ticker'] for h in sells[:2])} — poor momentum and market underperformance"
    elif adds:
        top_rec = f"Consider adding to {', '.join(h['ticker'] for h in adds[:2])} — strong across all timeframes"
    elif reduces:
        top_rec = f"Trim {', '.join(h['ticker'] for h in reduces[:2])} — manage risk or protect profits"
    else:
        top_rec = "Portfolio looks balanced — hold current positions and monitor signals"

    total_cost = sum(h["cost_basis"] for h in scored)
    total_pnl  = sum(h["pnl"] for h in scored)
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost else None

    # ── Portfolio-level risk analytics (beta, concentration, correlation, VaR) ──
    risk = None
    try:
        from backend.services.portfolio_risk import analyze_portfolio_risk
        risk = analyze_portfolio_risk(scored)
    except Exception as exc:
        logger.warning("Portfolio risk analysis failed: %s", exc)

    return {
        "holdings": scored + errors,
        "summary": {
            "total_value":    round(total_value, 2),
            "total_cost":     round(total_cost, 2),
            "total_pnl":      round(total_pnl, 2),
            "total_pnl_pct":  total_pnl_pct,
            "health_score":   health_score,
            "top_recommendation": top_rec,
            "action_counts":  action_counts,
            "num_holdings":   len(scored),
        },
        "risk": risk,
    }
