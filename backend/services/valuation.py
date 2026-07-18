"""
Valuation & trade-plan engine — the half of investing a factor score alone can't
answer: what is the business worth versus what it costs, and how do you act on it.

Fair value blends two independent, transparent estimates:
  1. Earnings power — forward EPS × a justified P/E derived from expected growth
     and quality (a PEG-anchored multiple, clamped to sane bounds).
  2. Analyst consensus — the mean price target (used only with enough coverage).

From the blend we derive a fair-value range, upside/downside, an expected
12-month return with bull/bear cases, a margin of safety, and a reverse-DCF
"growth priced in" so you can see whether the market already expects more than
the fundamentals support. Everything degrades gracefully to None when inputs
are missing, and every number is an estimate — labelled as such.

build_trade_plan turns that into an actionable plan: entry zone, ATR stop,
target, reward/risk, and a position size scaled by conviction and volatility.
"""

from __future__ import annotations


def _pos(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _justified_pe(eps_growth: float | None, quality_pct: float | None) -> float:
    """A defensible forward P/E from expected growth (PEG-anchored) with a small
    quality premium. Clamped to 8–35 so a single input can't produce nonsense."""
    g = (eps_growth or 0.0) * 100.0          # % growth
    base = 10.0 + max(g, 0.0) * 0.9          # ~PEG 1.1 above a 10x floor
    if quality_pct is not None:              # up to +15% for top-quintile quality
        base *= 1.0 + max(0.0, (quality_pct - 50.0) / 50.0) * 0.15
    return max(8.0, min(base, 35.0))


def estimate(data: dict, quality_pct: float | None = None) -> dict | None:
    """
    Estimate fair value + expected return. `data` should carry current_price,
    forward_eps (or eps), eps_growth, and analyst target_mean/low/high +
    num_analysts where available. `quality_pct` is the Quality factor percentile.
    """
    price = _pos(data.get("current_price"))
    if not price:
        return None

    fwd_eps = data.get("forward_eps")
    eps     = data.get("eps")
    use_eps = fwd_eps if (fwd_eps and fwd_eps > 0) else (eps if (eps and eps > 0) else None)
    eps_growth = data.get("eps_growth")

    estimates: list[tuple[str, float]] = []

    # 1. Earnings-power value
    just_pe = _justified_pe(eps_growth, quality_pct)
    if use_eps:
        estimates.append(("earnings power", round(use_eps * just_pe, 2)))

    # 2. Analyst consensus (needs meaningful coverage)
    target_mean = _pos(data.get("target_mean"))
    n_analysts  = data.get("num_analysts") or 0
    if target_mean and n_analysts >= 3:
        estimates.append(("analyst target", target_mean))

    if not estimates:
        return None

    # Blend (equal weight across whichever estimates exist)
    fair_value = round(sum(v for _n, v in estimates) / len(estimates), 2)

    # Range: prefer the analyst low/high, else scale by volatility-ish spread.
    t_low  = _pos(data.get("target_low"))
    t_high = _pos(data.get("target_high"))
    beta   = data.get("beta")
    spread = 0.20 + min(max((abs(beta) - 1.0) * 0.1 if beta else 0.0, 0.0), 0.15)
    fv_low  = round(t_low  if t_low  else fair_value * (1 - spread), 2)
    fv_high = round(t_high if t_high else fair_value * (1 + spread), 2)
    # keep base inside the range
    fv_low, fv_high = min(fv_low, fair_value), max(fv_high, fair_value)

    upside_pct = round((fair_value - price) / price * 100, 1)
    bull_pct   = round((fv_high - price) / price * 100, 1)
    bear_pct   = round((fv_low - price) / price * 100, 1)
    margin_of_safety = round((fair_value - price) / fair_value * 100, 1) if fair_value else None

    # Reverse-DCF lite: what growth does today's price imply, vs the estimate?
    implied_growth = None
    if use_eps:
        implied_pe = price / use_eps
        implied_growth = round(max((implied_pe - 10.0) / 0.9, -50.0) , 1)  # invert _justified_pe

    verdict = (
        "undervalued" if upside_pct >= 15 else
        "modestly undervalued" if upside_pct >= 5 else
        "roughly fair" if upside_pct > -10 else
        "overvalued"
    )

    return {
        "fair_value": fair_value,
        "fv_low": fv_low,
        "fv_high": fv_high,
        "current_price": round(price, 2),
        "upside_pct": upside_pct,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "margin_of_safety_pct": margin_of_safety,
        "justified_pe": round(just_pe, 1),
        "implied_growth_pct": implied_growth,
        "eps_growth_pct": round(eps_growth * 100, 1) if eps_growth is not None else None,
        "methods": [n for n, _v in estimates],
        "verdict": verdict,
    }


def build_trade_plan(
    data: dict,
    valuation: dict | None,
    conviction: float | None,
    signal: str | None,
    portfolio_value: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
) -> dict | None:
    """
    Actionable plan from price, ATR, fair value and conviction. Entry zone around
    the current price, ATR-based stop, target from fair value (fallback analyst),
    reward/risk, and a position size scaled by conviction and capped by a fixed
    per-trade risk budget.
    """
    price = _pos(data.get("current_price"))
    if not price:
        return None
    atr_pct = data.get("atr_pct")
    atr = (atr_pct / 100.0 * price) if atr_pct else price * 0.02   # fallback 2%

    stop = round(price - 1.5 * atr, 2)
    stop_pct = round((stop - price) / price * 100, 1)

    target = None
    if valuation and valuation.get("fair_value"):
        target = valuation["fair_value"]
    elif _pos(data.get("target_mean")):
        target = _pos(data.get("target_mean"))
    target = round(target, 2) if target else round(price + 3 * atr, 2)
    target_pct = round((target - price) / price * 100, 1)

    risk = price - stop
    reward = target - price
    rr = round(reward / risk, 2) if risk > 0 else None

    # Position size: fixed-fractional risk, scaled by conviction (0.4–1.0)…
    conv = max(0.0, min(conviction or 0.0, 100.0))
    conv_scale = 0.4 + 0.6 * (conv / 100.0)
    risk_budget = portfolio_value * (risk_per_trade_pct / 100.0) * conv_scale
    shares = int(risk_budget / risk) if risk > 0 else 0
    dollar_size = shares * price

    # …but hard-capped so a tight stop can never produce an imprudent position.
    # Max single-position weight scales 5%→15% with conviction.
    max_pct = 5.0 + 10.0 * (conv / 100.0)
    max_dollar = portfolio_value * max_pct / 100.0
    capped = dollar_size > max_dollar
    if capped:
        dollar_size = max_dollar
        shares = int(max_dollar / price) if price else 0
    dollar_size = round(shares * price, 2)
    size_pct = round(dollar_size / portfolio_value * 100, 2) if portfolio_value else 0.0

    entry_low  = round(price * 0.99, 2)
    entry_high = round(price * 1.01, 2)

    actionable = signal in ("buy", "watch", "strong buy") and (rr is None or rr >= 1.5)

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "stop_pct": stop_pct,
        "target": target,
        "target_pct": target_pct,
        "reward_risk": rr,
        "shares": shares,
        "dollar_size": dollar_size,
        "size_pct": size_pct,
        "size_capped": capped,
        "max_position_pct": round(max_pct, 1),
        "portfolio_value": portfolio_value,
        "risk_per_trade_pct": risk_per_trade_pct,
        "actionable": actionable,
    }
