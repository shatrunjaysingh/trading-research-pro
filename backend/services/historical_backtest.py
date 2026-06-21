"""
Historical backtest engine — simulates the multi-factor model on 2 years of daily data.

Approach:
  1. Download 2y OHLCV for universe stocks + SPY in one batch (no look-ahead bias).
  2. Evaluate monthly (every eval_every trading days), computing 8 price/volume factors
     using ONLY data available at that evaluation date.
     The 5 fundamental factors (earnings quality, short interest, sentiment, analyst,
     insider) cannot be replicated historically and are held fixed at 50 (neutral)
     so the optimiser focuses on the price-observable factors.
  3. Select top-N stocks by composite score, record entry price.
  4. Fill 5D / 21D / 63D forward returns from the same batch.
  5. Walk-forward weight optimization via numpy random search (scipy not required).
     Optimal weights sum to 1.0 across the 8 testable factors.
     research.py scales them by TESTABLE_WEIGHT_TOTAL (0.69) when applying to the
     full 13-factor composite.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# 8 price/volume factors that can be computed from historical OHLCV
FACTOR_KEYS = ["mom_3m", "mom_1m", "mom_1w", "mom_1d",
               "vol_scr", "pos_scr", "rs_spy", "rs_sector"]

# Default weights normalised to sum to 1.0 across the 8 testable factors.
# Proportions mirror the live model's 13-factor weights for these 8 factors:
#   mom_3m=18, mom_1m=14, mom_1w=9, mom_1d=2, vol_scr=9, pos_scr=3, rs_spy=7, rs_sector=7
#   total=69  →  each / 69
DEFAULT_WEIGHTS = {
    "mom_3m":    round(18 / 69, 4),   # ~0.2609
    "mom_1m":    round(14 / 69, 4),   # ~0.2029
    "mom_1w":    round( 9 / 69, 4),   # ~0.1304
    "mom_1d":    round( 2 / 69, 4),   # ~0.0290
    "vol_scr":   round( 9 / 69, 4),   # ~0.1304
    "pos_scr":   round( 3 / 69, 4),   # ~0.0435
    "rs_spy":    round( 7 / 69, 4),   # ~0.1014
    "rs_sector": round( 7 / 69, 4),   # ~0.1014
}


def _safe_ret(series, t_idx: int, n_back: int) -> float:
    prev_idx = max(0, t_idx - n_back)
    prev = float(series.iloc[prev_idx])
    curr = float(series.iloc[t_idx])
    if prev <= 0 or np.isnan(prev) or np.isnan(curr):
        return 0.0
    return (curr - prev) / prev * 100


def _compute_factors_8(closes, volumes, ticker: str, spy_s, t_idx: int) -> dict | None:
    """Compute the 8 price-based sub-scores (each 0-100) at index t_idx."""
    try:
        col     = closes[ticker]
        close_T = float(col.iloc[t_idx])
        if np.isnan(close_T) or close_T <= 0:
            return None

        # Momentum returns
        mom_3m_raw = _safe_ret(col, t_idx, 63)
        mom_1m_raw = _safe_ret(col, t_idx, 21)
        mom_1w_raw = _safe_ret(col, t_idx,  5)
        mom_1d_raw = _safe_ret(col, t_idx,  1)

        # 52-week position score
        window = col.iloc[max(0, t_idx - 252): t_idx + 1].dropna()
        hi52 = float(window.max()) if len(window) > 0 else close_T
        lo52 = float(window.min()) if len(window) > 0 else close_T
        pos_scr_raw = (close_T - lo52) / (hi52 - lo52) * 100 if hi52 != lo52 else 50.0

        # Volume surge score
        vol_col  = volumes[ticker]
        vol_5d   = float(vol_col.iloc[max(0, t_idx - 5): t_idx + 1].mean())
        vol_63d  = float(vol_col.iloc[max(0, t_idx - 63): t_idx + 1].mean())
        vol_ratio_raw = vol_5d / vol_63d if vol_63d > 0 else 1.0

        # Relative strength vs SPY (both factors use SPY in backtest)
        spy_3m     = _safe_ret(spy_s, t_idx, 63)
        rs_spy_raw = mom_3m_raw - spy_3m
        # rs_sector uses SPY as proxy (no per-ticker sector ETF history available)
        rs_sector_raw = rs_spy_raw

        # Normalise to 0-100 sub-scores (same formula as live research.py)
        return {
            "mom_3m":    min(max(mom_3m_raw  * 1.5 + 50, 0), 100),
            "mom_1m":    min(max(mom_1m_raw  * 2.0 + 50, 0), 100),
            "mom_1w":    min(max(mom_1w_raw  * 3.0 + 50, 0), 100),
            "mom_1d":    min(max(mom_1d_raw  * 5.0 + 50, 0), 100),
            "vol_scr":   min(vol_ratio_raw * 40, 100),
            "pos_scr":   pos_scr_raw,
            "rs_spy":    min(max(rs_spy_raw    * 2.0 + 50, 0), 100),
            "rs_sector": min(max(rs_sector_raw * 2.0 + 50, 0), 100),
            # raw values kept for display
            "raw_mom_3m":    round(mom_3m_raw, 2),
            "raw_rs_spy":    round(rs_spy_raw, 2),
            "raw_vol_ratio": round(vol_ratio_raw, 2),
            "close_T":       round(close_T, 4),
        }
    except Exception as exc:
        logger.debug("Factor compute failed %s t=%d: %s", ticker, t_idx, exc)
        return None


def _composite_score(factors: dict, weights: dict) -> float:
    return sum(factors[k] * weights.get(k, 0.0) for k in FACTOR_KEYS)


def _sharpe(arr: np.ndarray) -> float:
    return float(np.mean(arr) / (np.std(arr) + 1e-8)) if len(arr) > 0 else 0.0


def _optimize_weights(
    F: np.ndarray,
    R: np.ndarray,
    n_iter: int = 10_000,
    top_pct: float = 0.40,
) -> tuple[np.ndarray, float]:
    """Random-search Sharpe maximisation across 8 factors. Returns weights summing to 1.0."""
    n_f    = F.shape[1]
    best_w = np.ones(n_f) / n_f
    best_s = -np.inf
    rng    = np.random.default_rng(42)

    for _ in range(n_iter):
        w     = rng.dirichlet(np.ones(n_f) * 1.5)
        scr   = F @ w
        cut   = np.percentile(scr, (1 - top_pct) * 100)
        mask  = scr >= cut
        if mask.sum() < 3:
            continue
        sh = _sharpe(R[mask])
        if sh > best_s:
            best_s, best_w = sh, w.copy()

    return best_w, best_s


def _stats(vals: list) -> dict:
    v = [x for x in vals if x is not None]
    if not v:
        return {"avg": None, "win_rate": None, "sharpe": None, "n": 0}
    a = np.array(v, dtype=float)
    return {
        "avg":      round(float(np.mean(a)), 2),
        "win_rate": round(float(np.mean(a > 0)) * 100, 1),
        "sharpe":   round(_sharpe(a), 2),
        "n":        len(v),
    }


def run_historical_backtest(
    universe: list[str],
    years_back: int = 2,
    top_n: int = 5,
    eval_every: int = 21,   # evaluate every ~1 month of trading days
) -> dict:
    """
    Main entry point. Downloads data, runs simulation, optimises weights.
    Returns a comprehensive result dict suitable for the admin API and frontend.
    Optimal weights cover the 8 testable price/volume factors and sum to 1.0.
    research.py scales them by TESTABLE_WEIGHT_TOTAL (0.69) when building the composite.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    download_list = list(set(universe) | {"SPY"})
    logger.info("Downloading %dy history for %d tickers …", years_back, len(download_list))

    try:
        raw = yf.download(
            download_list,
            period=f"{years_back}y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        return {"error": f"Download failed: {exc}"}

    if "Close" not in raw:
        return {"error": "No price data returned from yfinance"}

    closes  = raw["Close"].ffill()
    volumes = raw["Volume"].fillna(0)

    all_dates = list(closes.index)
    n_dates   = len(all_dates)
    min_hist  = 252  # need 1 year before first evaluation

    if n_dates < min_hist + eval_every + 63:
        return {"error": f"Only {n_dates} trading days downloaded — need ≥{min_hist + eval_every + 63}"}

    spy_s       = closes["SPY"]
    stock_cols  = [t for t in universe if t in closes.columns]
    eval_indices = list(range(min_hist, n_dates - 63, eval_every))

    picks_data: list[dict] = []

    for t_idx in eval_indices:
        scored = []
        for ticker in stock_cols:
            fac = _compute_factors_8(closes, volumes, ticker, spy_s, t_idx)
            if fac is None:
                continue
            sc = _composite_score(fac, DEFAULT_WEIGHTS)
            scored.append((ticker, sc, fac))

        scored.sort(key=lambda x: x[1], reverse=True)
        eval_dt    = str(all_dates[t_idx].date())
        spy_entry  = float(spy_s.iloc[t_idx])

        for rank, (ticker, sc, fac) in enumerate(scored[:top_n], 1):
            entry = fac["close_T"]
            pick: dict = {
                "eval_date":  eval_dt,
                "ticker":     ticker,
                "rank":       rank,
                "score":      round(sc, 1),
                "entry":      entry,
                "factors":    {k: round(fac[k], 1) for k in FACTOR_KEYS},
                "raw_mom_3m": fac["raw_mom_3m"],
                "raw_rs_spy": fac["raw_rs_spy"],
            }

            for n_fwd, key in [(5, "5d"), (21, "21d"), (63, "63d")]:
                fwd_idx = t_idx + n_fwd
                if fwd_idx < n_dates:
                    try:
                        fp     = float(closes[ticker].iloc[fwd_idx])
                        spy_fp = float(spy_s.iloc[fwd_idx])
                        if not np.isnan(fp) and entry > 0 and spy_entry > 0:
                            ret     = (fp - entry) / entry * 100
                            spy_ret = (spy_fp - spy_entry) / spy_entry * 100
                            pick[f"return_{key}"]     = round(ret, 2)
                            pick[f"spy_return_{key}"] = round(spy_ret, 2)
                            pick[f"alpha_{key}"]      = round(ret - spy_ret, 2)
                        else:
                            pick[f"return_{key}"] = pick[f"spy_return_{key}"] = pick[f"alpha_{key}"] = None
                    except Exception:
                        pick[f"return_{key}"] = pick[f"spy_return_{key}"] = pick[f"alpha_{key}"] = None
                else:
                    pick[f"return_{key}"] = pick[f"spy_return_{key}"] = pick[f"alpha_{key}"] = None

            picks_data.append(pick)

    # Aggregate statistics
    stats_5d  = _stats([p.get("return_5d")  for p in picks_data])
    stats_21d = _stats([p.get("return_21d") for p in picks_data])
    stats_63d = _stats([p.get("return_63d") for p in picks_data])
    alpha_5d  = _stats([p.get("alpha_5d")   for p in picks_data])
    alpha_21d = _stats([p.get("alpha_21d")  for p in picks_data])

    # Walk-forward weight optimisation (train on first 75%, test on last 25%)
    opt_weights: dict | None = None
    opt_result:  dict | None = None

    eligible = [p for p in picks_data if p.get("return_5d") is not None]
    if len(eligible) >= 30:
        try:
            split  = int(len(eligible) * 0.75)
            tr, te = eligible[:split], eligible[split:]

            F_tr = np.array([[p["factors"][k] for k in FACTOR_KEYS] for p in tr])
            R_tr = np.array([p["return_5d"] for p in tr], dtype=float)

            best_w, _ = _optimize_weights(F_tr, R_tr)
            opt_weights = dict(zip(FACTOR_KEYS, [round(float(w), 4) for w in best_w]))

            cut_tr = np.percentile(F_tr @ best_w, 60)
            in_r   = R_tr[(F_tr @ best_w) >= cut_tr]

            if te:
                F_te = np.array([[p["factors"][k] for k in FACTOR_KEYS] for p in te])
                R_te = np.array([p["return_5d"] for p in te], dtype=float)
                cut_te = np.percentile(F_te @ best_w, 60) if len(F_te) > 0 else 0
                out_r  = R_te[(F_te @ best_w) >= cut_te]
            else:
                out_r = np.array([])

            opt_result = {
                "in_sample_avg":     round(float(np.mean(in_r)),  2) if len(in_r)  > 0 else None,
                "out_sample_avg":    round(float(np.mean(out_r)), 2) if len(out_r) > 0 else None,
                "in_sample_sharpe":  round(_sharpe(in_r),  2) if len(in_r)  > 0 else None,
                "out_sample_sharpe": round(_sharpe(out_r), 2) if len(out_r) > 0 else None,
                "n_train": split,
                "n_test":  len(te),
            }
            logger.info(
                "Opt weights (8-factor): %s | in-sample avg=%.2f%% | out-of-sample avg=%.2f%%",
                opt_weights,
                opt_result["in_sample_avg"] or 0,
                opt_result["out_sample_avg"] or 0,
            )
        except Exception as exc:
            logger.warning("Weight optimisation failed: %s", exc)

    return {
        "n_evaluations":       len(eval_indices),
        "n_picks_total":       len(picks_data),
        "universe":            universe,
        "years_back":          years_back,
        "top_n":               top_n,
        "stats_5d":            stats_5d,
        "stats_21d":           stats_21d,
        "stats_63d":           stats_63d,
        "alpha_5d":            alpha_5d,
        "alpha_21d":           alpha_21d,
        "picks":               picks_data[-60:],
        "default_weights":     DEFAULT_WEIGHTS,
        "optimal_weights":     opt_weights,
        "optimization_result": opt_result,
        "factor_keys":         FACTOR_KEYS,
    }
