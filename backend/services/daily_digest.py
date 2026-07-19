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


def _score_ticker_for_digest(
    ticker: str, spy_returns: dict, prior_rows: list[dict] | None = None,
    asset_type: str = "stock",
) -> dict | None:
    """Score a single ticker (stock, penny stock, or crypto). Returns None on fail.

    `asset_type` = "stock" | "penny" | "crypto". Crypto symbols are mapped to the
    yfinance `-USD` form for all fetches while the display ticker stays clean, and
    the penny-price filter is skipped for crypto (whose prices can be tiny).

    `prior_rows` is this ticker's stored signal history (most-recent-first),
    pre-fetched in the main thread so workers never touch the DB. The raw ST/LT
    scores are smoothed + hysteresis-gated against that history so the digest's
    picks stop churning day to day. The stabilized row is returned under
    `_signal_row` for the caller to persist in one batch.
    """
    try:
        import yfinance as yf
        from backend.services.rs_rating import compute_rs_rating
        from backend.services.stock_analyzer import (
            _fetch_stock_data, _compute_weekly_confirmation,
            _compute_st_score, _compute_lt_score, _fetch_fundamentals,
        )
        from backend.services.signal_stabilizer import stabilize

        # yfinance symbol (crypto needs the -USD suffix); display ticker stays clean.
        yf_sym = f"{ticker}-USD" if asset_type == "crypto" else ticker

        # Technical (3m daily — same as main scorer)
        tech_result = _fetch_stock_data(
            yf_sym, "3mo", "1d",
            ["rsi", "macd", "sma50", "sma200", "volume"],
        )
        if "error" in tech_result or not tech_result.get("technical"):
            return None

        tech = tech_result["technical"]
        price = tech.get("current_price")
        if not price:
            return None
        if asset_type == "stock" and price < 0.5:   # only large-caps skip sub-$0.50
            return None

        # RS rating (reuse pre-fetched SPY returns)
        rs_data = compute_rs_rating(yf_sym, spy_returns=spy_returns)
        rs_score = rs_data.get("rs_score", 50)

        # Weekly confirmation
        weekly = _compute_weekly_confirmation(yf_sym)

        # ST score
        st = _compute_st_score(tech, rs_score, weekly)

        # Fundamentals + LT score (crypto has none → LT stays None)
        fund = None if asset_type == "crypto" else _fetch_fundamentals(yf_sym)
        lt = _compute_lt_score(tech, fund, rs_score) if fund else None

        company = (fund or {}).get("company_name") or ticker

        # Stabilize raw ST/LT scores against stored history (pure, no DB here).
        row = stabilize(
            prior_rows or [],
            {"tech": tech.get("raw_score", 50.0), "st": st["score"],
             "lt": lt["score"] if lt else None},
            {"tech": tech.get("agreement", 0.5)},
        )
        st_score = row["st_smoothed"] if row.get("st_smoothed") is not None else st["score"]
        st_signal = row["st_signal"] or st["signal"]
        lt_score = row.get("lt_smoothed") if lt else None
        lt_signal = row.get("lt_signal") if lt else None

        # Raw factor exposures + financial health (stocks only) for cross-sectional
        # ranking + the composite/guardrails computed by the caller.
        from backend.services.factor_engine import merge_factor_data, compute_exposures
        from backend.services.financial_health import get_financial_health
        fdata = merge_factor_data(tech, fund, None, rs_score)
        if asset_type != "crypto":
            try:
                fdata.update({k: v for k, v in get_financial_health(yf_sym).items() if v is not None})
            except Exception:
                pass
        exposures = compute_exposures(fdata)

        return {
            "ticker":        ticker,
            "asset_type":    asset_type,
            "company":       company,
            "price":         price,
            "day_change_pct": tech.get("day_change_pct"),
            "rs_score":      rs_score,
            "st_score":      st_score,
            "st_signal":     st_signal,
            "st_reasoning":  st["reasoning"],
            "lt_score":      lt_score if lt else None,
            "lt_signal":     lt_signal if lt else None,
            "lt_reasoning":  lt["reasoning"] if lt else [],
            "_signal_row":   {"ticker": ticker, **row},
            "_exposures":    exposures,
            "_fdata":        fdata,
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
        def _valid_ticker(t: str) -> bool:
            import re
            return bool(t and re.match(r'^[A-Z]{1,5}$', t.strip()))

        watchlist_tickers: list[str] = []
        try:
            all_wl = db.get_all_watchlist_tickers()
            watchlist_tickers = [t for t in set(all_wl) - set(SP100) if _valid_ticker(t)]
        except Exception:
            pass

        universe = list(set(SP100 + watchlist_tickers))

        # Categorised task list: large-caps + sub-$5 penny stocks + crypto, all
        # scored on the same factor engine so one digest covers everything.
        tasks: list[tuple[str, str]] = [(t, "stock") for t in universe]

        # Penny stocks (< $5) screened from the broad market.
        try:
            from research import fetch_cheap_stocks
            penny_syms = [r["ticker"] for r in
                          fetch_cheap_stocks(max_price=5.0, min_market_cap=10_000_000, limit=40)]
            tasks += [(t, "penny") for t in penny_syms if _valid_ticker(t)]
        except Exception as exc:
            logger.warning("Penny-stock screen failed: %s", exc)

        # Mid-priced stocks ($5–$25) screened from the broad market.
        try:
            from research import fetch_cheap_stocks
            mid_syms = [r["ticker"] for r in
                        fetch_cheap_stocks(min_price=5.0, max_price=25.0,
                                           min_market_cap=50_000_000, limit=40)]
            tasks += [(t, "mid") for t in mid_syms if _valid_ticker(t)]
        except Exception as exc:
            logger.warning("Mid-price ($5–$25) screen failed: %s", exc)

        all_syms = [t for t, _a in tasks]
        logger.info("Screening %d names (%d stocks, %d penny, %d mid $5–$25)…",
                    len(tasks), sum(1 for _t, a in tasks if a == "stock"),
                    sum(1 for _t, a in tasks if a == "penny"),
                    sum(1 for _t, a in tasks if a == "mid"))

        # Pre-fetch signal history for the whole universe in ONE query (main
        # thread) so worker threads never hit the DB pool during scoring.
        try:
            history_map = db.get_recent_signal_history_bulk(all_syms, lookback_days=10, before=today)
        except Exception as exc:
            logger.warning("Signal history prefetch failed: %s", exc)
            history_map = {}

        # Score all names in parallel (max 20 workers)
        scored: list[dict] = []
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {
                ex.submit(_score_ticker_for_digest, t, spy_returns,
                          history_map.get(t.upper()), atype): (t, atype)
                for (t, atype) in tasks
            }
            for f in as_completed(futures):
                result = f.result()
                if result:
                    scored.append(result)

        logger.info("Scored %d/%d names successfully", len(scored), len(tasks))

        # Persist today's stabilized signal rows in one batch (main thread).
        try:
            today_rows = [s["_signal_row"] for s in scored if s.get("_signal_row")]
            if today_rows:
                db.upsert_signal_history_bulk(
                    [{"as_of": today, **r} for r in today_rows]
                )
        except Exception as exc:
            logger.warning("Signal history bulk upsert failed: %s", exc)

        # Compute + persist the day's cross-sectional factor distribution, then
        # score every ticker on the SAME institutional engine the analysis page
        # uses (composite + distress guardrails), ranked within today's universe.
        universe_stats = None
        try:
            from backend.services.factor_engine import accumulate_universe_stats
            # Equities only — crypto factor scales would skew the distribution.
            exp_rows = [s["_exposures"] for s in scored
                        if s.get("_exposures") and s.get("asset_type") != "crypto"]
            if len(exp_rows) >= 10:
                universe_stats = accumulate_universe_stats(exp_rows)
                db.save_factor_universe_stats(today, universe_stats, len(exp_rows))
                logger.info("Saved factor universe stats over %d stocks", len(exp_rows))
        except Exception as exc:
            logger.warning("Factor universe stats save failed: %s", exc)

        try:
            from backend.services import factor_engine as fe
            for s in scored:
                fd = s.get("_fdata")
                if not fd:
                    continue
                fa = fe.analyze(fd, universe_stats=universe_stats)
                s["composite"] = fa.get("composite")
                s["distressed"] = bool(fa.get("guardrail_caps"))
                s["_quality_pct"] = (fa.get("families", {}).get("quality") or {}).get("percentile")
        except Exception as exc:
            logger.warning("Digest factor scoring failed: %s", exc)

        # A pick must clear the factor composite AND not be financially distressed —
        # the digest will never surface a distressed momentum name as a "top pick".
        def _quality_ok(s: dict) -> bool:
            if s.get("distressed"):
                return False
            comp = s.get("composite")
            return comp is None or comp >= 50

        stocks_only = [s for s in scored if s.get("asset_type") == "stock"]

        # Top 5 short-term (large-cap): momentum + RS, gated by composite & distress.
        st_eligible = [
            s for s in stocks_only
            if _quality_ok(s) and s["st_score"] >= 60 and s.get("rs_score", 0) >= 65
        ]
        st_eligible.sort(
            key=lambda x: (x.get("composite") or x["st_score"]) * 0.4
                          + x["st_score"] * 0.35 + x["rs_score"] * 0.25,
            reverse=True,
        )
        top_st = st_eligible[:5]

        # Top 5 long-term (large-cap): LT quality + RS, gated by composite & distress.
        lt_eligible = [
            s for s in stocks_only
            if _quality_ok(s) and s.get("lt_score") is not None
            and s["lt_score"] >= 60 and s.get("rs_score", 0) >= 60
        ]
        lt_eligible.sort(
            key=lambda x: (x.get("composite") or x["lt_score"] or 0) * 0.4
                          + (x["lt_score"] or 0) * 0.35 + x["rs_score"] * 0.25,
            reverse=True,
        )
        top_lt = lt_eligible[:5]

        # Top 5 sub-$5 stocks — same distress guardrails, ranked by composite + momentum.
        penny_eligible = [s for s in scored if s.get("asset_type") == "penny" and _quality_ok(s)]
        penny_eligible.sort(
            key=lambda x: (x.get("composite") or x["st_score"]) * 0.5 + x["st_score"] * 0.5,
            reverse=True,
        )
        top_penny = penny_eligible[:5]

        # Top 5 mid-priced ($5–$25) stocks — same distress guardrails, ranked by composite + momentum.
        mid_eligible = [s for s in scored if s.get("asset_type") == "mid" and _quality_ok(s)]
        mid_eligible.sort(
            key=lambda x: (x.get("composite") or x["st_score"]) * 0.5 + x["st_score"] * 0.5,
            reverse=True,
        )
        top_mid = mid_eligible[:5]

        logger.info("ST picks: %s | LT: %s | Penny: %s | Mid $5–$25: %s",
                    [p["ticker"] for p in top_st], [p["ticker"] for p in top_lt],
                    [p["ticker"] for p in top_penny], [p["ticker"] for p in top_mid])

        # Fair value / upside for each pick (cheap — only ~20 picks).
        from backend.services import valuation as _val
        def _pick_val(p: dict) -> dict | None:
            fd = p.get("_fdata")
            if not fd:
                return None
            v = _val.estimate(fd, quality_pct=p.get("_quality_pct"))
            return {"fair_value": v["fair_value"], "upside_pct": v["upside_pct"],
                    "verdict": v["verdict"]} if v else None

        def _mk(p: dict, horizon: str, signal, score) -> dict:
            return {"horizon": horizon, "signal": signal or "watch", "score": score or 50,
                    "composite": p.get("composite"), "valuation": _pick_val(p),
                    "reasoning": p.get("st_reasoning") if horizon in ("short", "penny", "mid") else p.get("lt_reasoning") or [],
                    **{k: p[k] for k in ("ticker", "company", "price", "day_change_pct", "rs_score")}}

        # Build email picks — one unified list across all four categories.
        email_picks = (
            [_mk(p, "short", p["st_signal"], p["st_score"]) for p in top_st]
            + [_mk(p, "long", p["lt_signal"], p.get("lt_score", 50)) for p in top_lt]
            + [_mk(p, "penny", p["st_signal"], p.get("composite") or p["st_score"]) for p in top_penny]
            + [_mk(p, "mid", p["st_signal"], p.get("composite") or p["st_score"]) for p in top_mid]
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
        send_errors: list[str] = []
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
                send_email(
                    to_email=recipient["email"],
                    subject=f"📈 TradingResearch Daily — Top picks for {today.strftime('%b %-d')}",
                    html_body=html,
                )
                users_sent += 1
            except Exception as exc:
                err_msg = f"{recipient.get('email')}: {type(exc).__name__}: {exc}"
                logger.error("Failed to send digest — %s", err_msg)
                send_errors.append(err_msg)

        # Log to DB
        try:
            db.log_digest_run(today, len(top_st), len(top_lt), users_sent)
        except Exception:
            pass

        return {
            "date": str(today),
            "st_picks": [p["ticker"] for p in top_st],
            "lt_picks": [p["ticker"] for p in top_lt],
            "penny_picks": [p["ticker"] for p in top_penny],
            "mid_picks": [p["ticker"] for p in top_mid],
            "users_sent": users_sent,
            "recipients_found": len(all_recipients),
            "email_configured": email_configured,
            "send_errors": send_errors,
            "universe_size": len(tasks),
            "scored": len(scored),
        }

    except Exception as exc:
        logger.error("Daily digest failed: %s", exc)
        return {"error": str(exc)}
