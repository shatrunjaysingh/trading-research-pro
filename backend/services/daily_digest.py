"""
Daily digest — screens S&P 100 + user watchlists every morning.
Produces top 5 short-term and top 5 long-term picks and emails all subscribed users.
"""

import logging
from datetime import datetime, timezone, date
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# S&P 100 — 100 most liquid US large-caps (stable universe for screening)
SP100 = [
    "AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","JPM","LLY","UNH",
    "JNJ","XOM","V","PG","MA","AVGO","HD","CVX","MRK","ABBV","COST","CRM",
    "PEP","BAC","ACN","WMT","MCD","ORCL","NFLX","KO","ADBE","TMO","CSCO",
    "WFC","ABT","PM","DHR","VZ","QCOM","IBM","TXN","NEE","MS","GS","SPGI",
    "AXP","CAT","BLK","AMGN","SYK","HON","GILD","RTX","LMT","C","LOW",
    "AMAT","INTU","T","DE","NOW","ISRG","ELV","BDX","VRTX","MMC","REGN",
    "ICE","PGR","SHW","KLAC","BSX","ZTS","SO","CME","TJX","FI","CL","EOG",
    "GE","DUK","NOC","APD","HUM","AON","CI","MCO","TDG","SLB","WELL","PH",
    "ITW","EW","GD","MMM","F","GM","SBUX","PYPL",
]


def _score_ticker_for_digest(ticker: str, spy_returns: dict) -> dict | None:
    """Score a single ticker. Returns None on failure."""
    try:
        import yfinance as yf
        from backend.services.rs_rating import compute_rs_rating
        from backend.services.stock_analyzer import (
            _fetch_stock_data, _compute_weekly_confirmation,
            _compute_st_score, _compute_lt_score, _fetch_fundamentals,
        )

        # Technical (3m daily — same as main scorer)
        tech_result = _fetch_stock_data(
            ticker, "3mo", "1d",
            ["rsi", "macd", "sma50", "sma200", "volume"],
        )
        if "error" in tech_result or not tech_result.get("technical"):
            return None

        tech = tech_result["technical"]
        price = tech.get("current_price")
        if not price or price < 0.5:  # skip penny stocks for digest
            return None

        # RS rating (reuse pre-fetched SPY returns)
        rs_data = compute_rs_rating(ticker, spy_returns=spy_returns)
        rs_score = rs_data.get("rs_score", 50)

        # Weekly confirmation
        weekly = _compute_weekly_confirmation(ticker)

        # ST score
        st = _compute_st_score(tech, rs_score, weekly)

        # LT score (needs fundamentals)
        fund = _fetch_fundamentals(ticker)
        lt = _compute_lt_score(tech, fund, rs_score) if fund else None

        company = (fund or {}).get("company_name") or ticker

        return {
            "ticker":        ticker,
            "company":       company,
            "price":         price,
            "day_change_pct": tech.get("day_change_pct"),
            "rs_score":      rs_score,
            "st_score":      st["score"],
            "st_signal":     st["signal"],
            "st_reasoning":  st["reasoning"],
            "lt_score":      lt["score"]  if lt else None,
            "lt_signal":     lt["signal"] if lt else None,
            "lt_reasoning":  lt["reasoning"] if lt else [],
        }
    except Exception as exc:
        logger.debug("Digest scoring failed for %s: %s", ticker, exc)
        return None


