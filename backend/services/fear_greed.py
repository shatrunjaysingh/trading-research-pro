"""
Fear & Greed Index — composite market sentiment gauge (0 = Extreme Fear, 100 = Extreme Greed).

Components (weighted):
  30% — Volatility (VIX): lower VIX → greed
  30% — Momentum (SPY vs 125-day MA): price above MA → greed
  15% — Safe Haven (stocks vs gold 30d return): stocks outperform → greed
  15% — Junk Bond Demand (HYG vs LQD 30d return): HYG outperforms → greed
  10% — Market Breadth (14-day RSI of SPY): high RSI → greed
"""

import math


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def compute_fear_greed() -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return {"score": 50, "label": "Neutral", "color": "#eab308", "components": {}}

    scores: dict[str, dict] = {}

    # --- 1. VIX volatility (inverted) ---
    try:
        vix_price = _safe(yf.Ticker("^VIX").fast_info.last_price)
        if vix_price is not None:
            # VIX < 15 → extreme greed (100), VIX > 40 → extreme fear (0)
            vix_score = max(0.0, min(100.0, (40 - vix_price) / 25 * 100))
            scores["vix"] = {
                "score": round(vix_score, 1),
                "value": round(vix_price, 2),
                "label": "Market Volatility (VIX)",
            }
        else:
            scores["vix"] = {"score": 50.0, "value": None, "label": "Market Volatility (VIX)"}
    except Exception:
        scores["vix"] = {"score": 50.0, "value": None, "label": "Market Volatility (VIX)"}

    # --- 2. SPY Momentum (price vs 125-day MA) ---
    try:
        spy_hist = yf.Ticker("SPY").history(period="8mo", interval="1d")
        if len(spy_hist) >= 125:
            price = float(spy_hist["Close"].iloc[-1])
            ma125 = float(spy_hist["Close"].rolling(125).mean().iloc[-1])
            pct_from_ma = (price - ma125) / ma125 * 100  # +/- %
            # +10% above MA → 100, -10% below → 0
            mom_score = max(0.0, min(100.0, 50 + pct_from_ma * 5))
            scores["momentum"] = {
                "score": round(mom_score, 1),
                "value": round(price, 2),
                "label": "Market Momentum (SPY vs 125-day MA)",
            }
        else:
            scores["momentum"] = {"score": 50.0, "value": None, "label": "Market Momentum"}
    except Exception:
        scores["momentum"] = {"score": 50.0, "value": None, "label": "Market Momentum"}

    # --- 3. Safe Haven (stocks vs gold) ---
    try:
        gld_hist = yf.Ticker("GLD").history(period="35d", interval="1d")
        spy_1m   = yf.Ticker("SPY").history(period="35d", interval="1d")
        if len(gld_hist) >= 20 and len(spy_1m) >= 20:
            gld_ret = (float(gld_hist["Close"].iloc[-1]) / float(gld_hist["Close"].iloc[0]) - 1) * 100
            spy_ret = (float(spy_1m["Close"].iloc[-1]) / float(spy_1m["Close"].iloc[0]) - 1) * 100
            spread = spy_ret - gld_ret  # stocks outperform gold → greed
            safe_score = max(0.0, min(100.0, 50 + spread * 4))
            scores["safe_haven"] = {
                "score": round(safe_score, 1),
                "value": None,
                "label": "Safe Haven Demand (Stocks vs Gold)",
            }
        else:
            scores["safe_haven"] = {"score": 50.0, "value": None, "label": "Safe Haven Demand"}
    except Exception:
        scores["safe_haven"] = {"score": 50.0, "value": None, "label": "Safe Haven Demand"}

    # --- 4. Junk Bond Demand (HYG vs LQD) ---
    try:
        hyg_hist = yf.Ticker("HYG").history(period="35d", interval="1d")
        lqd_hist = yf.Ticker("LQD").history(period="35d", interval="1d")
        if len(hyg_hist) >= 20 and len(lqd_hist) >= 20:
            hyg_ret = (float(hyg_hist["Close"].iloc[-1]) / float(hyg_hist["Close"].iloc[0]) - 1) * 100
            lqd_ret = (float(lqd_hist["Close"].iloc[-1]) / float(lqd_hist["Close"].iloc[0]) - 1) * 100
            spread = hyg_ret - lqd_ret  # junk bonds outperform → risk-on = greed
            junk_score = max(0.0, min(100.0, 50 + spread * 8))
            scores["junk_bond"] = {
                "score": round(junk_score, 1),
                "value": None,
                "label": "Junk Bond Demand (HYG vs LQD)",
            }
        else:
            scores["junk_bond"] = {"score": 50.0, "value": None, "label": "Junk Bond Demand"}
    except Exception:
        scores["junk_bond"] = {"score": 50.0, "value": None, "label": "Junk Bond Demand"}

    # --- 5. Market Breadth (14-day RSI of SPY) ---
    try:
        spy_3m = yf.Ticker("SPY").history(period="3mo", interval="1d")
        if len(spy_3m) >= 15:
            delta  = spy_3m["Close"].diff()
            gains  = delta.clip(lower=0).rolling(14).mean()
            losses = (-delta.clip(upper=0)).rolling(14).mean()
            rs     = gains / losses
            rsi    = (100 - 100 / (1 + rs)).iloc[-1]
            scores["breadth"] = {
                "score": round(float(rsi), 1),
                "value": round(float(rsi), 1),
                "label": "Market Breadth (14-day RSI of SPY)",
            }
        else:
            scores["breadth"] = {"score": 50.0, "value": None, "label": "Market Breadth"}
    except Exception:
        scores["breadth"] = {"score": 50.0, "value": None, "label": "Market Breadth"}

    # Composite weighted average
    weights = {"vix": 0.30, "momentum": 0.30, "safe_haven": 0.15, "junk_bond": 0.15, "breadth": 0.10}
    composite = sum(scores[k]["score"] * weights[k] for k in weights if k in scores)
    composite = round(max(0.0, min(100.0, composite)), 1)

    if composite >= 75:
        label, color = "Extreme Greed", "#16a34a"
    elif composite >= 60:
        label, color = "Greed", "#22c55e"
    elif composite >= 40:
        label, color = "Neutral", "#eab308"
    elif composite >= 25:
        label, color = "Fear", "#f97316"
    else:
        label, color = "Extreme Fear", "#dc2626"

    return {"score": composite, "label": label, "color": color, "components": scores}
