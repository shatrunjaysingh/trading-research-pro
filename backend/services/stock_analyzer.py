"""
Single-stock deep analysis service.
Fetches price history + fundamentals via yfinance, computes requested
technical indicators, optionally calls Claude for AI narrative.
Yields SSE-style events so the router can stream results to the browser.
"""

import json
import logging
import math
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generator

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "1d": ("1d", "1m"),
    "1w": ("5d", "15m"),
    "1m": ("1mo", "1h"),
    "3m": ("3mo", "1d"),
    "6m": ("6mo", "1d"),
    "1y": ("1y", "1d"),
}


def _safe(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _norm_de(v: Any) -> float | None:
    """yfinance reports debt/equity as a PERCENTAGE (e.g. 168 = 1.68x). Normalise
    to a ratio so leverage thresholds (e.g. 'D/E > 2.0') and the factor engine's
    anchors are correct rather than flagging every firm as over-levered."""
    f = _safe(v)
    if f is None:
        return None
    return round(f / 100.0, 4) if f > 5 else round(f, 4)


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:  # period is user-configurable
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    def ema(data: list[float], n: int) -> list[float]:
        k = 2 / (n + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(closes) < slow:
        return None, None, None
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    offset = slow - 1
    macd_line = [ef - es for ef, es in zip(ema_fast[offset:], ema_slow[offset:])]
    if len(macd_line) < signal:
        return _safe(macd_line[-1]), None, None
    signal_line = ema(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return _safe(macd_line[-1]), _safe(signal_line[-1]), _safe(hist)


def _compute_vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> float | None:
    """Volume-Weighted Average Price across available bars."""
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n == 0:
        return None
    tp_vol  = sum(((highs[i] + lows[i] + closes[i]) / 3) * volumes[i] for i in range(n))
    tot_vol = sum(volumes[:n])
    if tot_vol == 0:
        return None
    return round(tp_vol / tot_vol, 4)


def _compute_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:
    """Average True Range over last `period` bars."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]))
        for i in range(1, n)
    ]
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period, 4)


def _compute_bollinger(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[float | None, float | None, float | None]:
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    return round(mid + std_mult * std, 4), round(mid - std_mult * std, 4), round(mid, 4)


def _raw_signal_score(tech: dict) -> tuple[float, float]:
    """Compute a DURABLE raw momentum score (0–100) and an agreement fraction.

    Deliberately built only from slow-moving trend/momentum indicators (RSI,
    MACD, price vs 50/200-day MAs). Single-day noise — day change, intraday
    VWAP, last-vs-average volume — is *excluded* from the score: those drove the
    old signal's overnight flip-flops. They remain in `tech` for display only.

    Returns (raw_score, agreement) where agreement ∈ [0,1] is how one-sided the
    indicator votes are (|net votes| / total). The stabilizer turns this raw
    score into the smoothed, hysteresis-gated signal and honest confidence.
    """
    score = 50.0
    votes: list[int] = []   # +1 = bullish, -1 = bearish, 0 = neutral

    rsi = tech.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 12; votes.append(1)
        elif rsi < 45:
            score += 6;  votes.append(1)
        elif rsi > 70:
            score -= 12; votes.append(-1)
        elif rsi > 55:
            score -= 6;  votes.append(-1)
        else:
            votes.append(0)

    macd = tech.get("macd")
    macd_sig = tech.get("macd_signal")
    if macd is not None and macd_sig is not None:
        if macd > macd_sig:
            score += 8; votes.append(1)
        else:
            score -= 8; votes.append(-1)

    close = tech.get("current_price")
    sma50 = tech.get("sma50")
    sma200 = tech.get("sma200")
    if close and sma50:
        if close > sma50:
            score += 8; votes.append(1)
        else:
            score -= 8; votes.append(-1)
    if close and sma200:
        if close > sma200:
            score += 7; votes.append(1)
        else:
            score -= 7; votes.append(-1)

    # Day change is kept only as a tiny freshness tilt (±3 max) and does NOT
    # vote — it must never be strong enough to flip the signal on its own.
    day_chg = tech.get("day_change_pct")
    if day_chg is not None:
        score += min(max(day_chg * 1.0, -3), 3)

    score = round(min(max(score, 0), 100), 1)

    total = len(votes)
    agreement = (abs(sum(votes)) / total) if total > 0 else 0.0
    return score, round(agreement, 3)


def _compute_weekly_confirmation(ticker: str) -> dict:
    """
    Fetch weekly bars and compute RSI + MACD on weekly timeframe.
    Returns: {rsi_w, macd_above_signal_w, trend_w}
    Weekly confirmation lifts conviction when it agrees with daily signal.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker.upper()).history(period="2y", interval="1wk")
        if len(hist) < 30:
            return {}
        closes = hist["Close"].dropna().tolist()
        rsi_w  = _compute_rsi(closes, period=14)
        m, ms, _ = _compute_macd(closes)
        macd_above = (m > ms) if (m is not None and ms is not None) else None
        # Determine weekly trend
        sma20w = _compute_sma(closes, 20)
        price  = closes[-1] if closes else None
        trend  = "up" if (price and sma20w and price > sma20w) else "down"
        return {"rsi_w": rsi_w, "macd_above_signal_w": macd_above, "trend_w": trend}
    except Exception:
        return {}


def _compute_st_score(tech: dict, rs_score: int, weekly: dict) -> dict:
    """
    Short-term score (1–4 week horizon).
    Optimised for momentum + near-term catalyst capture.

    Returns: {score, signal, reasoning[]}
    """
    score = 50.0
    reasons: list[str] = []

    # RSI: ideal zone for continuation is 50–65 (not overbought but building momentum)
    rsi = tech.get("rsi")
    if rsi is not None:
        if 50 <= rsi <= 65:
            score += 15; reasons.append(f"RSI {rsi:.0f} in ideal momentum zone")
        elif 40 <= rsi < 50:
            score += 8;  reasons.append(f"RSI {rsi:.0f} — neutral, watching")
        elif rsi < 30:
            score += 12; reasons.append(f"RSI {rsi:.0f} — oversold bounce candidate")
        elif rsi > 70:
            score -= 12; reasons.append(f"RSI {rsi:.0f} — overbought, pullback risk")

    # MACD bullish crossover / positive histogram
    macd     = tech.get("macd")
    macd_sig = tech.get("macd_signal")
    macd_h   = tech.get("macd_hist")
    if macd is not None and macd_sig is not None:
        if macd > macd_sig:
            score += 12; reasons.append("MACD above signal — bullish momentum")
        else:
            score -= 10; reasons.append("MACD below signal — bearish momentum")
    if macd_h is not None and macd_h > 0:
        score += 3  # histogram expanding = acceleration

    # Price vs 50-day SMA (key short-term support/resistance)
    price = tech.get("current_price")
    sma50 = tech.get("sma50")
    if price and sma50:
        pct_above = (price - sma50) / sma50 * 100
        if 0 < pct_above <= 8:
            score += 12; reasons.append(f"Price {pct_above:.1f}% above 50-day MA — healthy uptrend")
        elif pct_above > 8:
            score += 6;  reasons.append(f"Price {pct_above:.1f}% above 50-day MA — extended")
        else:
            score -= 10; reasons.append("Price below 50-day MA — short-term downtrend")

    # Volume confirmation
    vol_ratio = tech.get("vol_ratio")
    if vol_ratio:
        if vol_ratio >= 1.5:
            score += 8; reasons.append(f"Volume {vol_ratio:.1f}x average — institutional interest")
        elif vol_ratio < 0.7:
            score -= 4; reasons.append("Low volume — conviction lacking")

    # Volume trend (accumulation vs distribution)
    vol_signal = tech.get("vol_signal")
    if vol_signal == "accumulation":
        score += 5; reasons.append("30-day volume trend: accumulation")
    elif vol_signal == "distribution":
        score -= 5; reasons.append("30-day volume trend: distribution")

    # Day change momentum
    day_chg = tech.get("day_change_pct")
    if day_chg is not None:
        score += min(max(day_chg * 2, -8), 8)

    # Weekly confirmation (adds high-conviction bonus)
    rsi_w = weekly.get("rsi_w")
    macd_w = weekly.get("macd_above_signal_w")
    trend_w = weekly.get("trend_w")
    if trend_w == "up":
        if macd_w:
            score += 8; reasons.append("Weekly trend + MACD both bullish — strong alignment")
        else:
            score += 3; reasons.append("Weekly trend bullish")
    elif trend_w == "down":
        score -= 8; reasons.append("Weekly trend bearish — fighting headwind")

    # RS Rating bonus (strong relative performers tend to keep outperforming)
    if rs_score >= 90:
        score += 12; reasons.append(f"RS Rating {rs_score} — elite relative strength (top 10%)")
    elif rs_score >= 80:
        score += 8;  reasons.append(f"RS Rating {rs_score} — strong relative strength")
    elif rs_score >= 70:
        score += 4;  reasons.append(f"RS Rating {rs_score} — above average")
    elif rs_score < 40:
        score -= 8;  reasons.append(f"RS Rating {rs_score} — lagging the market")

    score = round(max(0, min(100, score)), 1)
    signal = "strong buy" if score >= 78 else "buy" if score >= 65 else "watch" if score >= 52 else "hold" if score >= 38 else "sell"
    return {"score": score, "signal": signal, "reasoning": reasons}


def _compute_lt_score(tech: dict, fund: dict, rs_score: int) -> dict:
    """
    Long-term score (3–12 month horizon).
    Focus: fundamental quality + relative strength + trend structure.

    Returns: {score, signal, reasoning[]}
    """
    score = 50.0
    reasons: list[str] = []

    # ── Fundamental Quality (50 pts max) ──────────────────────────────────────

    # EPS growth (key growth signal)
    eps_growth = fund.get("eps_growth")
    if eps_growth is not None:
        if eps_growth > 0.5:
            score += 18; reasons.append(f"EPS growth {eps_growth*100:.0f}% — exceptional growth")
        elif eps_growth > 0.25:
            score += 14; reasons.append(f"EPS growth {eps_growth*100:.0f}% — strong growth")
        elif eps_growth > 0.10:
            score += 8;  reasons.append(f"EPS growth {eps_growth*100:.0f}% — moderate growth")
        elif eps_growth < -0.10:
            score -= 12; reasons.append(f"EPS growth {eps_growth*100:.0f}% — shrinking earnings")

    # Revenue growth
    rev_growth = fund.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 0.20:
            score += 10; reasons.append(f"Revenue growth {rev_growth*100:.0f}% — strong expansion")
        elif rev_growth > 0.10:
            score += 6;  reasons.append(f"Revenue growth {rev_growth*100:.0f}%")
        elif rev_growth < -0.05:
            score -= 8;  reasons.append(f"Revenue declining {rev_growth*100:.0f}%")

    # ROE (management efficiency)
    roe = fund.get("return_on_equity")
    if roe is not None:
        if roe > 0.25:
            score += 10; reasons.append(f"ROE {roe*100:.0f}% — highly efficient management")
        elif roe > 0.15:
            score += 6;  reasons.append(f"ROE {roe*100:.0f}% — good capital allocation")
        elif roe < 0:
            score -= 8;  reasons.append("Negative ROE — unprofitable")

    # Profit margins (quality of earnings)
    margin = fund.get("profit_margin")
    if margin is not None:
        if margin > 0.20:
            score += 8; reasons.append(f"Net margin {margin*100:.0f}% — highly profitable")
        elif margin > 0.10:
            score += 4; reasons.append(f"Net margin {margin*100:.0f}% — healthy")
        elif margin < 0:
            score -= 6; reasons.append("Negative margins — losing money")

    # Valuation: forward vs trailing P/E (earnings expected to grow)
    pe     = fund.get("pe_ratio")
    fwd_pe = fund.get("forward_pe")
    if pe and fwd_pe and pe > 0 and fwd_pe > 0:
        if fwd_pe < pe * 0.85:
            score += 8; reasons.append(f"Fwd P/E {fwd_pe:.0f}x < TTM P/E {pe:.0f}x — earnings expected to grow")
        elif fwd_pe < pe:
            score += 4; reasons.append("Earnings expected to improve")

    # Debt (financial risk)
    de = fund.get("debt_to_equity")
    if de is not None:
        if de < 0.3:
            score += 6; reasons.append(f"Low debt ({de:.1f}x D/E) — financial flexibility")
        elif de > 2.0:
            score -= 8; reasons.append(f"High leverage ({de:.1f}x D/E) — financial risk")

    # Short interest (contrarian signal — high short = bearish)
    short_pct = fund.get("short_pct_float")
    if short_pct is not None:
        if short_pct > 0.20:
            score -= 8; reasons.append(f"{short_pct*100:.0f}% short interest — heavy bearish bet against stock")
        elif short_pct > 0.10:
            score -= 4; reasons.append(f"{short_pct*100:.0f}% short interest — moderate bearish positioning")

    # ── Technical structure for long term (20 pts max) ───────────────────────

    price  = tech.get("current_price")
    sma200 = tech.get("sma200")
    sma50  = tech.get("sma50")

    if price and sma200:
        pct_above = (price - sma200) / sma200 * 100
        if pct_above > 0:
            score += 10; reasons.append(f"Price {pct_above:.1f}% above 200-day MA — long-term uptrend")
        else:
            score -= 10; reasons.append("Price below 200-day MA — long-term downtrend")

    if price and sma50 and sma200:
        if sma50 > sma200:
            score += 5; reasons.append("Golden Cross in effect (SMA50 > SMA200)")
        else:
            score -= 5; reasons.append("Death Cross in effect (SMA50 < SMA200)")

    # ── RS Rating (30 pts max) ────────────────────────────────────────────────

    if rs_score >= 90:
        score += 20; reasons.append(f"RS Rating {rs_score} — elite (top 10%). Strong stocks stay strong.")
    elif rs_score >= 80:
        score += 14; reasons.append(f"RS Rating {rs_score} — leader (top 20%)")
    elif rs_score >= 70:
        score += 8;  reasons.append(f"RS Rating {rs_score} — above average")
    elif rs_score < 50:
        score -= 8;  reasons.append(f"RS Rating {rs_score} — underperforming the market")
    elif rs_score < 30:
        score -= 15; reasons.append(f"RS Rating {rs_score} — significantly lagging")

    score = round(max(0, min(100, score)), 1)
    signal = "strong buy" if score >= 78 else "buy" if score >= 65 else "watch" if score >= 52 else "hold" if score >= 38 else "sell"
    return {"score": score, "signal": signal, "reasoning": reasons}


def _fetch_stock_data(
    ticker: str,
    period: str,
    interval: str,
    indicators: list[str],
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    ticker_upper = ticker.strip().upper()
    yf_ticker = yf.Ticker(ticker_upper)

    # Fast info
    try:
        fi = yf_ticker.fast_info
        current    = _safe(getattr(fi, "last_price", None))
        prev_close = _safe(getattr(fi, "previous_close", None))
        high_52w   = _safe(getattr(fi, "year_high", None))
        low_52w    = _safe(getattr(fi, "year_low", None))
        avg_volume = _safe(getattr(fi, "three_month_average_volume", None))
        last_vol   = _safe(getattr(fi, "last_volume", None))
    except Exception:
        return {"error": f"Could not fetch data for {ticker_upper}. Verify the ticker symbol."}

    if not current:
        return {"error": f"No price data for {ticker_upper}. Is this a valid ticker?"}

    # History for indicator computation
    hist = yf_ticker.history(period=period, interval=interval, auto_adjust=True)
    if hist.empty:
        return {"error": f"No history available for {ticker_upper} in period {period}"}

    closes  = [float(v) for v in hist["Close"].dropna().tolist()]
    volumes = [float(v) for v in hist["Volume"].dropna().tolist()]
    highs   = [float(v) for v in hist["High"].dropna().tolist()] if "High" in hist else []
    lows    = [float(v) for v in hist["Low"].dropna().tolist()]  if "Low"  in hist else []

    # Period returns
    day_chg  = ((current - prev_close) / prev_close * 100) if prev_close else None
    week_chg = ((current - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None
    mon_chg  = ((current - closes[-21]) / closes[-21] * 100) if len(closes) >= 21 else None
    pos_52w  = ((current - low_52w) / (high_52w - low_52w) * 100) if (high_52w and low_52w and high_52w != low_52w) else None
    vol_ratio = (last_vol / avg_volume) if (last_vol and avg_volume) else None

    # 30-day volume trend vs prior 30 days
    vol_30d_avg: float | None   = None
    vol_prior_avg: float | None = None
    vol_trend_pct: float | None = None
    vol_signal: str | None      = None
    if len(volumes) >= 30:
        vol_30d_avg = round(sum(volumes[-30:]) / 30, 0)
        if len(volumes) >= 60:
            vol_prior_avg = round(sum(volumes[-60:-30]) / 30, 0)
            if vol_prior_avg and vol_prior_avg > 0:
                vol_trend_pct = round((vol_30d_avg - vol_prior_avg) / vol_prior_avg * 100, 1)
                price_up = mon_chg is not None and mon_chg > 0
                if vol_trend_pct > 20:
                    vol_signal = "accumulation" if price_up else "distribution"
                elif vol_trend_pct < -20:
                    vol_signal = "contraction"
                else:
                    vol_signal = "neutral"

    tech: dict = {
        "current_price": current,
        "prev_close": prev_close,
        "day_change_pct": _safe(day_chg),
        "week_change_pct": _safe(week_chg),
        "month_change_pct": _safe(mon_chg),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pos_52w_pct": _safe(pos_52w),
        "avg_volume": avg_volume,
        "last_volume": last_vol,
        "vol_ratio": _safe(vol_ratio),
        "vol_30d_avg": _safe(vol_30d_avg),
        "vol_prior_avg": _safe(vol_prior_avg),
        "vol_trend_pct": _safe(vol_trend_pct),
        "vol_signal": vol_signal,
    }

    ind_set = set(indicators)

    if "rsi" in ind_set:
        tech["rsi"] = _compute_rsi(closes, period=rsi_period)

    if "macd" in ind_set:
        tech["macd"], tech["macd_signal"], tech["macd_hist"] = _compute_macd(
            closes, fast=macd_fast, slow=macd_slow, signal=macd_signal
        )

    if "sma20" in ind_set:
        tech["sma20"] = _compute_sma(closes, 20)

    if "sma50" in ind_set:
        tech["sma50"] = _compute_sma(closes, 50)

    if "sma200" in ind_set:
        tech["sma200"] = _compute_sma(closes, 200)

    if "bollinger" in ind_set:
        tech["bb_upper"], tech["bb_lower"], tech["bb_mid"] = _compute_bollinger(
            closes, period=bb_period, std_mult=bb_std
        )

    # VWAP and ATR — always computed when history is available
    tech["vwap"] = _compute_vwap(highs, lows, closes, volumes)
    atr = _compute_atr(highs, lows, closes)
    tech["atr"] = atr
    tech["atr_pct"] = _safe((atr / current * 100)) if atr and current else None

    raw_score, agreement = _raw_signal_score(tech)
    tech["raw_score"] = raw_score
    tech["agreement"] = agreement

    # Provisional stabilized values with NO history (prior_rows=[]). Callers that
    # have access to stored history (single-stock analysis, daily digest) will
    # re-stabilize with the real history and overwrite these.
    from backend.services.signal_stabilizer import stabilize
    prov = stabilize([], {"tech": raw_score, "st": None, "lt": None}, {"tech": agreement})
    tech["score"] = prov["tech_smoothed"]
    tech["signal"] = prov["tech_signal"]
    tech["confidence"] = prov["tech_confidence"]

    return {"technical": tech}


def _fetch_fundamentals(ticker: str) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    ticker_upper = ticker.strip().upper()
    try:
        info = yf.Ticker(ticker_upper).info
    except Exception:
        return {}

    # Forward EPS growth: (forwardEps - trailingEps) / |trailingEps|
    fwd_eps   = _safe(info.get("forwardEps"))
    trail_eps = _safe(info.get("trailingEps"))
    if fwd_eps is not None and trail_eps is not None and abs(trail_eps) > 0.01:
        eps_growth_fwd = round((fwd_eps - trail_eps) / abs(trail_eps), 4)
    else:
        eps_growth_fwd = _safe(info.get("earningsGrowth"))

    fund = {
        "company_name":     info.get("longName") or info.get("shortName"),
        "sector":           info.get("sector"),
        "industry":         info.get("industry"),
        "market_cap":       _safe(info.get("marketCap")),
        "pe_ratio":         _safe(info.get("trailingPE")),
        "forward_pe":       _safe(info.get("forwardPE")),
        "eps":              trail_eps,
        "forward_eps":      fwd_eps,
        "eps_growth":       eps_growth_fwd,
        "revenue":          _safe(info.get("totalRevenue")),
        "revenue_growth":   _safe(info.get("revenueGrowth")),
        "profit_margin":    _safe(info.get("profitMargins")),
        "debt_to_equity":   _norm_de(info.get("debtToEquity")),
        "current_ratio":    _safe(info.get("currentRatio")),
        "return_on_equity": _safe(info.get("returnOnEquity")),
        "dividend_yield":   _safe(info.get("dividendYield")),
        "beta":             _safe(info.get("beta")),
        "short_pct_float":  _safe(info.get("shortPercentOfFloat")),
        "short_ratio":      _safe(info.get("shortRatio")),
    }

    # EPS beat/miss vs analyst consensus (most recent quarter)
    eps_surprise_pct: float | None = None
    try:
        eh = getattr(yf.Ticker(ticker_upper), "earnings_history", None)
        if eh is None:
            try:
                eh = yf.Ticker(ticker_upper).get_earnings_history()
            except Exception:
                pass
        if eh is not None and hasattr(eh, "empty") and not eh.empty:
            surp_col = next((c for c in eh.columns if "surprise" in str(c).lower()), None)
            if surp_col:
                val = eh[surp_col].dropna()
                if len(val) > 0:
                    raw = float(val.iloc[0])
                    eps_surprise_pct = raw if abs(raw) > 1 else raw * 100
    except Exception:
        pass
    fund["eps_surprise_pct"] = _safe(eps_surprise_pct)

    # Corporate actions: stock splits (5-year history + upcoming)
    try:
        import pandas as _pd
        from datetime import date, timedelta
        today  = date.today()
        tk2    = yf.Ticker(ticker_upper)
        splits = tk2.splits
        if splits is not None and not splits.empty:
            cutoff        = today - timedelta(days=5 * 365)
            recent_splits = splits[splits.index.date >= cutoff]
            if not recent_splits.empty:
                last_ratio = float(recent_splits.iloc[-1])
                last_dt    = recent_splits.index[-1].date()
                fund["last_split_date"]  = str(last_dt)
                fund["last_split_ratio"] = round(last_ratio, 4)
                fund["last_split_type"]  = "forward" if last_ratio > 1 else "reverse"
        cal = tk2.calendar
        if isinstance(cal, dict) and "Split Date" in cal:
            sd = cal["Split Date"]
            if not isinstance(sd, list):
                sd = [sd]
            for d in sd:
                if hasattr(d, "date"):
                    d = d.date()
                if isinstance(d, date) and d >= today:
                    fund["upcoming_split_date"] = str(d)
                    break
    except Exception:
        pass

    return fund


def _fetch_institutional(ticker: str) -> dict:
    """Institutional ownership: % held, holder count, top holders with Q-o-Q change."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    ticker_upper = ticker.strip().upper()
    result: dict = {}
    try:
        tk = yf.Ticker(ticker_upper)

        # Major holders summary (index = Breakdown labels, single column = Value)
        mh = tk.major_holders
        if mh is not None and not mh.empty:
            def _mh(key):
                try:
                    return float(mh.loc[key, "Value"])
                except Exception:
                    return None
            result["inst_pct_held"]    = _mh("institutionsPercentHeld")
            result["inst_float_pct"]   = _mh("institutionsFloatPercentHeld")
            result["insider_pct_held"] = _mh("insidersPercentHeld")
            ic = _mh("institutionsCount")
            result["inst_count"]       = int(ic) if ic is not None else None

        # Top 10 institutional holders with Q-o-Q share change
        ih = tk.institutional_holders
        if ih is not None and not ih.empty:
            top = ih.head(10)
            holders = []
            for _, row in top.iterrows():
                holders.append({
                    "holder":      str(row.get("Holder", "")),
                    "shares":      int(row["Shares"]) if "Shares" in row and row["Shares"] == row["Shares"] else None,
                    "pct_held":    round(float(row["pctHeld"]) * 100, 2) if "pctHeld" in row else None,
                    "value":       int(row["Value"]) if "Value" in row and row["Value"] == row["Value"] else None,
                    "pct_change":  round(float(row["pctChange"]) * 100, 2) if "pctChange" in row else None,
                    "date":        str(row["Date Reported"].date()) if "Date Reported" in row else None,
                })
            result["top_holders"] = holders

            # Aggregate net buy/sell signal from top 10 changes
            changes = [h["pct_change"] for h in holders if h["pct_change"] is not None]
            if changes:
                net_buyers  = sum(1 for c in changes if c > 0)
                net_sellers = sum(1 for c in changes if c < 0)
                result["top10_buyers"]  = net_buyers
                result["top10_sellers"] = net_sellers
                result["top10_signal"]  = (
                    "buying"  if net_buyers  > net_sellers + 1 else
                    "selling" if net_sellers > net_buyers  + 1 else
                    "mixed"
                )
    except Exception:
        pass
    return result if result else None


def _fetch_analyst_data(ticker: str, current_price: float | None) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    ticker_upper = ticker.strip().upper()
    try:
        tk_obj = yf.Ticker(ticker_upper)
        info   = tk_obj.info
    except Exception:
        return {}

    KEY_LABEL = {
        "strong_buy":   "Strong Buy",
        "buy":          "Buy",
        "hold":         "Hold",
        "underperform": "Underperform",
        "sell":         "Sell",
    }

    rec_key  = info.get("recommendationKey") or ""
    rec_mean = _safe(info.get("recommendationMean"))
    target_mean   = _safe(info.get("targetMeanPrice"))
    target_median = _safe(info.get("targetMedianPrice"))
    target_high   = _safe(info.get("targetHighPrice"))
    target_low    = _safe(info.get("targetLowPrice"))
    num_analysts  = info.get("numberOfAnalystOpinions")

    upside = None
    if target_mean and current_price and current_price > 0:
        upside = round((target_mean - current_price) / current_price * 100, 2)

    # Individual analyst upgrades / downgrades (last 12 months, up to 20)
    ratings: list[dict] = []
    try:
        import pandas as _pd
        ud = tk_obj.upgrades_downgrades
        if ud is not None and not ud.empty:
            cutoff = _pd.Timestamp.now(tz="UTC") - _pd.DateOffset(months=12)
            if ud.index.tz is None:
                ud.index = ud.index.tz_localize("UTC")
            recent = ud[ud.index >= cutoff].sort_index(ascending=False).head(20)
            for ts, row in recent.iterrows():
                from_g = str(row.get("FromGrade", "")).strip()
                ratings.append({
                    "date":       ts.strftime("%Y-%m-%d"),
                    "firm":       str(row.get("Firm", "")).strip(),
                    "to_grade":   str(row.get("ToGrade", "")).strip(),
                    "from_grade": from_g if from_g else None,
                    "action":     str(row.get("Action", "")).strip(),
                })
    except Exception:
        ratings = []

    return {
        "recommendation":      KEY_LABEL.get(rec_key.lower(), rec_key.replace("_", " ").title()) if rec_key else None,
        "recommendation_key":  rec_key or None,
        "recommendation_mean": rec_mean,
        "num_analysts":        int(num_analysts) if num_analysts else None,
        "target_mean":         target_mean,
        "target_median":       target_median,
        "target_high":         target_high,
        "target_low":          target_low,
        "upside_pct":          upside,
        "ratings":             ratings,
    }


def fetch_price_history(ticker: str, period: str = "3m") -> dict:
    """Return OHLCV bars and metadata for charting."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    yf_period, yf_interval = PERIOD_MAP.get(period, ("3mo", "1d"))
    ticker_upper = ticker.strip().upper()

    try:
        hist = yf.Ticker(ticker_upper).history(
            period=yf_period, interval=yf_interval, auto_adjust=True
        )
    except Exception as exc:
        return {"error": str(exc)}

    if hist.empty:
        return {"error": f"No history data for {ticker_upper}"}

    intraday = yf_interval in ("1m", "5m", "15m", "30m", "1h")
    bars = []
    for ts, row in hist.iterrows():
        bars.append({
            "date":   ts.strftime("%Y-%m-%d %H:%M") if intraday else ts.strftime("%Y-%m-%d"),
            "open":   _safe(float(row["Open"]))   if "Open"   in row else None,
            "high":   _safe(float(row["High"]))   if "High"   in row else None,
            "low":    _safe(float(row["Low"]))    if "Low"    in row else None,
            "close":  _safe(float(row["Close"]))  if "Close"  in row else None,
            "volume": int(row["Volume"])           if "Volume" in row and row["Volume"] == row["Volume"] else 0,
        })

    return {"ticker": ticker_upper, "period": period, "interval": yf_interval, "bars": bars}


def fetch_analyst_snapshot(ticker: str) -> dict:
    """Non-streaming: fundamentals + analyst consensus for a single ticker."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    ticker_upper = ticker.strip().upper()
    try:
        info = yf.Ticker(ticker_upper).info or {}
    except Exception as exc:
        return {"error": str(exc)}

    rec_key = (info.get("recommendationKey") or "").lower()
    rec_label_map = {
        "strong_buy":   "Strong Buy",
        "buy":          "Buy",
        "hold":         "Hold",
        "underperform": "Underperform",
        "sell":         "Sell",
    }

    current_price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
    target_mean   = _safe(info.get("targetMeanPrice"))
    upside_pct: float | None = None
    if current_price and target_mean and current_price > 0:
        upside_pct = round((target_mean - current_price) / current_price * 100, 1)

    return {
        "ticker":              ticker_upper,
        "company_name":        info.get("longName") or info.get("shortName"),
        "sector":              info.get("sector"),
        "industry":            info.get("industryDisp") or info.get("industry"),
        "website":             info.get("website"),
        "description":         (info.get("longBusinessSummary") or "")[:600] or None,
        "employees":           info.get("fullTimeEmployees"),
        # Price
        "current_price":       current_price,
        "high_52w":            _safe(info.get("fiftyTwoWeekHigh")),
        "low_52w":             _safe(info.get("fiftyTwoWeekLow")),
        # Fundamentals
        "market_cap":          _safe(info.get("marketCap")),
        "pe_ratio":            _safe(info.get("trailingPE")),
        "forward_pe":          _safe(info.get("forwardPE")),
        "eps":                 _safe(info.get("trailingEps")),
        "revenue":             _safe(info.get("totalRevenue")),
        "profit_margin":       _safe(info.get("profitMargins")),
        "debt_to_equity":      _norm_de(info.get("debtToEquity")),
        "current_ratio":       _safe(info.get("currentRatio")),
        "return_on_equity":    _safe(info.get("returnOnEquity")),
        "dividend_yield":      _safe(info.get("dividendYield")),
        "beta":                _safe(info.get("beta")),
        # Analyst
        "recommendation":      rec_label_map.get(rec_key) or (rec_key.replace("_", " ").title() if rec_key else None),
        "recommendation_key":  rec_key,
        "recommendation_mean": _safe(info.get("recommendationMean")),
        "num_analysts":        info.get("numberOfAnalystOpinions"),
        "target_mean":         target_mean,
        "target_median":       _safe(info.get("targetMedianPrice")),
        "target_high":         _safe(info.get("targetHighPrice")),
        "target_low":          _safe(info.get("targetLowPrice")),
        "upside_pct":          upside_pct,
    }


def _fetch_peers(ticker: str) -> list[dict]:
    try:
        import yfinance as yf
    except ImportError:
        return []

    ticker_upper = ticker.strip().upper()
    try:
        info = yf.Ticker(ticker_upper).info
        peers_raw = info.get("recommendationKey") or ""
    except Exception:
        return []

    return []


def _ai_analysis(
    ticker: str,
    tech: dict,
    fundamentals: dict,
    include_news: bool,
    analyst: dict | None = None,
    regime: dict | None = None,
    user_id: int | None = None,
    username: str | None = None,
) -> str:
    """Call Claude to generate an AI narrative for the stock."""
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        return ""

    price      = tech.get("current_price", "N/A")
    day_chg    = tech.get("day_change_pct")
    rsi        = tech.get("rsi")
    macd       = tech.get("macd")
    sma50      = tech.get("sma50")
    sma200     = tech.get("sma200")
    vwap       = tech.get("vwap")
    atr        = tech.get("atr")
    atr_pct    = tech.get("atr_pct")
    signal     = tech.get("signal", "hold")
    score      = tech.get("score", 50)
    pe              = fundamentals.get("pe_ratio")
    sector          = fundamentals.get("sector", "Unknown")
    company         = fundamentals.get("company_name", ticker)
    beta            = fundamentals.get("beta")
    eps_surprise    = fundamentals.get("eps_surprise_pct")
    short_pct       = fundamentals.get("short_pct_float")
    short_ratio_val = fundamentals.get("short_ratio")
    rev_growth      = fundamentals.get("revenue_growth")

    analyst_section = ""
    if analyst:
        rec        = analyst.get("recommendation") or "N/A"
        n_analysts = analyst.get("num_analysts")
        target_mean = analyst.get("target_mean")
        upside     = analyst.get("upside_pct")
        analyst_section = f"""
ANALYST DATA:
- Consensus: {rec}{f' ({n_analysts} analysts)' if n_analysts else ''}
- Price Target (mean): {'${:.2f}'.format(target_mean) if target_mean else 'N/A'}{f'  ({upside:+.1f}% upside)' if upside is not None else ''}
- Target Range: {'${:.2f} – ${:.2f}'.format(analyst.get('target_low'), analyst.get('target_high')) if analyst.get('target_low') and analyst.get('target_high') else 'N/A'}"""

    regime_section = ""
    if regime:
        rm = regime.get("regime", "NEUTRAL")
        regime_section = f"""
MARKET REGIME:
- Regime: {rm} (VIX={regime.get('vix', 0):.1f})
- SPY vs SMA50: {regime.get('spy_vs_sma50', 0):+.1f}%  /  vs SMA200: {regime.get('spy_vs_sma200', 0):+.1f}%
- Score multiplier: {regime.get('score_multiplier', 1.0)}× — {"favour tight stops and smaller position in this environment" if rm in ("BEAR","CRISIS") else "standard position sizing applies" if rm == "NEUTRAL" else "trend is supportive, normal sizing"}"""

    vwap_note = ""
    if vwap and price and price != "N/A":
        try:
            rel = "above" if float(price) > vwap else "below"
            vwap_note = f" ({rel} VWAP — {'bullish' if rel == 'above' else 'bearish'} intraday)"
        except Exception:
            pass

    fwd_eps   = fundamentals.get("forward_eps")
    eps_growth = fundamentals.get("eps_growth")
    fwd_eps_str = (
        f"trailing ${trail_eps:.2f} → forward ${fwd_eps:.2f} "
        f"({eps_growth*100:+.1f}% expected growth)"
        if fwd_eps is not None and trail_eps is not None and eps_growth is not None
        else "N/A"
    )
    trail_eps = fundamentals.get("eps")

    prompt = f"""You are a professional equity analyst. Analyze {ticker} ({company}) based on the following data and provide a concise, actionable analysis.

TECHNICAL DATA:
- Current Price: ${price}
- Day Change: {f'{day_chg:+.2f}%' if day_chg is not None else 'N/A'}
- RSI (14): {rsi if rsi is not None else 'N/A'}
- MACD: {macd if macd is not None else 'N/A'}
- 50-day SMA: {sma50 if sma50 is not None else 'N/A'}
- 200-day SMA: {sma200 if sma200 is not None else 'N/A'}
- VWAP: {f'${vwap:.2f}' if vwap else 'N/A'}{vwap_note}
- ATR (14): {f'${atr:.2f} ({atr_pct:.1f}% of price)' if atr and atr_pct else 'N/A'}
- Momentum Score: {score}/100
- Signal: {signal.upper()}

FUNDAMENTAL DATA:
- Sector: {sector}
- P/E Ratio: {pe if pe is not None else 'N/A'}
- Beta: {beta if beta is not None else 'N/A'}
- Profit Margin: {f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get('profit_margin') else 'N/A'}
- Revenue Growth (YoY): {f"{rev_growth*100:.1f}%" if rev_growth is not None else 'N/A'}
- EPS (forward vs trailing): {fwd_eps_str}
- EPS Surprise (last quarter): {f"{eps_surprise:+.1f}% vs estimate" if eps_surprise is not None else 'N/A'}
- Short Interest: {f"{short_pct*100:.1f}% of float  ({short_ratio_val:.1f} days to cover)" if short_pct is not None else 'N/A'}
{analyst_section}{regime_section}
Provide a structured analysis with:
1. **Summary** (2-3 sentences on current situation and market regime context)
2. **Technical Outlook** (what the indicators tell us, including VWAP position)
3. **Analyst Consensus** (how analyst targets compare to current price)
4. **Key Risks** (2-3 bullet points)
5. **Trade Setup** (entry zone, target, stop-loss = 1.5× ATR below entry if ATR is available, size adjusted for current regime)

Keep it concise and actionable. No fluff."""

    _MODEL = "claude-sonnet-4-6"
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from database import log_token_usage
            log_token_usage(
                user_id=user_id,
                username=username,
                feature="stock_analysis",
                model=_MODEL,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                ticker=ticker,
            )
        except Exception as log_exc:
            logger.warning("Token usage logging failed: %s", log_exc)
        return response.content[0].text
    except Exception as e:
        logger.warning("AI analysis failed: %s", e)
        return ""


def _detect_patterns(ticker: str) -> list[dict]:
    """
    Detect key technical chart patterns from 1-year daily data.
    Returns a list of pattern dicts: {name, signal, description, strength}.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker.upper()).history(period="1y", interval="1d")
        if len(hist) < 50:
            return []
        closes = hist["Close"].tolist()
    except Exception:
        return []

    patterns = []

    # Golden Cross / Death Cross (SMA50 vs SMA200)
    if len(closes) >= 200:
        sma50_now   = sum(closes[-50:]) / 50
        sma200_now  = sum(closes[-200:]) / 200
        sma50_prev  = sum(closes[-51:-1]) / 50
        sma200_prev = sum(closes[-201:-1]) / 200
        if sma50_prev <= sma200_prev and sma50_now > sma200_now:
            patterns.append({
                "name": "Golden Cross",
                "signal": "bullish",
                "description": "SMA50 just crossed above SMA200 — historically a strong long-term buy signal.",
                "strength": "strong",
            })
        elif sma50_prev >= sma200_prev and sma50_now < sma200_now:
            patterns.append({
                "name": "Death Cross",
                "signal": "bearish",
                "description": "SMA50 just crossed below SMA200 — often signals a prolonged downtrend.",
                "strength": "strong",
            })
        elif sma50_now > sma200_now:
            patterns.append({
                "name": "Above 200-Day MA",
                "signal": "bullish",
                "description": f"Price is in a long-term uptrend (SMA50 ${sma50_now:.2f} > SMA200 ${sma200_now:.2f}).",
                "strength": "moderate",
            })
        else:
            patterns.append({
                "name": "Below 200-Day MA",
                "signal": "bearish",
                "description": f"Price is in a long-term downtrend (SMA50 ${sma50_now:.2f} < SMA200 ${sma200_now:.2f}).",
                "strength": "moderate",
            })

    # RSI Extremes
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas[-14:]]
        losses = [abs(min(d, 0)) for d in deltas[-14:]]
        avg_g  = sum(gains) / 14
        avg_l  = sum(losses) / 14
        rsi = (100 - 100 / (1 + avg_g / avg_l)) if avg_l > 0 else 100
        if rsi < 30:
            patterns.append({
                "name": "RSI Oversold",
                "signal": "bullish",
                "description": f"RSI at {rsi:.1f} — deeply oversold, potential mean-reversion bounce.",
                "strength": "moderate",
            })
        elif rsi > 70:
            patterns.append({
                "name": "RSI Overbought",
                "signal": "bearish",
                "description": f"RSI at {rsi:.1f} — overbought territory, elevated pullback risk.",
                "strength": "moderate",
            })

    # MACD Crossover (last 3 bars)
    if len(closes) >= 35:
        def ema(data, n):
            k = 2 / (n + 1)
            r = [data[0]]
            for v in data[1:]:
                r.append(v * k + r[-1] * (1 - k))
            return r
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        offset = 25
        macd_line = [ema12[i] - ema26[i] for i in range(offset, len(closes))]
        if len(macd_line) >= 12:
            sig_line = ema(macd_line, 9)
            hist_vals = [macd_line[i] - sig_line[i] for i in range(len(sig_line))]
            if len(hist_vals) >= 2:
                if hist_vals[-2] < 0 and hist_vals[-1] > 0:
                    patterns.append({
                        "name": "MACD Bullish Crossover",
                        "signal": "bullish",
                        "description": "MACD histogram just crossed above signal line — short-term momentum turning positive.",
                        "strength": "moderate",
                    })
                elif hist_vals[-2] > 0 and hist_vals[-1] < 0:
                    patterns.append({
                        "name": "MACD Bearish Crossover",
                        "signal": "bearish",
                        "description": "MACD histogram just crossed below signal line — short-term momentum turning negative.",
                        "strength": "moderate",
                    })

    # Bollinger Band Squeeze (low volatility → potential breakout)
    if len(closes) >= 20:
        sma20 = sum(closes[-20:]) / 20
        std20 = (sum((c - sma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
        bb_width = (2 * std20 * 2) / sma20 * 100  # band width as % of price
        # Historical average width (use prior 20 bars)
        if len(closes) >= 40:
            sma20_p  = sum(closes[-40:-20]) / 20
            std20_p  = (sum((c - sma20_p) ** 2 for c in closes[-40:-20]) / 20) ** 0.5
            bb_width_p = (2 * std20_p * 2) / sma20_p * 100
            if bb_width < bb_width_p * 0.7:
                patterns.append({
                    "name": "Bollinger Squeeze",
                    "signal": "neutral",
                    "description": "Bollinger Bands are tightening — a large move (breakout or breakdown) is likely imminent.",
                    "strength": "moderate",
                })

    # 52-Week High proximity (within 2%)
    high_52w = max(closes[-252:] if len(closes) >= 252 else closes)
    current  = closes[-1]
    if current >= high_52w * 0.98:
        patterns.append({
            "name": "Near 52-Week High",
            "signal": "bullish",
            "description": f"Price ${current:.2f} is within 2% of its 52-week high ${high_52w:.2f} — strong relative strength.",
            "strength": "moderate",
        })
    elif current <= min(closes[-252:] if len(closes) >= 252 else closes) * 1.05:
        patterns.append({
            "name": "Near 52-Week Low",
            "signal": "bearish",
            "description": f"Price ${current:.2f} is near its 52-week low — potential value trap or distressed situation.",
            "strength": "moderate",
        })

    return patterns


def _apply_stabilization(ticker: str, tech: dict, result: dict) -> None:
    """
    Smooth today's raw tech/ST/LT scores against stored history, derive
    hysteresis-gated signals + honest confidence, write the values back into
    `tech`/`result`, and persist today's row.

    All DB access is wrapped defensively: if history is unavailable the caller
    still gets the provisional (stateless) values already sitting in `tech`.
    """
    try:
        from datetime import date
        from backend.services.signal_stabilizer import stabilize
        import database as db

        st = result.get("st_analysis") or {}
        lt = result.get("lt_analysis") or {}
        raw_scores = {
            "tech": tech.get("raw_score_adj", tech.get("raw_score", 50.0)),
            "st": st.get("score"),
            "lt": lt.get("score"),
        }
        agreements = {"tech": tech.get("agreement", 0.5)}

        try:
            prior_rows = db.get_recent_signal_history(ticker, lookback_days=10, before=date.today())
        except Exception:
            prior_rows = []

        row = stabilize(prior_rows, raw_scores, agreements)

        # Write stabilized tech values back (score shown = smoothed score).
        tech["score"] = row["tech_smoothed"]
        tech["signal"] = row["tech_signal"]
        tech["confidence"] = row["tech_confidence"]
        tech["signal_changed"] = row.get("tech_changed", False)

        # Overlay smoothed ST/LT signals + scores so the ranking is stable too.
        if result.get("st_analysis") and row.get("st_smoothed") is not None:
            result["st_analysis"]["score"] = row["st_smoothed"]
            result["st_analysis"]["signal"] = row["st_signal"]
            result["st_analysis"]["signal_changed"] = row.get("st_changed", False)
        if result.get("lt_analysis") and row.get("lt_smoothed") is not None:
            result["lt_analysis"]["score"] = row["lt_smoothed"]
            result["lt_analysis"]["signal"] = row["lt_signal"]
            result["lt_analysis"]["signal_changed"] = row.get("lt_changed", False)

        try:
            db.upsert_signal_history(ticker, date.today(), row)
        except Exception as exc:
            logger.warning("signal_history upsert failed for %s: %s", ticker, exc)
    except Exception as exc:
        logger.warning("Stabilization skipped for %s: %s", ticker, exc)


def analyze_stock_sync(
    ticker: str,
    mode: str,
    time_period: str,
    indicators: list[str],
    include_news: bool,
    include_fundamentals: bool,
    include_peers: bool,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal_period: int = 9,
    user_id: int | None = None,
    username: str | None = None,
) -> dict:
    period_str, interval = PERIOD_MAP.get(time_period, ("3mo", "1d"))

    result: dict = {"ticker": ticker.upper(), "mode": mode, "time_period": time_period,
                    "requested_indicators": indicators}

    # Always score on 3-month daily bars so signal/score are timeframe-consistent.
    # The chart displays the user-selected period; scoring uses a fixed baseline.
    SCORE_PERIOD, SCORE_INTERVAL = "3mo", "1d"
    score_result = _fetch_stock_data(
        ticker, SCORE_PERIOD, SCORE_INTERVAL, indicators,
        rsi_period=rsi_period, bb_period=bb_period, bb_std=bb_std,
        macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal_period,
    )
    if "error" in score_result:
        result["error"] = score_result["error"]
        return result

    tech = score_result["technical"]

    # If the user selected a different period, overlay chart-specific price fields
    # (current price, day/week change, 52w range, volume) from the selected period
    # so those display correctly, but keep indicators/score from 3m daily.
    if period_str != SCORE_PERIOD or interval != SCORE_INTERVAL:
        chart_result = _fetch_stock_data(
            ticker, period_str, interval, [],   # no indicators needed for chart overlay
            rsi_period=rsi_period, bb_period=bb_period, bb_std=bb_std,
            macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal_period,
        )
        if "technical" in chart_result:
            ct = chart_result["technical"]
            for field in ("current_price", "prev_close", "day_change_pct",
                          "last_volume", "avg_volume", "vol_ratio"):
                if ct.get(field) is not None:
                    tech[field] = ct[field]

    # ── Market regime — fold into the RAW score as a small additive tilt ──────
    # (The old code multiplied the whole score and re-derived the signal every
    # day, so a daily VIX move could flip the call. Now regime nudges the raw
    # score by at most a few points and the tilt is then absorbed by smoothing.)
    regime: dict | None = None
    regime_tilt = 0.0
    try:
        from backend.services.regime_detector import get_market_regime
        regime = get_market_regime()
        multiplier = float(regime.get("score_multiplier", 1.0))
        regime_tilt = round(min(max((multiplier - 1.0) * 40.0, -6.0), 6.0), 2)
        tech["regime_multiplier"] = multiplier
        tech["regime_tilt"] = regime_tilt
    except Exception:
        pass

    # Regime-adjusted raw score fed to the stabilizer (final signal derived later,
    # once ST/LT scores are known, so the whole day is persisted in one row).
    tech["raw_score_adj"] = round(min(max(tech.get("raw_score", 50.0) + regime_tilt, 0), 100), 1)

    result["technical"] = tech
    result["regime"]    = regime

    current_price = tech.get("current_price")

    if include_fundamentals:
        fund = _fetch_fundamentals(ticker)
        result["fundamentals"] = fund
        result["company_name"] = fund.get("company_name")
    else:
        result["fundamentals"] = None

    # Analyst data is always fetched when fundamentals are on (same .info call, yf caches it)
    if include_fundamentals:
        result["analyst"] = _fetch_analyst_data(ticker, current_price)
        result["institutional"] = _fetch_institutional(ticker)
        # SEC EDGAR Form 4 insider transactions
        try:
            from backend.services.sec_edgar import get_insider_transactions, summarise_insider_transactions, get_recent_filings
            txns = get_insider_transactions(ticker, days=90, max_filings=10)
            result["sec_insider_transactions"] = txns
            result["sec_insider_summary"]      = summarise_insider_transactions(txns)
            result["sec_recent_filings"]       = get_recent_filings(ticker)
        except Exception:
            result["sec_insider_transactions"] = []
            result["sec_insider_summary"]      = None
            result["sec_recent_filings"]       = []
    else:
        result["analyst"] = None
        result["institutional"] = None
        result["sec_insider_transactions"] = []
        result["sec_insider_summary"]      = None
        result["sec_recent_filings"]       = []

    if include_peers:
        result["peer_comparison"] = _fetch_peers(ticker)

    # ── Position sizing using ATR already computed in tech ────────────────────
    atr_pct = tech.get("atr_pct")
    if atr_pct and current_price:
        try:
            from backend.services.position_sizer import compute_position_size
            result["position_size"] = compute_position_size(
                entry_price=current_price,
                atr_pct=atr_pct,
                score=int(tech.get("score", 50)),
                regime_multiplier=float((regime or {}).get("score_multiplier", 1.0)),
            )
        except Exception:
            result["position_size"] = None
    else:
        result["position_size"] = None

    # Technical pattern detection (always, uses 1-year history internally)
    try:
        result["patterns"] = _detect_patterns(ticker)
    except Exception:
        result["patterns"] = []

    # ── RS Rating (Relative Strength vs S&P 500) ──────────────────────────────
    rs_data: dict = {"rs_score": 50}
    try:
        from backend.services.rs_rating import compute_rs_rating
        rs_data = compute_rs_rating(ticker)
        result["rs_rating"] = rs_data
    except Exception:
        result["rs_rating"] = rs_data

    rs_score = rs_data.get("rs_score", 50)

    # ── Multi-timeframe weekly confirmation ───────────────────────────────────
    weekly: dict = {}
    try:
        weekly = _compute_weekly_confirmation(ticker)
        result["weekly"] = weekly
    except Exception:
        result["weekly"] = {}

    # ── Short-term score (1–4 weeks, technical + RS) ──────────────────────────
    try:
        result["st_analysis"] = _compute_st_score(tech, rs_score, weekly)
    except Exception:
        result["st_analysis"] = None

    # ── Long-term score (3–12 months, fundamentals + RS + trend) ─────────────
    if include_fundamentals and result.get("fundamentals"):
        try:
            result["lt_analysis"] = _compute_lt_score(tech, result["fundamentals"], rs_score)
        except Exception:
            result["lt_analysis"] = None
    else:
        result["lt_analysis"] = None

    # ── Stabilize tech/ST/LT against stored history, then persist today ───────
    # Smoothing + hysteresis live here so the signal only moves on a sustained
    # trend, and confidence reflects real conviction — not a near-boundary flip.
    _apply_stabilization(ticker, tech, result)

    # ── Institutional cross-sectional factor decomposition ────────────────────
    # Rank this ticker's factor exposures (momentum/value/quality/growth/low-vol/
    # revisions) against the latest universe distribution the digest recorded.
    try:
        from backend.services import factor_engine as fe
        import database as db
        try:
            uni = db.get_latest_factor_universe_stats()
        except Exception:
            uni = None

        # Financial-health signals (Piotroski, Altman-Z, ROIC, FCF) + analyst
        # estimate-revision momentum — new institutional factors for the engine.
        health: dict = {}
        if include_fundamentals:
            try:
                from backend.services.financial_health import (
                    get_financial_health, revision_score_from_ratings,
                )
                health = get_financial_health(ticker)
                rev = revision_score_from_ratings((result.get("analyst") or {}).get("ratings"))
                if rev is not None:
                    health["revision_score"] = rev
                result["financial_health"] = health
            except Exception as exc:
                logger.warning("financial_health failed for %s: %s", ticker, exc)
                result["financial_health"] = None
        else:
            result["financial_health"] = None

        data = fe.merge_factor_data(
            tech, result.get("fundamentals"), result.get("analyst"), rs_score
        )
        data.update({k: v for k, v in (health or {}).items() if v is not None})
        fa = fe.analyze(data, universe_stats=(uni or {}).get("stats"))
        fa["universe_date"] = str(uni["as_of"]) if uni else None
        fa["universe_n"] = (uni or {}).get("n_stocks")
        fa["basis"] = "cross-sectional" if uni else "static-anchors"
        result["factor_analysis"] = fa

        # ── Valuation (fair value, expected return) + actionable trade plan ────
        try:
            from backend.services import valuation as val
            q_pct = (fa.get("families", {}).get("quality") or {}).get("percentile")
            valn = val.estimate(data, quality_pct=q_pct)
            result["valuation"] = valn
            comp = fa.get("composite", 50)
            sig = "buy" if comp >= 65 else "watch" if comp >= 52 else "hold" if comp >= 38 else "sell"
            result["trade_plan"] = val.build_trade_plan(data, valn, fa.get("conviction"), sig)
        except Exception as exc:
            logger.warning("Valuation/trade plan failed for %s: %s", ticker, exc)
            result["valuation"] = None
            result["trade_plan"] = None
    except Exception as exc:
        logger.warning("Factor analysis failed for %s: %s", ticker, exc)
        result["factor_analysis"] = None
        result["valuation"] = None
        result["trade_plan"] = None

    if mode == "api":
        fund_for_ai    = result.get("fundamentals") or {}
        analyst_for_ai = result.get("analyst") or {}
        result["ai_analysis"] = _ai_analysis(
            ticker, tech, fund_for_ai, include_news, analyst_for_ai,
            regime=regime, user_id=user_id, username=username,
        )

    return result


async def stream_stock_analysis(
    ticker: str,
    mode: str,
    time_period: str,
    indicators: list[str],
    include_news: bool,
    include_fundamentals: bool,
    include_peers: bool,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal_period: int = 9,
    force_refresh: bool = False,
    user_id: int | None = None,
    username: str | None = None,
):
    """Async generator that yields SSE-formatted bytes."""

    def _event(obj: dict) -> bytes:
        return f"data: {json.dumps(obj)}\n\n".encode()

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key: str | None = None
    if not force_refresh:
        try:
            from backend.services.cache_service import make_cache_key, cache_get
            cache_key = make_cache_key(
                ticker, mode, time_period, indicators,
                rsi_period, bb_period, bb_std,
                macd_fast, macd_slow, macd_signal_period,
                include_news, include_fundamentals, include_peers,
            )
            cached = cache_get(cache_key)
            if cached:
                age_min = (cached.get("cache_age_seconds") or 0) // 60
                yield _event({"type": "progress", "message": f"Loaded from cache ({age_min}m ago)"})
                yield _event({"type": "result", "data": cached})
                yield _event({"type": "done"})
                return
        except Exception as exc:
            logger.warning("Cache lookup failed: %s", exc)
            cache_key = None

    if force_refresh or cache_key is None:
        try:
            from backend.services.cache_service import make_cache_key
            cache_key = make_cache_key(
                ticker, mode, time_period, indicators,
                rsi_period, bb_period, bb_std,
                macd_fast, macd_slow, macd_signal_period,
                include_news, include_fundamentals, include_peers,
            )
        except Exception:
            cache_key = None

    yield _event({"type": "progress", "message": f"Fetching data for {ticker.upper()}..."})

    q: queue.SimpleQueue = queue.SimpleQueue()

    def _run():
        try:
            result = analyze_stock_sync(
                ticker, mode, time_period, indicators,
                include_news, include_fundamentals, include_peers,
                rsi_period=rsi_period, bb_period=bb_period, bb_std=bb_std,
                macd_fast=macd_fast, macd_slow=macd_slow, macd_signal_period=macd_signal_period,
                user_id=user_id, username=username,
            )
            q.put(("result", result))
        except Exception as e:
            q.put(("error", str(e)))

    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(_run)

    import asyncio
    loop = asyncio.get_event_loop()

    while True:
        try:
            kind, payload = await loop.run_in_executor(None, lambda: q.get(timeout=60))
        except Exception:
            yield _event({"type": "error", "message": "Analysis timed out."})
            break

        if kind == "error":
            yield _event({"type": "error", "message": payload})
            break

        if kind == "result":
            if payload.get("error"):
                yield _event({"type": "error", "message": payload["error"]})
            else:
                if mode == "api" and payload.get("ai_analysis"):
                    yield _event({"type": "progress", "message": "AI analysis complete."})
                payload["cached"] = False
                payload["cache_age_seconds"] = 0
                if cache_key:
                    try:
                        from backend.services.cache_service import cache_set
                        cache_set(cache_key, ticker, mode, payload)
                    except Exception as exc:
                        logger.warning("Cache write failed: %s", exc)
                yield _event({"type": "result", "data": payload})
            break

    yield _event({"type": "done"})
    executor.shutdown(wait=False)
