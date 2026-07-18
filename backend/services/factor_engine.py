"""
Cross-sectional factor engine — institutional-style stock scoring.

The retail approach (which this app used everywhere else) maps each indicator to
absolute points: "RSI < 30 → +12", "qtr return × 1.5 + 50". That has two deep
problems: the magic numbers are arbitrary, and a score of 72 tells you nothing
about whether 72 is good *relative to everything else you could buy*.

Institutions score **cross-sectionally**: every stock's exposure to a factor is
standardized (z-scored) against a reference universe, so "momentum" becomes
"88th percentile momentum among large-caps", not an absolute number. Factors are
grouped into well-researched families, each family is a percentile, and the
composite is a weighted blend whose weights are *learned from out-of-sample
performance* rather than hand-set.

This module is the engine. It is pure (no I/O): callers pass in a stock's raw
data plus a reference distribution (universe stats, produced daily by the digest
over the S&P 100) and get back a factor decomposition + composite + conviction.

Factor families and their economic rationale:
  MOMENTUM   — trend persists over 3–12 months (strongest medium-term anomaly).
  VALUE      — cheap cash/earnings yields outperform expensive ones long-run.
  QUALITY    — profitable, low-leverage, high-ROE firms compound and drawdown less.
  GROWTH     — durable revenue/earnings growth drives multiple expansion.
  LOW_VOL    — lower-beta / lower-volatility names earn better risk-adjusted returns.
  REVISIONS  — analyst upgrades, positive surprises, low short interest (sentiment
               & estimate momentum — one of the most robust public-data edges).
"""

from __future__ import annotations

import math

# ── Factor families → raw metrics, each already oriented so HIGHER = BULLISH ──
# Each metric is a (key, direction) pair; direction +1 means the raw value is
# already bullish-up, -1 means we flip its sign before standardizing.
FACTOR_FAMILIES: dict[str, list[tuple[str, int]]] = {
    "momentum": [
        ("month_change_pct", +1),
        ("pos_52w_pct", +1),
        ("pct_above_sma200", +1),
        ("rs_score", +1),
    ],
    "value": [
        ("earnings_yield", +1),      # 1 / forward P/E — high yield = cheap
        ("fcf_yield", +1),           # free cash flow / market cap
    ],
    "quality": [
        ("return_on_equity", +1),
        ("profit_margin", +1),
        ("debt_to_equity", -1),      # less debt = higher quality
        ("current_ratio", +1),
        ("roic_excess", +1),         # ROIC − WACC: value creation above cost of capital
        ("fcf_conversion", +1),      # FCF / net income: earnings-quality
        ("piotroski", +1),           # 0–9 fundamental-strength checklist
        ("altman_z", +1),            # distress risk (higher = safer)
    ],
    "growth": [
        ("eps_growth", +1),
        ("revenue_growth", +1),
    ],
    "low_vol": [
        ("beta", -1),                # lower beta = higher defensive score
        ("atr_pct", -1),
    ],
    "revisions": [
        ("analyst_upside_pct", +1),
        ("analyst_rec_score", +1),   # 5 - recommendationMean (higher = more buys)
        ("eps_surprise_pct", +1),
        ("revision_score", +1),      # net analyst upgrades − downgrades (estimate momentum)
        ("short_pct_float", -1),     # heavy shorting = bearish
    ],
}

# Institutional default family weights (sum to 1.0). Momentum carries the most
# medium-term signal; quality/value anchor the long side. Overridable per call
# (e.g. from backtest-optimized weights or a regime-specific profile).
DEFAULT_FAMILY_WEIGHTS: dict[str, float] = {
    "momentum": 0.30,
    "quality": 0.20,
    "value": 0.15,
    "growth": 0.15,
    "revisions": 0.12,
    "low_vol": 0.08,
}

# Fallback (mean, std) anchors used ONLY until a real universe distribution has
# been recorded. Rough large-cap norms so a single stock still ranks sensibly on
# day one. Keys are the *oriented* metric names (post-direction where relevant is
# handled in standardization, so these are for the raw values).
STATIC_ANCHORS: dict[str, tuple[float, float]] = {
    "month_change_pct":   (1.0, 8.0),
    "pos_52w_pct":        (55.0, 25.0),
    "pct_above_sma200":   (3.0, 12.0),
    "rs_score":           (50.0, 20.0),
    "earnings_yield":     (0.045, 0.03),
    "fcf_yield":          (0.04, 0.03),
    "return_on_equity":   (0.15, 0.13),
    "profit_margin":      (0.12, 0.10),
    "debt_to_equity":     (1.0, 1.2),
    "current_ratio":      (1.6, 0.9),
    "roic_excess":        (0.04, 0.08),   # ROIC − WACC; ~4% median excess return
    "fcf_conversion":     (0.9, 0.5),     # FCF ≈ net income for healthy firms
    "piotroski":          (5.0, 2.0),     # 0–9, absolute interpretation
    "altman_z":           (3.2, 1.6),     # >3 safe, <1.8 distress
    "eps_growth":         (0.10, 0.25),
    "revenue_growth":     (0.08, 0.12),
    "beta":               (1.05, 0.4),
    "atr_pct":            (2.2, 1.2),
    "analyst_upside_pct": (8.0, 15.0),
    "analyst_rec_score":  (2.7, 0.8),   # 5 - recommendationMean, ~2.7 ≈ Buy-ish
    "eps_surprise_pct":   (3.0, 8.0),
    "revision_score":     (0.0, 2.0),   # net upgrades − downgrades, centered at 0
    "short_pct_float":    (0.03, 0.05),
}