def run_daily_digest(force: bool = False) -> dict:
    """
    Run the full daily screening and email all subscribed users.
    Pass force=True to run on weekends / off-hours (e.g. for testing).
    Returns summary of what was sent.
    """
    logger.info("Daily digest starting… (force=%s)", force)
    today = date.today()

    # Skip weekends unless forced
    if not force and today.weekday() >= 5:
        logger.info("Weekend — skipping daily digest")
        return {"skipped": True, "reason": "weekend"}

    try:
        import database as db

        # Fetch SPY returns once — reuse across all tickers
        from backend.services.rs_rating import fetch_spy_returns
        spy_returns = fetch_spy_returns()

        # Build universe: S&P 100 + all watchlist tickers
        watchlist_tickers: list[str] = []
        try:
            all_wl = db.get_all_watchlist_tickers()
            watchlist_tickers = list(set(all_wl) - set(SP100))
        except Exception:
            pass

        universe = list(set(SP100 + watchlist_tickers))
        logger.info("Screening %d tickers…", len(universe))

        # Score all tickers in parallel (max 20 workers)
        scored: list[dict] = []
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(_score_ticker_for_digest, t, spy_returns): t for t in universe}
            for f in as_completed(futures):
                result = f.result()
                if result:
                    scored.append(result)

        logger.info("Scored %d/%d tickers successfully", len(scored), len(universe))

        # Top 5 short-term: high ST score + RS > 65 + positive day change preferred
        st_eligible = [
            s for s in scored
            if s["st_score"] >= 60 and s.get("rs_score", 0) >= 65
        ]
        st_eligible.sort(key=lambda x: x["st_score"] * 0.6 + x["rs_score"] * 0.4, reverse=True)
        top_st = st_eligible[:5]

        # Top 5 long-term: high LT score + RS > 60
        lt_eligible = [
            s for s in scored
            if s.get("lt_score") is not None and s["lt_score"] >= 60 and s.get("rs_score", 0) >= 60
        ]
        lt_eligible.sort(key=lambda x: (x["lt_score"] or 0) * 0.5 + x["rs_score"] * 0.5, reverse=True)
        top_lt = lt_eligible[:5]

        logger.info("ST picks: %s", [p["ticker"] for p in top_st])
        logger.info("LT picks: %s", [p["ticker"] for p in top_lt])

        # Build email picks list
        email_picks = (
            [{"horizon": "short", "signal": p["st_signal"], "score": p["st_score"],
              "reasoning": p["st_reasoning"], **{k: p[k] for k in ("ticker","company","price","day_change_pct","rs_score")}}
             for p in top_st]
            +
            [{"horizon": "long", "signal": p["lt_signal"] or "watch", "score": p.get("lt_score", 50),
              "reasoning": p["lt_reasoning"], **{k: p[k] for k in ("ticker","company","price","day_change_pct","rs_score")}}
             for p in top_lt]
        )

        # Build per-user portfolio analyses in advance (only for users with saved portfolios)
        from backend.services.portfolio_advisor import analyze_saved_portfolio
        all_saved_portfolios: dict[int, list[dict]] = {}
        try:
            portfolios_list = db.get_all_saved_portfolios()
            logger.info("Found %d users with saved portfolios", len(portfolios_list))
            for p_user in portfolios_list:
                uid = p_user["user_id"]
                try:
                    analysis = analyze_saved_portfolio(uid)
                    if analysis.get("holdings"):
                        all_saved_portfolios[uid] = analysis["holdings"]
                except Exception as exc:
                    logger.warning("Portfolio analysis failed for user %d: %s", uid, exc)
        except Exception as exc:
            logger.warning("Could not load saved portfolios: %s", exc)

        # Send to all subscribed users
        from backend.services.email_service import send_email, build_digest_html
        from backend.config import settings
        date_str = today.strftime("%A, %B %-d, %Y")
        users_sent = 0
        email_configured = bool(settings.email_sender and settings.email_app_password)

        try:
            subscribed = db.get_digest_subscribers()
        except Exception:
            subscribed = []

        # Also include addresses from the admin-managed email list
        try:
            extra_emails = [e for e in db.get_digest_email_list() if e.get("is_active")]
        except Exception:
            extra_emails = []

        # Merge: use a set to avoid duplicate sends
        seen_emails: set[str] = set()
        all_recipients: list[dict] = []
        for u in subscribed:
            e = (u.get("email") or "").lower()
            if e and e not in seen_emails:
                seen_emails.add(e)
                all_recipients.append({"email": u["email"], "name": u.get("full_name") or u.get("username") or "Trader", "user_id": u.get("id")})
        for e in extra_emails:
            addr = (e.get("email") or "").lower()
            if addr and addr not in seen_emails:
                seen_emails.add(addr)
                all_recipients.append({"email": e["email"], "name": e.get("name") or "Trader", "user_id": None})

        for recipient in all_recipients:
            try:
                user_portfolio = all_saved_portfolios.get(recipient.get("user_id")) if recipient.get("user_id") else None
                html = build_digest_html(
                    picks=email_picks,
                    user_name=recipient["name"],
                    date_str=date_str,
                    portfolio_holdings=user_portfolio,
                )
                ok = send_email(
                    to_email=recipient["email"],
                    subject=f"📈 TradingResearch Daily — Top picks for {today.strftime('%b %-d')}",
                    html_body=html,
                )
                if ok:
                    users_sent += 1
            except Exception as exc:
                logger.error("Failed to send digest to %s: %s", recipient.get("email"), exc)

        # Log to DB
        try:
            db.log_digest_run(today, len(top_st), len(top_lt), users_sent)
        except Exception:
            pass

        return {
            "date": str(today),
            "st_picks": [p["ticker"] for p in top_st],
            "lt_picks": [p["ticker"] for p in top_lt],
            "users_sent": users_sent,
            "recipients_found": len(all_recipients),
            "email_configured": email_configured,
            "universe_size": len(universe),
            "scored": len(scored),
        }

    except Exception as exc:
        logger.error("Daily digest failed: %s", exc)
        return {"error": str(exc)}
