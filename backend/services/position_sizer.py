"""
ATR-based position sizing model.

Formula: size = (portfolio_risk_pct × portfolio_value) / (ATR_pct × 1.5)
Adjusted by composite score (confidence proxy) and market regime multiplier.
"""


def compute_position_size(
    entry_price: float,
    atr_pct: float,              # ATR as % of price (e.g. 2.5 means 2.5% of price)
    score: int,                  # composite score 0-100
    regime_multiplier: float = 1.0,
    portfolio_value: float = 100_000,
    base_risk_pct: float = 0.01, # risk 1% of portfolio per trade
) -> dict:
    """
    Returns sizing recommendation dict with position size, stop loss, and dollar amounts.
    """
    atr_pct = max(atr_pct, 0.5)          # floor at 0.5% to avoid division by zero

    # Stop loss 1.5× ATR below entry
    stop_loss_pct = 1.5 * atr_pct / 100  # as a fraction of price
    stop_price    = round(entry_price * (1.0 - stop_loss_pct), 4)

    # Base size = risk budget / per-share risk
    raw_size_pct = (base_risk_pct / stop_loss_pct) * 100  # as % of portfolio

    # Score-based confidence adjustment (score 50 → 0.75×, score 90 → 1.05×)
    conf_adj = 0.75 + (max(score, 50) - 50) / 200.0
    conf_adj = max(0.5, min(1.5, conf_adj))

    size_pct = raw_size_pct * conf_adj * regime_multiplier
    size_pct = max(0.25, min(10.0, size_pct))  # hard caps: 0.25%–10%

    dollar_size = portfolio_value * size_pct / 100.0
    shares      = max(1, int(dollar_size / entry_price)) if entry_price > 0 else 0

    return {
        "size_pct":        round(size_pct, 2),
        "dollar_size":     round(dollar_size, 2),
        "shares":          shares,
        "stop_price":      stop_price,
        "stop_loss_pct":   round(stop_loss_pct * 100, 2),
        "atr_pct":         round(atr_pct, 2),
        "risk_budget_usd": round(portfolio_value * base_risk_pct, 2),
    }