Z_CLIP = 3.0   # winsorize extreme exposures so one outlier can't dominate


def _norm_cdf(z: float) -> float:
    """Standard-normal CDF → maps a z-score to a 0–1 percentile."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def compute_exposures(data: dict) -> dict:
    """
    Extract raw factor metrics from a merged data dict (technical + fundamental +
    analyst + RS fields). Returns {metric: value|None}. Derived metrics (yields,
    distances) are computed here so callers can pass raw yfinance-style fields.
    """
    def g(*keys):
        for k in keys:
            v = data.get(k)
            if v is not None:
                return v
        return None

    exp: dict = {}

    exp["month_change_pct"] = g("month_change_pct")
    exp["pos_52w_pct"] = g("pos_52w_pct")
    exp["rs_score"] = g("rs_score")

    price = g("current_price")
    sma200 = g("sma200")
    exp["pct_above_sma200"] = (
        (price - sma200) / sma200 * 100 if price and sma200 and sma200 > 0 else None
    )

    fwd_pe = g("forward_pe")
    pe = g("pe_ratio")
    use_pe = fwd_pe if (fwd_pe and fwd_pe > 0) else (pe if (pe and pe > 0) else None)
    exp["earnings_yield"] = (1.0 / use_pe) if use_pe else None
    exp["fcf_yield"] = g("fcf_yield")   # optional; may be absent

    exp["return_on_equity"] = g("return_on_equity")
    exp["profit_margin"] = g("profit_margin")
    exp["debt_to_equity"] = g("debt_to_equity")
    exp["current_ratio"] = g("current_ratio")
    # Financial-health metrics (from financial_health.get_financial_health)
    exp["roic_excess"] = g("roic_excess")
    exp["fcf_conversion"] = g("fcf_conversion")
    exp["piotroski"] = g("piotroski")
    exp["altman_z"] = g("altman_z")

    exp["eps_growth"] = g("eps_growth")
    exp["revenue_growth"] = g("revenue_growth")

    exp["beta"] = g("beta")
    exp["atr_pct"] = g("atr_pct")

    exp["analyst_upside_pct"] = g("upside_pct", "analyst_upside_pct")
    rec_mean = g("recommendation_mean")
    exp["analyst_rec_score"] = (5.0 - rec_mean) if rec_mean is not None else None
    exp["eps_surprise_pct"] = g("eps_surprise_pct")
    exp["revision_score"] = g("revision_score")
    exp["short_pct_float"] = g("short_pct_float")

    return exp


def merge_factor_data(
    tech: dict | None,
    fund: dict | None,
    analyst: dict | None,
    rs_score: float | None,
) -> dict:
    """Flatten the analyzer's separate result sections into one dict for the
    engine. Later sources don't overwrite earlier non-null values."""
    merged: dict = {}
    for src in (tech or {}, fund or {}, analyst or {}):
        for k, v in src.items():
            if merged.get(k) is None and v is not None:
                merged[k] = v
    if rs_score is not None:
        merged["rs_score"] = rs_score
    return merged


def _metric_percentile(
    metric: str, value: float, direction: int, stats: dict | None
) -> float | None:
    """Standardize one raw metric to a 0–100 cross-sectional percentile."""
    if value is None:
        return None
    ref = (stats or {}).get(metric)
    if ref and ref.get("std"):
        mean, std = ref["mean"], ref["std"]
    else:
        mean, std = STATIC_ANCHORS.get(metric, (value, 1.0))
    if not std or std <= 0:
        return 50.0
    z = (value - mean) / std * direction
    z = max(-Z_CLIP, min(Z_CLIP, z))
    return round(_norm_cdf(z) * 100.0, 1)


