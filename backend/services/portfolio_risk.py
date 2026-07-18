"""
Portfolio-level risk & construction — the layer that separates picking stocks
from running a book. Scoring names in isolation ignores what actually drives
portfolio outcomes: how positions move *together*, where risk concentrates, and
whether sizing matches conviction and volatility.

Given a set of holdings (ticker, weight, beta, sector, conviction), this computes:
  • Portfolio beta — market sensitivity of the whole book.
  • Sector concentration — weights + Herfindahl index (HHI) with flags.
  • Correlation matrix + redundant pairs — positions that are really one bet.
  • Portfolio volatility & diversification ratio — realized risk vs the naive
    weighted-average, i.e. how much diversification you're actually getting.
  • Expected downside — a 1-year 95% VaR estimate from portfolio volatility.
  • Vol- & conviction-targeted weights — a risk-parity-style target tilted toward
    higher-conviction names, with the largest rebalancing deltas surfaced.

The analytics are pure given a returns matrix, so callers can inject returns for
testing; in production `analyze_portfolio_risk` fetches history via yfinance.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
CORR_REDUNDANT = 0.75      # pairwise correlation above this = redundant risk
SECTOR_CONCENTRATION = 0.35  # single-sector weight above this = flag
VAR_Z_95 = 1.645           # one-sided 95% normal quantile


def _weights_from_holdings(holdings: list[dict]) -> np.ndarray:
    """Fractional weights from current_value (fallback to given 'weight' %)."""
    vals = [float(h.get("current_value") or 0) for h in holdings]
    total = sum(vals)
    if total > 0:
        return np.array([v / total for v in vals])
    pct = np.array([float(h.get("weight") or 0) for h in holdings])
    return pct / pct.sum() if pct.sum() > 0 else np.ones(len(holdings)) / len(holdings)


def _conviction_from_holding(h: dict) -> float:
    """0.2–1.0 conviction proxy from ST/LT scores (or factor composite if present)."""
    comp = (h.get("factor_analysis") or {}).get("composite")
    if comp is None:
        st = h.get("st_score")
        lt = h.get("lt_score")
        vals = [v for v in (st, lt) if v is not None]
        comp = sum(vals) / len(vals) if vals else 50.0
    return max(0.2, min(1.0, comp / 100.0))


def compute_risk(
    holdings: list[dict],
    returns: np.ndarray | None,
    tickers: list[str],
) -> dict:
    """
    Core risk math. `returns` is a (T × N) daily simple-returns matrix aligned to
    `tickers`, or None if unavailable (then correlation/vol are skipped).
    """
    n = len(tickers)
    w = _weights_from_holdings(holdings)
    betas = np.array([float(h.get("beta") or 1.0) for h in holdings])
    port_beta = float(np.dot(w, betas))

    # ── Sector concentration ──────────────────────────────────────────────────
    sector_w: dict[str, float] = {}
    for h, wi in zip(holdings, w):
        sec = h.get("sector") or "Unknown"
        sector_w[sec] = sector_w.get(sec, 0.0) + float(wi)
    hhi = float(sum(v * v for v in sector_w.values()))  # 1/n (diversified) → 1 (one sector)
    sector_flags = [
        {"sector": s, "weight": round(v * 100, 1)}
        for s, v in sorted(sector_w.items(), key=lambda kv: kv[1], reverse=True)
        if v > SECTOR_CONCENTRATION
    ]

    out: dict = {
        "portfolio_beta": round(port_beta, 2),
        "sector_weights": {s: round(v * 100, 1) for s, v in
                           sorted(sector_w.items(), key=lambda kv: kv[1], reverse=True)},
        "sector_hhi": round(hhi, 3),
        "sector_flags": sector_flags,
        "n_holdings": n,
    }

    if returns is None or returns.shape[0] < 20 or n < 2:
        out["risk_available"] = False
        out.update(_target_weights(holdings, w, tickers, vols=None))
        return out
    out["risk_available"] = True

    # ── Volatility & correlation ──────────────────────────────────────────────
    daily_vol = returns.std(axis=0, ddof=1)                 # per-asset daily σ
    ann_vol = daily_vol * np.sqrt(TRADING_DAYS)
    cov = np.cov(returns, rowvar=False, ddof=1)             # N×N daily covariance
    corr = np.corrcoef(returns, rowvar=False)

    port_daily_var = float(w @ cov @ w)
    port_daily_vol = float(np.sqrt(max(port_daily_var, 0.0)))
    port_ann_vol = port_daily_vol * np.sqrt(TRADING_DAYS)

    # Diversification ratio: weighted-avg σ ÷ portfolio σ (higher = more benefit)
    wavg_ann_vol = float(np.dot(w, ann_vol))
    diversification = round(wavg_ann_vol / port_ann_vol, 2) if port_ann_vol > 0 else None

    # Redundant pairs — high correlation AND both positions non-trivial
    redundant: list[dict] = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if not np.isnan(c) and c >= CORR_REDUNDANT and w[i] > 0.03 and w[j] > 0.03:
                redundant.append({
                    "a": tickers[i], "b": tickers[j],
                    "corr": round(float(c), 2),
                    "combined_weight": round(float(w[i] + w[j]) * 100, 1),
                })
    redundant.sort(key=lambda r: r["corr"], reverse=True)

    # 1-year 95% VaR estimate (assumes ~0 drift, normal): z × annual σ
    var_95_1y = round(VAR_Z_95 * port_ann_vol * 100, 1)

    out.update({
        "portfolio_ann_vol_pct": round(port_ann_vol * 100, 1),
        "weighted_avg_ann_vol_pct": round(wavg_ann_vol * 100, 1),
        "diversification_ratio": diversification,
        "redundant_pairs": redundant[:5],
        "est_var_95_1y_pct": var_95_1y,
        "asset_ann_vol_pct": {tickers[i]: round(float(ann_vol[i]) * 100, 1) for i in range(n)},
    })
    out.update(_target_weights(holdings, w, tickers, vols=ann_vol))
    return out


def _target_weights(
    holdings: list[dict], w: np.ndarray, tickers: list[str], vols: np.ndarray | None
) -> dict:
    """
    Conviction- & volatility-targeted weights: target_i ∝ conviction_i / vol_i
    (risk parity tilted by conviction). Surfaces the biggest rebalancing deltas.
    """
    conv = np.array([_conviction_from_holding(h) for h in holdings])
    if vols is not None:
        inv_vol = 1.0 / np.where(vols > 1e-6, vols, 1e-6)
    else:
        inv_vol = np.ones(len(holdings))
    raw = conv * inv_vol
    target = raw / raw.sum() if raw.sum() > 0 else w
    deltas = [
        {
            "ticker": tickers[i],
            "current_pct": round(float(w[i]) * 100, 1),
            "target_pct": round(float(target[i]) * 100, 1),
            "delta_pct": round(float(target[i] - w[i]) * 100, 1),
        }
        for i in range(len(tickers))
    ]
    deltas.sort(key=lambda d: abs(d["delta_pct"]), reverse=True)
    return {"target_weights": deltas}


def analyze_portfolio_risk(holdings: list[dict]) -> dict | None:
    """
    Production entry point. Fetches ~6 months of daily returns for the holdings
    and runs the risk math. `holdings` items need: ticker, current_value (or
    weight), beta, sector, and st_score/lt_score (or factor_analysis) for
    conviction. Returns None if there are fewer than 2 scorable holdings.
    """
    scorable = [h for h in holdings if h.get("ticker") and not h.get("error")]
    if len(scorable) < 2:
        return None

    tickers = [h["ticker"].upper() for h in scorable]
    returns = None
    try:
        import yfinance as yf
        data = yf.download(
            tickers, period="6mo", interval="1d",
            auto_adjust=True, progress=False, group_by="column",
        )
        closes = data["Close"] if "Close" in data else data
        closes = closes[tickers].dropna(how="all")       # keep column order = tickers
        rets = closes.pct_change().dropna(how="any")
        if len(rets) >= 20:
            returns = rets.to_numpy()
            tickers = list(closes.columns)               # align to actual columns
            # Re-align holdings order to the (possibly reordered) columns
            by_ticker = {h["ticker"].upper(): h for h in scorable}
            scorable = [by_ticker[t] for t in tickers if t in by_ticker]
            tickers = [t for t in tickers if t in by_ticker]
            returns = rets[tickers].to_numpy()
    except Exception as exc:
        logger.warning("Portfolio return fetch failed: %s", exc)
        returns = None

    try:
        return compute_risk(scorable, returns, tickers)
    except Exception as exc:
        logger.warning("Portfolio risk computation failed: %s", exc)
        return None