def analyze(
    data: dict,
    universe_stats: dict | None = None,
    family_weights: dict | None = None,
) -> dict:
    """
    Full cross-sectional factor decomposition for one stock.

    Returns:
      {
        "families": {family: {"percentile", "metrics": {m: pct}, "n"}},
        "composite": 0-100 weighted blend of family percentiles,
        "conviction": 0-100 breadth-of-agreement conviction,
        "weights": effective family weights used,
        "coverage": fraction of metrics that had data,
      }
    """
    weights = dict(DEFAULT_FAMILY_WEIGHTS)
    if family_weights:
        weights.update(family_weights)

    exposures = compute_exposures(data)
    families: dict = {}
    total_metrics = 0
    covered_metrics = 0

    for fam, metrics in FACTOR_FAMILIES.items():
        pcts: dict = {}
        for metric, direction in metrics:
            total_metrics += 1
            pct = _metric_percentile(metric, exposures.get(metric), direction, universe_stats)
            if pct is not None:
                pcts[metric] = pct
                covered_metrics += 1
        fam_pct = round(sum(pcts.values()) / len(pcts), 1) if pcts else None
        families[fam] = {"percentile": fam_pct, "metrics": pcts, "n": len(pcts)}

    # Composite: weighted average over families that have data, weights
    # renormalized so missing families don't drag the score toward 50.
    num = 0.0
    den = 0.0
    for fam, w in weights.items():
        fp = families.get(fam, {}).get("percentile")
        if fp is not None:
            num += w * fp
            den += w
    composite = round(num / den, 1) if den > 0 else 50.0
    raw_composite = composite

    # ── Hard risk guardrails ──────────────────────────────────────────────────
    # A decision tool must never rate a financially distressed company as a
    # Buy/Hold just because its momentum or growth screens well. These caps
    # enforce the same discipline a real risk desk would: severe distress forces
    # the rating into Sell/Avoid territory regardless of the factor blend.
    caps: list[str] = []
    cap_at = 100.0
    alt   = data.get("altman_z")
    pio   = data.get("piotroski")
    fcf   = data.get("fcf_yield")
    roicx = data.get("roic_excess")

    if alt is not None and alt < 1.8:
        cap_at = min(cap_at, 40.0); caps.append(f"Altman-Z {alt:.1f} (distress zone)")
    if alt is not None and alt < 0:
        cap_at = min(cap_at, 25.0)   # negative Z = severe bankruptcy risk
    if pio is not None and pio <= 2:
        cap_at = min(cap_at, 45.0); caps.append(f"Piotroski {int(pio)}/9 (weak)")
    if fcf is not None and roicx is not None and fcf < 0 and roicx < 0:
        cap_at = min(cap_at, 32.0); caps.append("burning cash & destroying capital")

    if cap_at < composite:
        composite = round(cap_at, 1)

    # Conviction = breadth of agreement. How many families lean the SAME way as
    # the composite, weighted by how far each leans from neutral (50). A stock
    # strong on one factor but mixed elsewhere gets low conviction — honest.
    direction = 1 if composite >= 50 else -1
    agree_w = 0.0
    lean_sum = 0.0
    for fam, w in weights.items():
        fp = families.get(fam, {}).get("percentile")
        if fp is None:
            continue
        lean = (fp - 50.0)
        lean_sum += w * abs(lean)
        if (lean >= 0 and direction > 0) or (lean < 0 and direction < 0):
            agree_w += w * abs(lean)
    breadth = (agree_w / lean_sum) if lean_sum > 0 else 0.5      # 0..1 agreement
    magnitude = min(abs(composite - 50.0) / 30.0, 1.0)            # 0..1 conviction
    conviction = round(100.0 * (0.6 * breadth + 0.4 * magnitude), 0)
    # A distress cap is high-confidence bearish evidence — don't report it as a
    # wishy-washy low-conviction call.
    if caps:
        conviction = max(conviction, 65.0)

    return {
        "families": families,
        "composite": composite,
        "raw_composite": raw_composite,
        "conviction": conviction,
        "guardrail_caps": caps,
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "coverage": round(covered_metrics / total_metrics, 2) if total_metrics else 0.0,
    }


# ── Universe distribution stats (produced by the digest over the S&P 100) ─────

def accumulate_universe_stats(exposure_rows: list[dict]) -> dict:
    """
    Given many stocks' raw exposure dicts, compute per-metric {mean, std, n}.
    This is the reference distribution single-stock analysis ranks against.
    """
    metrics = {m for fam in FACTOR_FAMILIES.values() for (m, _d) in fam}
    stats: dict = {}
    for metric in metrics:
        vals = [
            float(r[metric]) for r in exposure_rows
            if r.get(metric) is not None and not _is_nan(r[metric])
        ]
        if len(vals) < 5:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[metric] = {"mean": round(mean, 6), "std": round(var ** 0.5, 6), "n": len(vals)}
    return stats


def _is_nan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False
