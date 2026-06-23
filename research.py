"""
Research mode — ranks today's top picks from the configured asset universe.

Modes (set in config.yaml → research.mode):
  free   Uses yfinance for live prices + momentum scoring. No API key needed.
  api    Uses Claude + live web search for deeper analysis. Requires ANTHROPIC_API_KEY.

Usage:
  python3 research.py
  python3 research.py --top 10
  python3 research.py --stocks-only
  python3 research.py --crypto-only
  python3 research.py --mode free     # override config
  python3 research.py --mode api
"""

import argparse
import io
import json
import logging
import os
import smtplib
from datetime import datetime
from email.encoders import encode_base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

from sentiment import get_social_sentiment

# ---------------------------------------------------------------------------
# Live weight loading — price-based factors (backtestable)
# ---------------------------------------------------------------------------
# The 8 price/volume factors below can be optimised via historical backtest.
# Their weights are loaded from DB if a recent backtest exists; otherwise
# the hardcoded defaults below are used.
# The 5 fundamental factors keep fixed weights at all times (can't backtest them).

_TESTABLE_FACTOR_TOTAL = 0.69   # sum of live weights for the 8 price factors
_FIXED_FACTOR_WEIGHTS = {
    "earn_qual_scr": 0.07,
    "short_scr":     0.04,
    "sent_scr":      0.05,
    "analyst_score": 0.10,
    "insider_score": 0.05,
}
_DEFAULT_PRICE_WEIGHTS = {        # normalised to sum to 1.0
    "mom_3m":    0.2609,
    "mom_1m":    0.2029,
    "mom_1w":    0.1304,
    "mom_1d":    0.0290,
    "vol_scr":   0.1304,
    "pos_scr":   0.0435,
    "rs_spy":    0.1014,
    "rs_sector": 0.1014,
}

_live_weights: dict | None = None          # cached live weights
_live_weights_loaded_at: float = 0.0       # epoch seconds

def _get_live_weights() -> dict:
    """Return scaled price-factor weights (each already multiplied by 0.69).
    Refreshes from DB at most once per 24 h."""
    import time
    global _live_weights, _live_weights_loaded_at
    if _live_weights is not None and (time.time() - _live_weights_loaded_at) < 86_400:
        return _live_weights

    w = None
    try:
        from database import get_optimal_weights
        raw = get_optimal_weights()   # normalised to sum to 1.0 across 8 factors
        if raw and all(k in raw for k in _DEFAULT_PRICE_WEIGHTS):
            # Validate: weights must sum to roughly 1.0
            total = sum(raw.values())
            if 0.85 <= total <= 1.15:
                w = {k: raw[k] * _TESTABLE_FACTOR_TOTAL for k in raw}
                logger.info("Loaded backtest-optimised weights from DB (sum_raw=%.3f)", total)
    except Exception as exc:
        logger.debug("Could not load DB weights: %s", exc)

    if w is None:
        w = {k: v * _TESTABLE_FACTOR_TOTAL for k, v in _DEFAULT_PRICE_WEIGHTS.items()}

    _live_weights = w
    _live_weights_loaded_at = time.time()
    return w

import pytz
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_universe(config: dict, stocks_only: bool, crypto_only: bool) -> tuple[list, list]:
    stocks = config["assets"]["stocks"] if not crypto_only else []
    crypto = config["assets"]["crypto"] if not stocks_only else []
    return stocks, crypto


# ---------------------------------------------------------------------------
# Technical indicator helpers (shared with free-mode scoring)
# ---------------------------------------------------------------------------

def _rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0)   for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_g  = sum(gains)  / period
    avg_l  = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 2)


def _sma(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9
          ) -> tuple[float | None, float | None, float | None]:
    def _ema(data: list, n: int) -> list:
        k = 2 / (n + 1)
        out = [data[0]]
        for v in data[1:]:
            out.append(v * k + out[-1] * (1 - k))
        return out
    if len(closes) < slow:
        return None, None, None
    ef = _ema(closes, fast)
    es = _ema(closes, slow)
    off = slow - 1
    ml  = [a - b for a, b in zip(ef[off:], es[off:])]
    if len(ml) < signal:
        return round(ml[-1], 4) if ml else None, None, None
    sl  = _ema(ml, signal)
    return round(ml[-1], 4), round(sl[-1], 4), round(ml[-1] - sl[-1], 4)


def _bollinger(closes: list, period: int = 20, mult: float = 2.0
               ) -> tuple[float | None, float | None, float | None]:
    if len(closes) < period:
        return None, None, None
    win = closes[-period:]
    mid = sum(win) / period
    std = (sum((x - mid) ** 2 for x in win) / period) ** 0.5
    return round(mid + mult * std, 4), round(mid - mult * std, 4), round(mid, 4)


def _vwap(highs: list, lows: list, closes: list, volumes: list) -> float | None:
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n == 0:
        return None
    tp_vol  = sum(((highs[i] + lows[i] + closes[i]) / 3) * volumes[i] for i in range(n))
    tot_vol = sum(volumes[:n])
    return round(tp_vol / tot_vol, 4) if tot_vol else None


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> float | None:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs = [max(highs[i] - lows[i],
               abs(highs[i]  - closes[i - 1]),
               abs(lows[i]   - closes[i - 1]))
           for i in range(1, n)]
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period, 4)


# ---------------------------------------------------------------------------
# FREE MODE — yfinance, no API key required
# ---------------------------------------------------------------------------

def _yf_ticker(symbol: str, asset_type: str) -> str:
    """Convert crypto symbols to yfinance format (BTC → BTC-USD)."""
    return f"{symbol}-USD" if asset_type == "crypto" else symbol


# Maps yfinance sector string → sector ETF ticker for relative-strength comparison
_SECTOR_ETF: dict[str, str] = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Energy":                 "XLE",
    "Healthcare":             "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples":       "XLP",
    "Industrials":            "XLI",
    "Materials":              "XLB",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
    "Communication Services": "XLC",
    "Basic Materials":        "XLB",
}


def _fetch_benchmark_returns() -> dict[str, float]:
    """
    Pre-fetch 3-month returns for SPY + all sector ETFs in one batch download.
    Returns a dict keyed by ETF ticker (e.g. {"SPY": 8.2, "XLK": 12.1, ...}).
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    etfs = list({"SPY"} | set(_SECTOR_ETF.values()))
    returns: dict[str, float] = {}
    try:
        raw = yf.download(etfs, period="3mo", interval="1d",
                          auto_adjust=True, progress=False, threads=False)
        closes = raw["Close"] if "Close" in raw else raw
        for etf in etfs:
            try:
                col = closes[etf].dropna()
                if len(col) >= 2:
                    returns[etf] = float((col.iloc[-1] - col.iloc[0]) / col.iloc[0] * 100)
            except Exception:
                pass
    except Exception:
        # Fallback: fetch SPY alone
        try:
            import yfinance as yf
            hist = yf.Ticker("SPY").history(period="3mo", interval="1d", auto_adjust=True)
            col  = hist["Close"].dropna()
            if len(col) >= 2:
                returns["SPY"] = float((col.iloc[-1] - col.iloc[0]) / col.iloc[0] * 100)
        except Exception:
            pass
    return returns


def _fetch_spy_return(period_days: int = 63) -> float:
    """Return SPY's 3-month return (kept for backward compatibility)."""
    return _fetch_benchmark_returns().get("SPY", 0.0)


_track_cache: dict = {}
_track_cache_at: float = 0.0

def _get_track_record_scores() -> dict:
    """Cache the per-ticker track-record dict for 1 hour."""
    import time
    global _track_cache, _track_cache_at
    if _track_cache is not None and (time.time() - _track_cache_at) < 3_600:
        return _track_cache
    try:
        from database import get_track_record_scores
        _track_cache    = get_track_record_scores()
        _track_cache_at = time.time()
    except Exception:
        _track_cache = {}
    return _track_cache


def _score_asset(asset: dict, spy_return_3m: float,
                 benchmark_returns: dict | None = None,
                 regime: dict | None = None) -> dict | None:
    """
    Multi-factor composite score (0-100), regime-adjusted.

    Weights:
      18%  3-month momentum (Jegadeesh & Titman)
      14%  1-month momentum
       9%  1-week momentum
       2%  1-day change
       9%  volume surge
       7%  relative strength vs SPY
       7%  relative strength vs sector ETF
       3%  52-week position (near high = breakout zone)
       7%  earnings quality (fwd EPS growth + beat/miss vs estimate)
       4%  short interest momentum (squeeze potential)
       5%  social sentiment
      10%  analyst consensus + price target
       5%  insider / institutional ownership signal
    Earnings proximity penalty applied after composite (−5 to −15 pts).
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    import time as _time
    from datetime import date, timedelta

    bm = benchmark_returns or {}
    symbol = _yf_ticker(asset["ticker"], asset["type"])

    # ── Live price cache (Polygon.io) — skip yfinance fast_info if fresh ───────
    _cached_current: float | None    = None
    _cached_prev_close: float | None = None
    try:
        from backend.services.polygon_client import price_cache as _pc
        _cq = _pc.get(asset["ticker"])
        if _cq and _cq.price:
            import time as _t
            if _t.time() - _cq.updated_at < 300:
                _cached_current    = _cq.price
                _cached_prev_close = _cq.prev_close
    except Exception:
        pass

    # Retry up to 3 times with backoff to handle Yahoo Finance rate limits / crumb errors
    for _attempt in range(3):
        try:
            tk = yf.Ticker(symbol)
            _ = tk.fast_info  # probe — raises immediately if rate-limited
            break
        except Exception as _e:
            if _attempt == 2:
                logger.warning("Rate-limited on %s after 3 attempts: %s", symbol, _e)
                return None
            _time.sleep(2 ** _attempt)  # 1s, 2s backoff
    else:
        return None

    # ── Fast price data ────────────────────────────────────────────────────────
    try:
        fi = tk.fast_info
        current    = _cached_current    or getattr(fi, "last_price",                 None)
        prev_close = _cached_prev_close or getattr(fi, "previous_close",             None)
        high_52w   = getattr(fi, "year_high",                  None)
        low_52w    = getattr(fi, "year_low",                   None)
        avg_volume = getattr(fi, "three_month_average_volume", None)
        last_vol   = getattr(fi, "last_volume",                None)
    except Exception as exc:
        logger.debug("fast_info failed %s: %s", symbol, exc)
        return None

    if not current or not prev_close:
        return None

    # ── 3-month history for multi-timeframe returns + technical indicators ───────
    try:
        hist    = tk.history(period="3mo", interval="1d", auto_adjust=True)
        closes  = [float(v) for v in hist["Close"].dropna().tolist()]  if not hist.empty else []
        highs   = [float(v) for v in hist["High"].dropna().tolist()]   if not hist.empty and "High"   in hist else []
        lows    = [float(v) for v in hist["Low"].dropna().tolist()]    if not hist.empty and "Low"    in hist else []
        volumes = [float(v) for v in hist["Volume"].dropna().tolist()] if not hist.empty and "Volume" in hist else []
    except Exception:
        closes = highs = lows = volumes = []

    day_chg_pct   = (current - prev_close) / prev_close * 100
    week_chg_pct  = (current - closes[-5])  / closes[-5]  * 100 if len(closes) >= 6  else day_chg_pct
    month_chg_pct = (current - closes[-21]) / closes[-21] * 100 if len(closes) >= 22 else day_chg_pct
    qtr_chg_pct   = (current - closes[0])   / closes[0]   * 100 if len(closes) >= 10 else day_chg_pct

    vol_ratio = (last_vol / avg_volume) if (last_vol and avg_volume and avg_volume > 0) else 1.0

    # 30-day volume trend vs prior 30 days — institutional accumulation/distribution signal
    vol_30d_avg: float | None   = None
    vol_prior_avg: float | None = None
    vol_trend_pct: float | None = None
    vol_signal: str | None      = None
    if len(volumes) >= 30:
        vol_30d_avg = round(sum(volumes[-30:]) / 30, 0)
        if len(volumes) >= 60:
            vol_prior_avg = round(sum(volumes[-60:-30]) / 30, 0)
            if vol_prior_avg > 0:
                vol_trend_pct = round((vol_30d_avg - vol_prior_avg) / vol_prior_avg * 100, 1)
                price_up = month_chg_pct > 0
                if vol_trend_pct > 20:
                    vol_signal = "accumulation" if price_up else "distribution"
                elif vol_trend_pct < -20:
                    vol_signal = "contraction"
                else:
                    vol_signal = "neutral"

    pos_52w = (
        (current - low_52w) / (high_52w - low_52w)
        if (high_52w and low_52w and high_52w != low_52w) else 0.5
    )

    # ── Fundamentals + earnings calendar (one .info call covers everything) ────
    eps_growth          = 0.0
    rev_growth          = 0.0
    eps_surprise_pct    = 0.0
    short_pct_float     = 0.0
    short_ratio         = 0.0
    stock_sector        = ""
    earnings_flag       = None
    today               = date.today()
    last_split_date     = None
    last_split_ratio    = None
    last_split_type     = None
    upcoming_split_date = None
    split_score_adj     = 0
    target_mean_price   = 0.0
    recommendation_mean = 3.0   # 1=strong_buy … 5=sell
    num_analysts        = 0
    recommendation_key  = "Hold"

    try:
        info             = tk.info
        fwd_eps          = float(info.get("forwardEps")          or 0)
        trail_eps        = float(info.get("trailingEps")         or 0)
        if abs(trail_eps) > 0.01 and fwd_eps != 0:
            eps_growth = (fwd_eps - trail_eps) / abs(trail_eps)
        else:
            eps_growth = float(info.get("earningsGrowth")        or 0)
        rev_growth          = float(info.get("revenueGrowth")           or 0)
        short_pct_float     = float(info.get("shortPercentOfFloat")     or 0)
        short_ratio         = float(info.get("shortRatio")              or 0)
        stock_sector        = info.get("sector") or ""
        target_mean_price   = float(info.get("targetMeanPrice")         or 0)
        recommendation_mean = float(info.get("recommendationMean")      or 3)
        num_analysts        = int(info.get("numberOfAnalystOpinions")   or 0)
        rec_raw             = info.get("recommendationKey") or "hold"
        recommendation_key  = rec_raw.replace("_", " ").title()

        week_end = today + timedelta(days=7)
        cal = tk.calendar
        if isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if not isinstance(dates, list):
                dates = [dates]
            for d in dates:
                if hasattr(d, "date"):
                    d = d.date()
                if isinstance(d, date) and today <= d <= week_end:
                    earnings_flag = str(d)
                    break
        # Upcoming announced split
        if isinstance(cal, dict) and "Split Date" in cal:
            sd = cal["Split Date"]
            if not isinstance(sd, list):
                sd = [sd]
            for d in sd:
                if hasattr(d, "date"):
                    d = d.date()
                if isinstance(d, date) and d >= today:
                    upcoming_split_date = str(d)
                    break
    except Exception:
        pass

    # ── Individual analyst ratings (upgrades/downgrades, last 12 months) ──────
    analyst_ratings: list = []
    if asset["type"] == "stock":
        try:
            import pandas as _pd
            ud = tk.upgrades_downgrades
            if ud is not None and not ud.empty:
                cutoff = _pd.Timestamp.now(tz="UTC") - _pd.DateOffset(months=12)
                if ud.index.tz is None:
                    ud.index = ud.index.tz_localize("UTC")
                recent_ud = ud[ud.index >= cutoff].sort_index(ascending=False).head(20)
                for ts, row in recent_ud.iterrows():
                    from_g = str(row.get("FromGrade", "")).strip()
                    analyst_ratings.append({
                        "date":       ts.strftime("%Y-%m-%d"),
                        "firm":       str(row.get("Firm", "")).strip(),
                        "to_grade":   str(row.get("ToGrade", "")).strip(),
                        "from_grade": from_g if from_g else None,
                        "action":     str(row.get("Action", "")).strip(),
                    })
        except Exception:
            analyst_ratings = []

    # ── EPS beat/miss vs consensus (most recent quarter) ──────────────────────
    try:
        eh = getattr(tk, "earnings_history", None)
        if eh is None:
            try:
                eh = tk.get_earnings_history()
            except Exception:
                pass
        if eh is not None and hasattr(eh, "empty") and not eh.empty:
            surp_col = next((c for c in eh.columns if "surprise" in str(c).lower()), None)
            if surp_col:
                val = eh[surp_col].dropna()
                if len(val) > 0:
                    raw_surp = float(val.iloc[0])
                    # yfinance may return as fraction (0.031) or percent (3.1) — normalise to %
                    eps_surprise_pct = raw_surp if abs(raw_surp) > 1 else raw_surp * 100
    except Exception:
        pass

    # ── Technical indicators (same logic as Stock Analysis tab) ─────────────────
    rsi_val                    = _rsi(closes)
    macd_val, macd_sig, macd_h = _macd(closes)
    sma20_val                  = _sma(closes, 20)
    sma50_val                  = _sma(closes, 50)
    sma200_val                 = _sma(closes, 200)   # None for < 200 days of data
    bb_upper, bb_lower, bb_mid = _bollinger(closes)
    vwap_val                   = _vwap(highs, lows, closes, volumes)
    atr_val                    = _atr(highs, lows, closes)
    atr_pct_val = round(atr_val / current * 100, 2) if atr_val and current else None

    # ── Insider transactions + institutional ownership (SEC Form 4 via yfinance) ─
    insider_score      = 50.0
    insider_net_shares = 0
    insider_buys       = 0
    insider_sells      = 0
    inst_pct_held      = 0.0
    sec_insider_summary: dict = {}
    sec_recent_filings:  list = []

    if asset["type"] == "stock":
        try:
            import pandas as _pd
            df = tk.insider_transactions
            if df is not None and not df.empty:
                cutoff = _pd.Timestamp(today - timedelta(days=90))
                try:
                    recent = df[df.index >= cutoff]
                except Exception:
                    recent = df
                text_col   = next((c for c in recent.columns
                                   if any(k in str(c).lower() for k in ("text", "transaction"))), None)
                shares_col = next((c for c in recent.columns if "shares" in str(c).lower()), None)
                if text_col and shares_col:
                    txt = recent[text_col].astype(str)
                    buy_mask  = txt.str.contains("Purchase|Buy", case=False, na=False)
                    sell_mask = (txt.str.contains("Sale|Sell", case=False, na=False) &
                                 ~txt.str.contains("Automatic", case=False, na=False))
                    buy_sh    = recent[buy_mask][shares_col].sum()
                    sell_sh   = recent[sell_mask][shares_col].sum()
                    net       = int(buy_sh - sell_sh)
                    insider_buys       = int(buy_mask.sum())
                    insider_sells      = int(sell_mask.sum())
                    insider_net_shares = net
                    if net > 100_000:
                        insider_score = 85.0
                    elif net > 20_000:
                        insider_score = 70.0
                    elif net > 0:
                        insider_score = 58.0
                    elif net < -200_000:
                        insider_score = 22.0
                    elif net < -50_000:
                        insider_score = 33.0
                    elif net < 0:
                        insider_score = 42.0
        except Exception:
            pass

        try:
            major = tk.major_holders
            if major is not None and not major.empty:
                try:
                    pct = float(major.loc["institutionsPercentHeld", "Value"])
                except Exception:
                    pct = 0.0
                inst_pct_held = round(pct * 100, 1)
                if pct > 0.75:
                    insider_score = min(insider_score + 8, 100)
                elif pct > 0.50:
                    insider_score = min(insider_score + 4, 100)
        except Exception:
            pass

        # Top institutional holders with Q-o-Q share change
        inst_top_holders: list   = []
        inst_top10_buyers: int   = 0
        inst_top10_sellers: int  = 0
        inst_top10_signal: str   = "neutral"
        try:
            ih = tk.institutional_holders
            if ih is not None and not ih.empty:
                for _, row in ih.head(5).iterrows():
                    inst_top_holders.append({
                        "holder":     str(row.get("Holder", "")),
                        "pct_held":   round(float(row["pctHeld"]) * 100, 2) if "pctHeld" in row else None,
                        "pct_change": round(float(row["pctChange"]) * 100, 2) if "pctChange" in row else None,
                    })
                changes = [h["pct_change"] for h in inst_top_holders if h["pct_change"] is not None]
                if changes:
                    inst_top10_buyers  = sum(1 for c in changes if c > 0)
                    inst_top10_sellers = sum(1 for c in changes if c < 0)
                    inst_top10_signal  = (
                        "buying"  if inst_top10_buyers  > inst_top10_sellers else
                        "selling" if inst_top10_sellers > inst_top10_buyers  else
                        "mixed"
                    )
        except Exception:
            pass

        # SEC EDGAR Form 4 — supplement/override yfinance insider score
        try:
            from backend.services.sec_edgar import (
                get_insider_transactions, summarise_insider_transactions, get_recent_filings
            )
            _txns = get_insider_transactions(asset["ticker"], days=90, max_filings=10)
            sec_insider_summary = summarise_insider_transactions(_txns)
            sec_recent_filings  = get_recent_filings(asset["ticker"])
            if sec_insider_summary:
                sig = sec_insider_summary.get("signal", "neutral")
                insider_score = (
                    85.0 if sig == "strong_buy" else
                    70.0 if sig == "buy"        else
                    22.0 if sig == "sell"       else
                    33.0 if sig == "weak_sell"  else
                    50.0
                )
        except Exception:
            pass

    # ── Corporate actions: stock splits (5-year history) ─────────────────────
    try:
        import pandas as _pd
        splits = tk.splits
        if splits is not None and not splits.empty:
            cutoff        = today - timedelta(days=5 * 365)
            recent_splits = splits[splits.index.date >= cutoff]
            if not recent_splits.empty:
                last_ratio       = float(recent_splits.iloc[-1])
                last_dt          = recent_splits.index[-1].date()
                last_split_ratio = round(last_ratio, 4)
                last_split_date  = str(last_dt)
                last_split_type  = "forward" if last_ratio > 1 else "reverse"
                days_since       = (today - last_dt).days
                if last_split_type == "reverse":
                    split_score_adj = -8 if days_since <= 730 else -3
                elif last_split_type == "forward" and days_since <= 365:
                    split_score_adj = 2
    except Exception:
        pass

    # ── Social sentiment (best-effort, cached 30 min) ─────────────────────────
    sentiment = get_social_sentiment(asset["ticker"])
    sent_scr  = float(sentiment.get("sentiment_score", 50))

    # ── Sub-scores (0-100 each) ────────────────────────────────────────────────
    mom_1d  = min(max(day_chg_pct   * 5   + 50, 0), 100)
    mom_1w  = min(max(week_chg_pct  * 3   + 50, 0), 100)
    mom_1m  = min(max(month_chg_pct * 2   + 50, 0), 100)
    mom_3m  = min(max(qtr_chg_pct   * 1.5 + 50, 0), 100)
    vol_scr = min(vol_ratio * 40, 100)
    pos_scr = pos_52w * 100   # near 52-week HIGH = strong score

    # RS vs SPY
    spy_3m  = bm.get("SPY", spy_return_3m)
    rs_spy  = min(max((qtr_chg_pct - spy_3m) * 2 + 50, 0), 100)

    # RS vs sector ETF (falls back to SPY if unknown sector)
    sector_etf    = _SECTOR_ETF.get(stock_sector, "SPY")
    sector_3m     = bm.get(sector_etf, spy_3m)
    rs_sector     = min(max((qtr_chg_pct - sector_3m) * 2 + 50, 0), 100)

    # Earnings quality: beat/miss (50%) + EPS growth (30%) + revenue growth (20%)
    eps_beat_scr  = min(max(eps_surprise_pct * 2 + 50, 0), 100)
    eps_grow_scr  = min(max(50 + eps_growth * 50,      0), 100)
    rev_grow_scr  = min(max(50 + rev_growth * 30,      0), 100)
    earn_qual_scr = eps_beat_scr * 0.5 + eps_grow_scr * 0.3 + rev_grow_scr * 0.2

    # Short interest: high short + rising price = squeeze potential
    squeeze_flag = False
    short_scr    = 50.0
    if short_pct_float > 0:
        if short_pct_float > 0.15 and qtr_chg_pct > 5:
            short_scr    = min(70 + short_pct_float * 80, 92)
            squeeze_flag = True
        elif short_pct_float > 0.30 and qtr_chg_pct < -5:
            short_scr = 22
        elif short_pct_float > 0.20:
            short_scr = 40

    # Analyst consensus + price target score
    analyst_score      = 50.0
    analyst_upside_pct = 0.0
    if target_mean_price > 0 and current > 0 and num_analysts >= 2:
        analyst_upside_pct = (target_mean_price - current) / current * 100
        price_scr      = min(max(50 + analyst_upside_pct * 1.5, 0), 100)
        rec_scr        = min(max(100 - (recommendation_mean - 1) * 22.5, 0), 100)
        reliability    = min(num_analysts / 8.0, 1.0)
        analyst_score  = (price_scr * 0.5 + rec_scr * 0.5) * reliability + 50.0 * (1 - reliability)

    # ── Composite — price weights loaded from DB backtest, fixed weights hardcoded ──
    _pw = _get_live_weights()
    composite = (
        _pw["mom_3m"]    * mom_3m        +
        _pw["mom_1m"]    * mom_1m        +
        _pw["mom_1w"]    * mom_1w        +
        _pw["mom_1d"]    * mom_1d        +
        _pw["vol_scr"]   * vol_scr       +
        _pw["rs_spy"]    * rs_spy        +
        _pw["rs_sector"] * rs_sector     +
        _pw["pos_scr"]   * pos_scr       +
        _FIXED_FACTOR_WEIGHTS["earn_qual_scr"] * earn_qual_scr +
        _FIXED_FACTOR_WEIGHTS["short_scr"]     * short_scr     +
        _FIXED_FACTOR_WEIGHTS["sent_scr"]      * sent_scr      +
        _FIXED_FACTOR_WEIGHTS["analyst_score"] * analyst_score +
        _FIXED_FACTOR_WEIGHTS["insider_score"] * insider_score
    )

    # Earnings proximity penalty: high event risk when reporting soon
    earnings_days_out = None
    earnings_penalty  = 0
    if earnings_flag:
        try:
            earnings_days_out = (date.fromisoformat(earnings_flag) - today).days
            if earnings_days_out <= 1:
                earnings_penalty = 15
            elif earnings_days_out <= 3:
                earnings_penalty = 10
            elif earnings_days_out <= 7:
                earnings_penalty = 5
        except Exception:
            pass

    # Regime adjustment: dampen scores in BEAR/CRISIS, boost in confirmed BULL
    regime_info  = regime or {}
    multiplier   = float(regime_info.get("score_multiplier", 1.0))
    raw_score    = int(round(min(max(composite, 0), 100)))

    # Track-record adjustment: ±6 pts based on how this ticker's past BUY picks performed
    ticker_sym = asset.get("ticker", "")
    _tr = _get_track_record_scores().get(ticker_sym)
    track_adj = 0
    if _tr:
        wr = _tr["win_rate"]
        if wr >= 0.70:   track_adj =  6
        elif wr >= 0.60: track_adj =  3
        elif wr <= 0.30: track_adj = -6
        elif wr <= 0.40: track_adj = -3

    score  = int(round(min(max(composite * multiplier - earnings_penalty + track_adj + split_score_adj, 0), 100)))
    signal = "BUY" if score >= 65 else "WATCH" if score >= 45 else "HOLD"

    all_sub    = [mom_3m, mom_1m, mom_1w, mom_1d, vol_scr, rs_spy, rs_sector,
                  pos_scr, earn_qual_scr, short_scr, sent_scr, analyst_score, insider_score]
    confidence = round(sum(1 for s in all_sub if s > 50) / len(all_sub) * 100)

    # ── ATR proxy for position sizing (1-week volatility × 1.5) ───────────────
    atr_pct_est = max(abs(week_chg_pct) * 1.5, 0.5)  # rough ATR estimate as % of price

    try:
        from backend.services.position_sizer import compute_position_size
        pos_size = compute_position_size(
            entry_price=current,
            atr_pct=atr_pct_est,
            score=score,
            regime_multiplier=multiplier,
        )
    except Exception:
        pos_size = None

    return {
        "ticker":              asset["ticker"],
        "type":                asset["type"],
        "current_price":       round(current, 4),
        "day_change_pct":      round(day_chg_pct,   2),
        "week_change_pct":     round(week_chg_pct,  2),
        "month_change_pct":    round(month_chg_pct, 2),
        "qtr_change_pct":      round(qtr_chg_pct,   2),
        "vol_ratio":           round(vol_ratio, 2),
        "vol_30d_avg":         vol_30d_avg,
        "vol_prior_avg":       vol_prior_avg,
        "vol_trend_pct":       vol_trend_pct,
        "vol_signal":          vol_signal,
        "pos_52w":             round(pos_52w * 100, 1),
        "rs_vs_spy":           round(qtr_chg_pct - spy_3m,    2),
        "rs_vs_sector":        round(qtr_chg_pct - sector_3m, 2),
        "sector":              stock_sector,
        "sector_etf":          sector_etf,
        "eps_growth_pct":      round(eps_growth * 100, 1),
        "rev_growth_pct":      round(rev_growth * 100, 1),
        "eps_surprise_pct":    round(eps_surprise_pct, 1),
        "short_pct_float":     round(short_pct_float * 100, 1),
        "short_ratio":         round(short_ratio, 1),
        # technical indicators
        "rsi":                 rsi_val,
        "macd":                macd_val,
        "macd_signal":         macd_sig,
        "macd_hist":           macd_h,
        "sma20":               sma20_val,
        "sma50":               sma50_val,
        "sma200":              sma200_val,
        "bb_upper":            bb_upper,
        "bb_lower":            bb_lower,
        "bb_mid":              bb_mid,
        "vwap":                vwap_val,
        "atr":                 atr_val,
        "atr_pct":             atr_pct_val,
        # analyst fields
        "analyst_target":      round(target_mean_price, 2) if target_mean_price > 0 else None,
        "analyst_upside_pct":  round(analyst_upside_pct, 1),
        "analyst_consensus":   recommendation_key,
        "num_analysts":        num_analysts,
        "analyst_ratings":     analyst_ratings,
        # insider / institutional fields
        "insider_net_shares":   insider_net_shares,
        "insider_buys":         insider_buys,
        "insider_sells":        insider_sells,
        "inst_pct_held":        inst_pct_held,
        "inst_top_holders":     inst_top_holders,
        "inst_top10_buyers":    inst_top10_buyers,
        "inst_top10_sellers":   inst_top10_sellers,
        "inst_top10_signal":    inst_top10_signal,
        # SEC EDGAR
        "sec_insider_summary":  sec_insider_summary,
        "sec_recent_filings":   sec_recent_filings,
        # score fields
        "raw_score":           raw_score,
        "regime_multiplier":   multiplier,
        "score":               score,
        "signal":              signal,
        "confidence":          confidence,
        "breakout_flag":       pos_52w >= 0.95,
        "squeeze_flag":        squeeze_flag,
        "earnings_flag":       earnings_flag,
        "earnings_days_out":   earnings_days_out,
        "earnings_penalty":    earnings_penalty,
        # corporate actions
        "last_split_date":     last_split_date,
        "last_split_ratio":    last_split_ratio,
        "last_split_type":     last_split_type,
        "upcoming_split_date": upcoming_split_date,
        "split_score_adj":     split_score_adj,
        "position_size":       pos_size,
        "sentiment_score":     sentiment.get("sentiment_score", 50),
        "sentiment_label":     sentiment.get("sentiment_label", "Neutral"),
        "sentiment_bullish":   sentiment.get("bullish_pct", 50),
        "sentiment_bearish":   sentiment.get("bearish_pct", 50),
        "st_total":            sentiment.get("st_total", 0),
        "reddit_mentions":     sentiment.get("reddit_mentions", 0),
        "sentiment_sources":   sentiment.get("sources", []),
    }


def fetch_all_data(stocks: list, crypto: list) -> list:
    """Fetch and score all assets. Returns unsorted list of dicts."""
    try:
        import yfinance as yf  # noqa: F401
    except ImportError:
        logger.error("yfinance not installed. Run: pip3 install yfinance --break-system-packages")
        return []

    assets = (
        [{"ticker": s, "type": "stock"} for s in stocks] +
        [{"ticker": c, "type": "crypto"} for c in crypto]
    )
    if not assets:
        return []

    logger.info("Fetching multi-factor scores for %d assets...", len(assets))
    bm = _fetch_benchmark_returns()
    spy_3m = bm.get("SPY", 0.0)
    logger.info("Benchmarks: SPY=%.2f%%  sector ETFs=%d loaded", spy_3m, len(bm))

    try:
        from backend.services.regime_detector import get_market_regime
        regime = get_market_regime()
        logger.info("Regime: %s (multiplier=%.2f)", regime.get("regime"), regime.get("score_multiplier", 1.0))
    except Exception:
        regime = None

    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows: list = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_score_asset, a, spy_3m, bm, regime): a for a in assets}
        for fut in as_completed(futures):
            asset = futures[fut]
            try:
                result = fut.result()
                if result:
                    rows.append(result)
            except Exception as exc:
                logger.warning("Skipping %s: %s", asset["ticker"], exc)

    return rows


def fetch_cheap_stocks(max_price: float = 5.0, min_market_cap: int = 50_000_000, limit: int = 50) -> list:
    """Screen the broad US market for stocks priced below max_price,
    score them with the multi-factor model, and return sorted results."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed.")
        return []

    logger.info("Screening US stocks priced under $%.2f via yfinance...", max_price)

    try:
        from yfinance.screener.query import EquityQuery
        query = EquityQuery("and", [
            EquityQuery("is-in", ["exchange", "NMS", "NYQ"]),
            EquityQuery("lt",    ["intradayprice", max_price]),
            EquityQuery("gt",    ["intradayprice", 0.10]),
            EquityQuery("gt",    ["intradaymarketcap", min_market_cap]),
        ])
        result  = yf.screen(query, size=limit, sortField="percentchange", sortAsc=False)
        quotes  = result.get("quotes", [])
        tickers = [q["symbol"] for q in quotes if q.get("symbol")]
        logger.info("Screener returned %d tickers under $%.2f", len(tickers), max_price)
    except Exception as exc:
        logger.warning("Screener failed (%s) — falling back to empty list.", exc)
        return []

    if not tickers:
        return []

    bm     = _fetch_benchmark_returns()
    spy_3m = bm.get("SPY", 0.0)
    assets = [{"ticker": t, "type": "stock"} for t in tickers]

    try:
        from backend.services.regime_detector import get_market_regime
        regime = get_market_regime()
    except Exception:
        regime = None

    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows: list = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_score_asset, a, spy_3m, bm, regime): a for a in assets}
        for fut in as_completed(futures):
            asset = futures[fut]
            try:
                result = fut.result()
                if result and result["current_price"] <= max_price:
                    rows.append(result)
            except Exception as exc:
                logger.warning("Skipping %s: %s", asset["ticker"], exc)

    return sorted(rows, key=lambda x: x["score"], reverse=True)


def fetch_market_context(stocks: list, max_headlines_per_ticker: int = 2) -> str:
    """
    Return a compact market-intelligence string for injection into the trading
    session kickoff: upcoming earnings dates + recent news headlines.

    Uses yfinance only — no extra API keys required. Fails gracefully if a
    ticker is unavailable.
    """
    try:
        import yfinance as yf
    except ImportError:
        return ""

    from datetime import date, timedelta

    today    = date.today()
    week_end = today + timedelta(days=7)

    earnings_soon: list[str] = []
    headlines:     list[str] = []

    for ticker in stocks:
        try:
            t = yf.Ticker(ticker)

            # ── Earnings calendar ──────────────────────────────────────────
            try:
                cal = t.calendar
                if isinstance(cal, dict) and "Earnings Date" in cal:
                    dates = cal["Earnings Date"]
                    if not isinstance(dates, list):
                        dates = [dates]
                    for d in dates:
                        if hasattr(d, "date"):
                            d = d.date()
                        if isinstance(d, date) and today <= d <= week_end:
                            earnings_soon.append(f"{ticker} ({d})")
                            break
            except Exception:
                pass

            # ── News headlines ─────────────────────────────────────────────
            try:
                news = t.news or []
                for item in news[:max_headlines_per_ticker]:
                    title = item.get("title", "").strip()
                    if title:
                        headlines.append(f"[{ticker}] {title}")
            except Exception:
                pass

        except Exception:
            pass

    parts: list[str] = []
    if earnings_soon:
        parts.append("Earnings this week: " + ", ".join(earnings_soon))
    else:
        parts.append("No universe stocks report earnings this week.")
    if headlines:
        parts.append("Recent news headlines:\n" + "\n".join(headlines[:40]))

    return "\n\n".join(parts)


def _print_free_table(title: str, rows: list, now: "datetime") -> None:
    """Print a formatted table of multi-factor scored rows."""
    print("\n" + "=" * 90)
    print(f"  {title} — {now.strftime('%A, %Y-%m-%d %H:%M ET')}  [free mode]")
    print("=" * 90)
    if not rows:
        print("  No qualifying picks.")
        print("=" * 90 + "\n")
        return
    print(f"{'#':<4} {'Ticker':<8} {'Score':<6} {'Sig':<6} {'Price':>8}  "
          f"{'Day%':>6}  {'1W%':>6}  {'3M%':>7}  {'RS/SPY':>7}  "
          f"{'Vol':>5}  {'52w':>5}  {'Flags':<12}")
    print("-" * 90)
    for i, r in enumerate(rows, 1):
        icon  = {"BUY": "🟢", "WATCH": "🔵", "HOLD": "🟡"}.get(r.get("signal", ""), "⚪")
        flags = ""
        if r.get("breakout_flag"):
            flags += "🚀BRK "
        if r.get("squeeze_flag"):
            flags += "💥SQZ "
        if r.get("earnings_flag"):
            flags += "⚠EPS"
        surp = r.get("eps_surprise_pct")
        surp_str = f"{surp:+.0f}%" if surp is not None else "  —  "
        print(
            f"{i:<4} {r['ticker']:<8} {r['score']:<6} "
            f"{icon}{r.get('signal',''):<4} "
            f"{r['current_price']:>8.2f}  "
            f"{r.get('day_change_pct', 0):>+5.1f}%  "
            f"{r.get('week_change_pct', 0):>+5.1f}%  "
            f"{r.get('qtr_change_pct', 0):>+6.1f}%  "
            f"{r.get('rs_vs_spy', 0):>+6.1f}pp  "
            f"{r.get('vol_ratio', 1):>4.1f}x  "
            f"EPS:{surp_str}  "
            f"SI:{r.get('short_pct_float', 0):>4.0f}%  "
            f"{flags}"
        )
    print("=" * 90)
    print("Score: 25%×3M-mom + 20%×1M-mom + 15%×1W-mom + 15%×volume + 10%×RS-vs-SPY + 5%×52wPos + 5%×quality")
    print("🚀BRK = within 5% of 52-week high (breakout zone)  ⚠EPS = earnings this week")
    print("NOTE: Research only — no trades placed.")
    print("=" * 90 + "\n")


def run_free(stocks: list, crypto: list, top_n: int, max_price: float | None = None,
             dual_category: bool = False, email_cfg: dict | None = None) -> None:
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    if dual_category:
        all_label   = f"TOP {PICKS_PER_CATEGORY} ALL STOCKS"
        penny_label = f"TOP {PICKS_PER_CATEGORY} PENNY STOCKS (under $5)"

        # --- Category 1: All stocks from configured universe ---
        all_rows = sorted(
            fetch_all_data(stocks, []), key=lambda x: x["score"], reverse=True
        )[:PICKS_PER_CATEGORY]
        _print_free_table(all_label, all_rows, now)

        # --- Category 2: Penny stocks screened from the broad market ---
        penny_rows = fetch_cheap_stocks(max_price=5.0, limit=50)[:PICKS_PER_CATEGORY]
        _print_free_table(penny_label, penny_rows, now)

        sections = [
            {"label": all_label,   "data": all_rows,   "mode": "free"},
            {"label": penny_label, "data": penny_rows, "mode": "free"},
        ]
        if email_cfg:
            html = _build_research_html(sections, now, "free")
            send_research_email(html, email_cfg, now)
        return sections

    rows = sorted(fetch_all_data(stocks, crypto), key=lambda x: x["score"], reverse=True)
    if max_price is not None:
        rows = [r for r in rows if r["current_price"] <= max_price]
    label   = f"TOP {len(rows[:top_n])} PICKS" + (f" (price ≤ ${max_price})" if max_price else "")
    section = [{"label": label, "data": rows[:top_n], "mode": "free"}]
    _print_free_table(label, rows[:top_n], now)
    if email_cfg:
        html = _build_research_html(section, now, "free")
        send_research_email(html, email_cfg, now)
    return section


# ---------------------------------------------------------------------------
# API MODE — Claude + web search
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 90   # minimum score to include a pick (API mode)
PICKS_PER_CATEGORY    = 5   # picks returned per category


def _build_technical_context(tickers: list[str]) -> str:
    """
    Pre-compute technical indicators for tickers and return a compact text block
    for injection into Claude prompts so it has quantitative context to reason from.
    """
    try:
        import yfinance as yf
    except ImportError:
        return ""

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(ticker: str) -> tuple[str, dict]:
        try:
            tk   = yf.Ticker(ticker)
            hist = tk.history(period="3mo", interval="1d", auto_adjust=True)
            if hist.empty:
                return ticker, {}
            closes  = [float(v) for v in hist["Close"].dropna()]
            highs   = [float(v) for v in hist["High"].dropna()]  if "High"   in hist else []
            lows    = [float(v) for v in hist["Low"].dropna()]   if "Low"    in hist else []
            volumes = [float(v) for v in hist["Volume"].dropna()] if "Volume" in hist else []
            fi      = tk.fast_info
            price   = getattr(fi, "last_price", closes[-1] if closes else None)
            return ticker, {
                "price":   round(price, 2) if price else None,
                "rsi":     _rsi(closes),
                "macd":    _macd(closes)[0],
                "macd_h":  _macd(closes)[2],
                "sma50":   _sma(closes, 50),
                "sma200":  _sma(closes, 200),
                "bb_upper":_bollinger(closes)[0],
                "bb_lower":_bollinger(closes)[1],
                "vwap":    _vwap(highs, lows, closes, volumes),
                "atr_pct": round(_atr(highs, lows, closes) / price * 100, 2)
                           if _atr(highs, lows, closes) and price else None,
            }
        except Exception:
            return ticker, {}

    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker, data = fut.result()
            if data:
                results[ticker] = data

    if not results:
        return ""

    lines = ["\n\nPre-computed technical indicators (use as quantitative context):"]
    for ticker in tickers:
        d = results.get(ticker)
        if not d:
            continue
        price  = d.get("price")
        rsi    = d.get("rsi")
        macd   = d.get("macd")
        macd_h = d.get("macd_h")
        sma50  = d.get("sma50")
        sma200 = d.get("sma200")
        bbu    = d.get("bb_upper")
        bbl    = d.get("bb_lower")
        vwap   = d.get("vwap")
        atr_p  = d.get("atr_pct")

        parts = [f"${price}" if price else ""]
        if rsi:
            parts.append(f"RSI={rsi:.1f}{'(oversold)' if rsi<30 else '(overbought)' if rsi>70 else ''}")
        if macd and macd_h:
            parts.append(f"MACD={macd:+.3f} hist={macd_h:+.3f}({'bullish' if macd_h>0 else 'bearish'})")
        if sma50 and price:
            parts.append(f"SMA50=${sma50:.2f}({'above' if price>sma50 else 'below'})")
        if sma200 and price:
            parts.append(f"SMA200=${sma200:.2f}({'above' if price>sma200 else 'below'})")
        if bbu and bbl and price:
            pct_bb = (price - bbl) / (bbu - bbl) * 100 if bbu != bbl else 50
            parts.append(f"BB=[{bbl:.2f}–{bbu:.2f}] pos={pct_bb:.0f}%")
        if vwap and price:
            parts.append(f"VWAP=${vwap:.2f}({'above' if price>vwap else 'below'})")
        if atr_p:
            parts.append(f"ATR={atr_p:.1f}%")

        lines.append(f"  {ticker}: {' | '.join(p for p in parts if p)}")

    return "\n".join(lines)


def _build_sentiment_block(tickers: list[str]) -> str:
    """
    Pre-fetch social sentiment for *tickers* (parallel, max 3 workers) and
    return a compact text block ready to inject into a Claude prompt.
    Returns an empty string when no data is available for any ticker.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not tickers:
        return ""

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(get_social_sentiment, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                results[ticker] = fut.result()
            except Exception:
                pass

    lines = []
    for ticker in tickers:
        s = results.get(ticker, {})
        if not s.get("sources"):
            continue
        src  = " + ".join(s["sources"])
        lbl  = s.get("sentiment_label", "Neutral")
        bull = s.get("bullish_pct", 50)
        fg   = s.get("fg_label")
        st   = s.get("st_total", 0)
        rd   = s.get("reddit_mentions", 0)

        detail = f"{bull}% bullish"
        if st:
            detail += f" | ST: {st} msgs"
        if rd:
            detail += f" | Reddit: {rd} posts"
        if fg:
            detail += f" | F&G: {fg}"

        lines.append(f"  {ticker}: {lbl} ({detail})  [{src}]")

    if not lines:
        return ""

    return (
        "\n\nSocial sentiment data (pre-fetched from StockTwits / Fear & Greed / Reddit):\n"
        + "\n".join(lines)
        + "\n\nFactor this alongside your own research — strong bullish sentiment can confirm "
        "momentum; extreme fear/greed readings may signal caution or opportunity."
    )

SYSTEM_PROMPT = """You are a quantitative trading analyst. Research a given universe
of stocks and cryptocurrencies using live market data and news, then rank them by
short-term opportunity score for today.

IMPORTANT QUALITY BAR: Only include picks where you have 90%+ confidence in the
opportunity. Prefer returning fewer than 5 picks over including a low-conviction one.
Return EXACTLY 5 picks (or fewer if not enough qualify at 90%+ confidence).

For each asset, research ALL of the following:
1. Price momentum, volume vs 30-day average, and today's % change.
2. News sentiment from the last 48 hours.
3. Analyst consensus: current buy/hold/sell ratings and mean price target.
4. Earnings calendar: flag any earnings within the next 7 days (high event risk).
5. Insider activity: any notable Form 4 insider purchases or sales in the last 30 days.
6. Institutional ownership: is it rising or falling (13F signals)?
7. Technical signals and upcoming catalysts (earnings, macro events, sector rotation).

Penalise stocks reporting earnings within 3 days — reduce confidence accordingly.
Treat recent insider buying as a strong positive signal; heavy selling as a red flag.

Respond ONLY with a JSON object:
{
  "date": "YYYY-MM-DD",
  "market_summary": "2-3 sentence market overview",
  "top_picks": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "asset_type": "stock",
      "current_price": 135.42,
      "day_change_pct": 2.3,
      "score": 92,
      "confidence_pct": 94,
      "signal": "BUY",
      "reasoning": "...",
      "key_catalyst": "...",
      "analyst_sentiment": "e.g. '18 Buy, 5 Hold, 0 Sell — consensus target $240'",
      "insider_activity": "e.g. 'CEO bought 50,000 shares on 2026-06-10' or 'No notable activity'",
      "earnings_warning": "e.g. 'Reports 2026-06-22 — hold until after' or null",
      "suggested_entry": 134.00,
      "target_price": 160.00,
      "stop_loss": 125.00,
      "time_horizon": "2-4 weeks",
      "risk_note": "..."
    }
  ],
  "avoid_today": ["TICKER1"],
  "avoid_reason": "brief explanation"
}
Signal: BUY | HOLD | WATCH. Score: 0-100 (only include if score >= 90). Rank by score descending."""

CHEAP_STOCK_SYSTEM_PROMPT = """You are a small-cap stock analyst specialising in
low-price, high-potential equities (under $5). Your job is to identify stocks that
are currently cheap but have strong future growth potential — NOT just momentum plays.

IMPORTANT QUALITY BAR: Only include picks where you have 90%+ confidence in the
opportunity. Prefer returning fewer than 5 picks over including a low-conviction one.
Return EXACTLY 5 picks (or fewer if not enough qualify at 90%+ confidence).

For each stock consider:
- Business model: is the company solving a real problem with a viable path to profitability?
- Catalysts: upcoming earnings, product launches, FDA approvals, contracts, partnerships
- Financial health: debt levels, cash runway, recent revenue trend (growing or shrinking?)
- News sentiment: any recent positive developments in the last 7 days?
- Insider/institutional activity: any notable buying?
- Risk: why is it cheap? Is the risk temporary (sector downturn, short-term loss) or structural (dying business)?

Only recommend stocks where the upside potential clearly outweighs the risk.
Avoid pure penny-stock pumps, companies with no revenue, or stocks in terminal decline.

Respond ONLY with a JSON object:
{
  "date": "YYYY-MM-DD",
  "market_summary": "2-3 sentence overview of the small-cap environment today",
  "top_picks": [
    {
      "rank": 1,
      "ticker": "EXAMPLE",
      "asset_type": "stock",
      "current_price": 3.42,
      "day_change_pct": 1.5,
      "score": 91,
      "confidence_pct": 92,
      "signal": "BUY",
      "reasoning": "why this stock has real future potential",
      "key_catalyst": "specific upcoming event or trend driving the opportunity",
      "suggested_entry": 3.20,
      "target_price": 6.00,
      "time_horizon": "3-6 months",
      "risk_note": "main risk to the thesis"
    }
  ],
  "avoid_today": ["TICKER1"],
  "avoid_reason": "brief explanation"
}
Signal: BUY | HOLD | WATCH. Score: 0-100 (only include if score >= 90). Rank by score descending."""


def _parse_api_json(text: str) -> dict | None:
    """Extract and parse the JSON object from Claude's response text."""
    raw = text.strip()
    if "```" in raw:
        start = raw.find("{", raw.find("```"))
        end   = raw.rfind("}") + 1
        raw   = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _run_api_single(client, system_prompt: str, user_message: str,
                    label: str, now: "datetime") -> dict | None:
    """Run one API research conversation, print results, and return parsed data."""
    tools = [
        {"type": "web_search_20260209", "name": "web_search"},
        {"type": "web_fetch_20260209",  "name": "web_fetch"},
    ]
    messages = [{"role": "user", "content": user_message}]
    logger.info("Starting API research: %s", label)

    for iteration in range(1, 16):
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=[{"type": "text", "text": system_prompt,
                     "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        )
        logger.info("Turn %d | stop=%s | tokens in=%d out=%d",
                    iteration, response.stop_reason,
                    response.usage.input_tokens, response.usage.output_tokens)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    data = _parse_api_json(block.text)
                    if data:
                        _print_api_results(data, PICKS_PER_CATEGORY, now, label)
                    else:
                        print(block.text)
                    return data

        if response.stop_reason != "tool_use":
            logger.warning("Unexpected stop: %s", response.stop_reason)
            break

    logger.error("Research did not complete within iteration limit.")
    return None


def run_api(stocks: list, crypto: list, top_n: int, max_price: float | None = None,
            dual_category: bool = False, email_cfg: dict | None = None) -> None:
    import anthropic

    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    client = anthropic.Anthropic()

    if dual_category:
        # --- Category 1: All stocks from configured universe ---
        universe_lines = []
        if stocks:
            universe_lines.append(f"Stocks: {', '.join(stocks)}")
        if crypto:
            universe_lines.append(f"Crypto: {', '.join(crypto)}")
        all_tickers    = stocks + crypto
        all_sentiment  = _build_sentiment_block(all_tickers)
        all_stocks_msg = (
            f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
            f"Research the following assets and identify the top {PICKS_PER_CATEGORY} high-confidence "
            f"picks for today. Only include picks with 90%+ confidence (score >= {CONFIDENCE_THRESHOLD}).\n\n"
            + "\n".join(universe_lines)
            + all_sentiment +
            f"\n\nSearch for live prices, % changes, and recent news. "
            f"Return up to {PICKS_PER_CATEGORY} picks as JSON per the specified format. "
            f"Quality over quantity — omit a pick rather than include a low-conviction one."
        )
        all_label = f"ALL STOCKS — Top {PICKS_PER_CATEGORY} (90%+ Confidence)"
        all_data = _run_api_single(client, SYSTEM_PROMPT, all_stocks_msg, all_label, now)

        # --- Category 2: Penny stocks screened from the broad market ---
        logger.info("Screening penny stocks (under $5) for deep analysis...")
        screened = fetch_cheap_stocks(max_price=5.0, min_market_cap=10_000_000, limit=30)[:30]
        tickers  = [r["ticker"] for r in screened]
        logger.info("Screener returned %d tickers — sending to Claude.", len(tickers))
        penny_data = None
        penny_label = f"PENNY STOCKS (under $5) — Top {PICKS_PER_CATEGORY} (90%+ Confidence)"
        if tickers:
            penny_sentiment = _build_sentiment_block(tickers)
            penny_msg = (
                f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
                f"Research the following stocks (all priced under $5) and identify the top "
                f"{PICKS_PER_CATEGORY} with the strongest future growth potential. "
                f"Only include picks with 90%+ confidence (score >= {CONFIDENCE_THRESHOLD}).\n\n"
                f"Stocks to analyse: {', '.join(tickers)}"
                + penny_sentiment +
                "\n\nFor each pick, search for recent news, financials, catalysts, and business outlook. "
                f"Return up to {PICKS_PER_CATEGORY} picks as JSON. "
                f"Quality over quantity — omit a pick rather than include a low-conviction one."
            )
            penny_data = _run_api_single(client, CHEAP_STOCK_SYSTEM_PROMPT, penny_msg, penny_label, now)

        sections = [
            {"label": all_label,   "data": all_data,   "mode": "api"},
            {"label": penny_label, "data": penny_data, "mode": "api"},
        ]
        if email_cfg:
            html = _build_research_html(sections, now, "api")
            send_research_email(html, email_cfg, now)
        return sections

    # --- Single-category legacy path ---
    if max_price is not None:
        logger.info("Price filter set — screening broader market for stocks under $%.2f...", max_price)
        screened = fetch_cheap_stocks(max_price=max_price, min_market_cap=10_000_000, limit=25)[:25]
        tickers  = [r["ticker"] for r in screened]
        logger.info("Screener returned %d tickers — sending to Claude for deep analysis.", len(tickers))
        system_prompt = CHEAP_STOCK_SYSTEM_PROMPT
        user_message = (
            f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
            f"Research the following stocks (all priced under ${max_price}) and identify "
            f"the top {top_n} with the strongest future growth potential.\n\n"
            f"Stocks to analyse: {', '.join(tickers)}"
            + _build_sentiment_block(tickers) +
            "\n\nFor each pick, search for recent news, financials, catalysts, and business outlook. "
            f"Return the top {top_n} as JSON per the specified format."
        )
        label = f"PENNY STOCKS — top {top_n}"
    else:
        system_prompt = SYSTEM_PROMPT
        universe_lines = []
        if stocks:
            universe_lines.append(f"Stocks: {', '.join(stocks)}")
        if crypto:
            universe_lines.append(f"Crypto: {', '.join(crypto)}")
        user_message = (
            f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
            f"Research the following assets and identify the top {top_n} picks for today.\n\n"
            + "\n".join(universe_lines)
            + _build_sentiment_block(stocks + crypto) +
            f"\n\nSearch for live prices, % changes, and recent news. "
            f"Return top {top_n} picks as JSON per the specified format."
        )
        label = f"TOP {top_n} PICKS"

    data = _run_api_single(client, system_prompt, user_message, label, now)
    section = [{"label": label, "data": data, "mode": "api"}]
    if email_cfg and data:
        html = _build_research_html(section, now, "api")
        send_research_email(html, email_cfg, now)
    return section


def _print_api_results(data: dict, top_n: int, now: datetime, label: str = "") -> None:
    heading = label or f"TOP {top_n} PICKS"
    print("\n" + "=" * 60)
    print(f"  {heading} — {now.strftime('%A, %Y-%m-%d %H:%M ET')}  [api mode]")
    print("=" * 60)
    print(f"\nMarket: {data.get('market_summary', '')}\n")

    picks = data.get("top_picks", [])
    if not picks:
        print("  No picks met the 90%+ confidence threshold today.")
    for pick in picks:
        icon = {"BUY": "🟢", "HOLD": "🟡", "WATCH": "🔵"}.get(pick.get("signal"), "⚪")
        confidence = pick.get("confidence_pct")
        conf_str = f"  Confidence: {confidence}%" if confidence else ""
        print(f"#{pick['rank']:>2}  {icon} {pick['ticker']:<8} [{pick['asset_type']:<6}]  "
              f"Score: {pick['score']:>3}{conf_str}  Signal: {pick.get('signal',''):<5}  "
              f"${pick.get('current_price', '?'):>10}  ({pick.get('day_change_pct', 0):+.1f}%)")
        print(f"     {pick.get('reasoning', '')[:120]}")
        if pick.get("key_catalyst"):
            print(f"     Catalyst: {pick['key_catalyst']}")
        if pick.get("suggested_entry"):
            entry_line = f"     Entry: ${pick['suggested_entry']}"
            if pick.get("target_price"):
                entry_line += f"  →  Target: ${pick['target_price']}"
            if pick.get("time_horizon"):
                entry_line += f"  [{pick['time_horizon']}]"
            print(entry_line)
        if pick.get("risk_note"):
            print(f"     Risk: {pick['risk_note']}")
        print()

    avoid = data.get("avoid_today", [])
    if avoid:
        print(f"Avoid today: {', '.join(avoid)}")
        print(f"Reason: {data.get('avoid_reason', '')}")

    print("=" * 60)
    print("NOTE: Research only — no trades placed.")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Email — HTML builder + SMTP sender
# ---------------------------------------------------------------------------

_SIGNAL_BG = {"BUY": "#C6EFCE", "WATCH": "#DDEBF7", "HOLD": "#FFEB9C"}
_SIGNAL_ICON = {"BUY": "🟢", "WATCH": "🔵", "HOLD": "🟡"}

_HTML_STYLE = """
<style>
  body{font-family:Arial,sans-serif;font-size:13px;color:#222;margin:24px}
  h1{color:#1F4E79;font-size:18px;margin-bottom:4px}
  h2{color:#1F4E79;font-size:15px;margin:24px 0 6px}
  .summary{background:#f0f4f8;border-left:4px solid #1F4E79;padding:8px 12px;
           margin-bottom:12px;font-size:12px;color:#444}
  table{border-collapse:collapse;width:100%;margin-bottom:8px}
  th{background:#1F4E79;color:#fff;padding:7px 10px;text-align:left;font-size:12px}
  td{padding:6px 10px;border-bottom:1px solid #ddd;vertical-align:top;font-size:12px}
  .avoid{background:#FFF2CC;padding:8px 12px;margin-top:6px;font-size:12px}
  .footer{color:#aaa;font-size:11px;margin-top:28px;border-top:1px solid #eee;padding-top:8px}
  .fg-banner{display:flex;gap:16px;margin:12px 0 20px;flex-wrap:wrap}
  .fg-card{flex:1;min-width:180px;border-radius:8px;padding:12px 16px;border:1px solid #ddd}
  .fg-label{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px}
  .fg-score{font-size:28px;font-weight:bold;margin:4px 0 2px}
  .fg-tag{font-size:12px;font-weight:600}
  .fg-bar{height:8px;border-radius:4px;margin-top:8px;background:#eee;overflow:hidden}
  .fg-bar-fill{height:100%;border-radius:4px}
</style>
"""


def _fg_color(score: int) -> tuple[str, str]:
    """Return (bg_hex, bar_hex) based on Fear & Greed score."""
    if score <= 25:
        return "#fff1f1", "#ef4444"   # Extreme Fear — red
    if score <= 45:
        return "#fff7ed", "#f97316"   # Fear — orange
    if score <= 55:
        return "#fefce8", "#eab308"   # Neutral — yellow
    if score <= 75:
        return "#f0fdf4", "#22c55e"   # Greed — green
    return "#f0fdf4", "#16a34a"       # Extreme Greed — dark green


def _fear_greed_banner() -> str:
    """Fetch both Fear & Greed indices and return a styled HTML banner for the email."""
    from sentiment import _fetch_cnn_fear_greed, _fetch_crypto_fear_greed

    stock_score, stock_label = _fetch_cnn_fear_greed()
    crypto_score, crypto_label = _fetch_crypto_fear_greed()

    def _card(title: str, score: int, label: str) -> str:
        bg, bar_color = _fg_color(score)
        return (
            f"<div class='fg-card' style='background:{bg}'>"
            f"<div class='fg-label'>{title}</div>"
            f"<div class='fg-score' style='color:{bar_color}'>{score}</div>"
            f"<div class='fg-tag' style='color:{bar_color}'>{label}</div>"
            f"<div class='fg-bar'>"
            f"<div class='fg-bar-fill' style='width:{score}%;background:{bar_color}'></div>"
            f"</div>"
            f"</div>"
        )

    return (
        "<div class='fg-banner'>"
        + _card("Stock Market Fear & Greed (CNN)", stock_score, stock_label)
        + _card("Crypto Fear & Greed (Alternative.me)", crypto_score, crypto_label)
        + "</div>"
    )


def _api_picks_table(data: dict) -> str:
    """Build card-style HTML from an API-mode result dict."""
    picks = data.get("top_picks", [])
    if not picks:
        return "<p><em>No picks met the 90%+ confidence threshold today.</em></p>"

    cards = []
    for p in picks:
        bg     = _SIGNAL_BG.get(p.get("signal", ""), "#fff")
        icon   = _SIGNAL_ICON.get(p.get("signal", ""), "⚪")
        risks  = p.get("risk_factors", [])
        risk_html = "".join(f"<li>{r}</li>" for r in risks) if risks else "<li>—</li>"

        entry      = f"${p['suggested_entry']}"  if p.get("suggested_entry")  else "—"
        target     = f"${p['target_price']}"     if p.get("target_price")     else "—"
        stop       = f"${p['stop_loss']}"        if p.get("stop_loss")        else "—"
        upside     = f"{p['upside_pct']:.1f}%"  if p.get("upside_pct")       else "—"
        confidence = f"{p['confidence_pct']}%"  if p.get("confidence_pct")   else "—"
        week_chg   = f"{p['week_change_pct']:+.1f}%" if p.get("week_change_pct") else "—"

        extra_rows = ""
        for field, label in [
            ("why_its_cheap",      "Why It's Cheap"),
            ("business_viability", "Business Viability"),
            ("financial_health",   "Financial Health"),
        ]:
            if p.get(field):
                extra_rows += f"<tr><td><b>{label}:</b></td><td>{p[field]}</td></tr>"

        cards.append(f"""
<div style="border:1px solid #ddd;border-radius:6px;margin-bottom:14px;overflow:hidden">
  <div style="background:{bg};padding:10px 14px;border-bottom:1px solid #ddd">
    <b>#{p['rank']} {icon} {p['ticker']}</b>
    &nbsp;·&nbsp; {p.get('company_name','')}
    &nbsp;·&nbsp; Score: <b>{p.get('score','—')}</b>
    &nbsp;·&nbsp; Confidence: <b>{confidence}</b>
    &nbsp;·&nbsp; Signal: <b>{p.get('signal','')}</b>
    &nbsp;·&nbsp; ${p.get('current_price','?')}
    &nbsp;·&nbsp; Today: {p.get('day_change_pct',0):+.1f}%
    &nbsp;·&nbsp; Week: {week_chg}
  </div>
  <div style="padding:10px 14px;font-size:12px">
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="width:160px;padding:3px 0;vertical-align:top"><b>Why Picked:</b></td>
          <td style="padding:3px 0">{p.get('why_picked','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Key Catalyst:</b></td>
          <td style="padding:3px 0">{p.get('key_catalyst','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Sector Tailwind:</b></td>
          <td style="padding:3px 0">{p.get('sector_tailwind','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Technical:</b></td>
          <td style="padding:3px 0">{p.get('technical_analysis','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Fundamentals:</b></td>
          <td style="padding:3px 0">{p.get('fundamental_snapshot','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>News:</b></td>
          <td style="padding:3px 0">{p.get('news_summary','—')}
            &nbsp;<span style="color:#888">({p.get('news_sentiment','')})</span></td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Analyst View:</b></td>
          <td style="padding:3px 0">{p.get('analyst_sentiment','—')}</td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Insider Activity:</b></td>
          <td style="padding:3px 0">{p.get('insider_activity','—')}</td></tr>
      {f"<tr><td style='padding:3px 0;vertical-align:top'><b>⚠ Earnings:</b></td><td style='padding:3px 0;color:#b45309'>{p['earnings_warning']}</td></tr>" if p.get('earnings_warning') else ""}
      {extra_rows}
      <tr><td style="padding:3px 0"><b>Trade Levels:</b></td>
          <td style="padding:3px 0">
            Entry: {entry} &nbsp;→&nbsp; Target: {target} &nbsp;·&nbsp;
            Stop: {stop} &nbsp;·&nbsp; Upside: {upside} &nbsp;·&nbsp;
            Horizon: {p.get('time_horizon','—')}
          </td></tr>
      <tr><td style="padding:3px 0;vertical-align:top"><b>Risks:</b></td>
          <td style="padding:3px 0"><ul style="margin:0;padding-left:16px">{risk_html}</ul></td></tr>
    </table>
  </div>
</div>""")

    return "\n".join(cards)


def _free_picks_table(rows: list) -> str:
    """Build an HTML table from a free-mode multi-factor scored rows list."""
    if not rows:
        return "<p><em>No qualifying picks.</em></p>"

    rows_html = ""
    for i, r in enumerate(rows, 1):
        bg    = _SIGNAL_BG.get(r.get("signal", ""), "#fff")
        icon  = _SIGNAL_ICON.get(r.get("signal", ""), "⚪")
        flags = ""
        if r.get("breakout_flag"):
            flags += "🚀 Breakout "
        if r.get("earnings_flag"):
            flags += f"⚠ Earnings {r['earnings_flag']}"
        why   = r.get("why_picked", "")
        sent_lbl  = r.get("sentiment_label", "")
        sent_bull = r.get("sentiment_bullish", 0)
        sent_cell = f"{sent_lbl} ({sent_bull}% 🐂)" if sent_lbl else "—"
        # Analyst cell
        target = r.get("analyst_target")
        if target and r.get("num_analysts", 0) >= 2:
            upside = r.get("analyst_upside_pct", 0)
            up_color = "#16a34a" if upside >= 0 else "#dc2626"
            analyst_cell = (f"${target:.2f} <span style='color:{up_color}'>({upside:+.1f}%)</span>"
                            f"<br><small>{r.get('analyst_consensus','—')} · {r['num_analysts']} analysts</small>")
        else:
            analyst_cell = "—"

        # Insider cell
        ins_net = r.get("insider_net_shares", 0)
        inst    = r.get("inst_pct_held", 0)
        if ins_net > 20_000:
            insider_cell = f"🟢 Buying ({ins_net:+,}sh)"
        elif ins_net < -50_000:
            insider_cell = f"🔴 Selling ({ins_net:+,}sh)"
        else:
            insider_cell = "⚪ Neutral"
        if inst:
            insider_cell += f"<br><small>Inst: {inst:.0f}%</small>"

        # Technical indicators row
        rsi   = r.get("rsi")
        macd  = r.get("macd")
        msig  = r.get("macd_signal")
        mh    = r.get("macd_hist")
        sma50 = r.get("sma50")
        sma200= r.get("sma200")
        bbu   = r.get("bb_upper")
        bbl   = r.get("bb_lower")
        vwap  = r.get("vwap")
        atr_p = r.get("atr_pct")
        price = r.get("current_price", 0)

        rsi_color = "#dc2626" if rsi and rsi > 70 else ("#16a34a" if rsi and rsi < 30 else "#555")
        rsi_str   = f"<span style='color:{rsi_color}'>{rsi:.1f}</span>" if rsi else "—"
        macd_str  = f"{macd:+.3f} / sig {msig:+.3f} / hist {mh:+.3f}" if macd and msig else "—"
        sma_str   = (f"SMA50 ${sma50:.2f} {'🟢' if price > sma50 else '🔴'}" if sma50 else "") + \
                    (f"  SMA200 ${sma200:.2f} {'🟢' if price > sma200 else '🔴'}" if sma200 else "")
        bb_str    = f"BB ${bbl:.2f} – ${bbu:.2f}" if bbu and bbl else "—"
        vwap_str  = f"VWAP ${vwap:.2f} {'🟢' if price > vwap else '🔴'}" if vwap else "—"
        atr_str   = f"ATR {atr_p:.1f}%" if atr_p else "—"

        tech_row = (
            f"<tr style='background:{bg}'>"
            f"<td></td><td colspan='9' style='font-size:11px;color:#444;padding:1px 10px 6px'>"
            f"<b>RSI(14):</b> {rsi_str} &nbsp;│&nbsp; "
            f"<b>MACD:</b> {macd_str} &nbsp;│&nbsp; "
            f"{sma_str} &nbsp;│&nbsp; "
            f"<b>Bollinger:</b> {bb_str} &nbsp;│&nbsp; "
            f"{vwap_str} &nbsp;│&nbsp; "
            f"<b>Volatility:</b> {atr_str}"
            f"</td></tr>"
        )

        rows_html += (
            f"<tr style='background:{bg}'>"
            f"<td><b>#{i}</b></td>"
            f"<td><b>{r['ticker']}</b><br><small>{r.get('type','')}</small></td>"
            f"<td style='text-align:center'><b>{r['score']}</b><br><small>{r.get('confidence','')}% conf</small></td>"
            f"<td>{icon} {r.get('signal','')}</td>"
            f"<td>${r['current_price']:,.2f}<br>"
            f"<small>Day {r.get('day_change_pct',0):+.1f}% / "
            f"1W {r.get('week_change_pct',0):+.1f}% / "
            f"3M {r.get('qtr_change_pct',0):+.1f}%</small></td>"
            f"<td>RS vs SPY: {r.get('rs_vs_spy',0):+.1f}pp<br>"
            f"<small>Vol {r.get('vol_ratio',1):.1f}× | 52w {r.get('pos_52w',50):.0f}%</small></td>"
            f"<td style='color:#555'>{sent_cell}</td>"
            f"<td style='font-size:11px'>{analyst_cell}</td>"
            f"<td style='font-size:11px'>{insider_cell}</td>"
            f"<td style='color:#555'>{flags}</td>"
            f"</tr>"
            + tech_row
            + (f"<tr style='background:{bg}'><td colspan='10' style='font-size:11px;color:#555;padding:2px 10px 8px'>{why}</td></tr>" if why else "")
        )
    return (
        "<table>"
        "<tr><th>Rank</th><th>Ticker</th><th>Score</th><th>Signal</th>"
        "<th>Price / Returns</th><th>Volume / Position</th><th>Sentiment</th>"
        "<th>Analyst Target</th><th>Insider Activity</th><th>Flags</th></tr>"
        f"{rows_html}"
        "</table>"
        "<p style='font-size:11px;color:#888'>"
        "Score weights: 3M mom(18%) + 1M(14%) + 1W(9%) + volume(9%) + RS vs SPY(7%) + "
        "analyst(10%) + insider(5%) + sentiment(5%) + earnings quality(7%) + other(16%)</p>"
    )


def _build_research_html(sections: list[dict], now: datetime, mode: str) -> str:
    """Build the full HTML email body.
    sections: list of {'label': str, 'data': dict|list, 'mode': 'api'|'free'}
    """
    body_parts = [
        f"<h1>Trading Research — {now.strftime('%A, %Y-%m-%d %H:%M ET')}</h1>",
        f"<p style='color:#888;font-size:12px'>Mode: {mode} &nbsp;|&nbsp; "
        f"5 picks per category at 90%+ confidence</p>",
        _fear_greed_banner(),
    ]
    for s in sections:
        body_parts.append(f"<h2>{s['label']}</h2>")
        if s["mode"] == "api" and isinstance(s["data"], dict):
            summary = s["data"].get("market_summary", "")
            if summary:
                body_parts.append(f"<div class='summary'>{summary}</div>")
            body_parts.append(_api_picks_table(s["data"]))
            avoid = s["data"].get("avoid_today", [])
            if avoid:
                body_parts.append(
                    f"<div class='avoid'><b>Avoid today:</b> {', '.join(avoid)}<br>"
                    f"{s['data'].get('avoid_reason','')}</div>"
                )
        else:
            body_parts.append(_free_picks_table(s["data"] or []))

    body_parts.append(
        "<div class='footer'>Research only — no trades have been placed. "
        "Generated by Trading Agent.</div>"
    )
    return f"<!DOCTYPE html><html><head>{_HTML_STYLE}</head><body>"  \
           + "\n".join(body_parts) + "</body></html>"


def send_research_email(html: str, email_cfg: dict, now: datetime) -> None:
    """Send the research HTML as an email to configured recipients."""
    raw          = email_cfg["recipient"]
    recipients   = raw if isinstance(raw, list) else [raw]
    sender       = os.getenv("EMAIL_SENDER") or email_cfg.get("sender", "")
    app_password = "".join(os.getenv("EMAIL_APP_PASSWORD", "").split())
    smtp_host    = email_cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port    = email_cfg.get("smtp_port", 587)

    if not sender:
        logger.error("EMAIL_SENDER env var not set — skipping email.")
        return
    if not app_password:
        logger.error("EMAIL_APP_PASSWORD env var not set — skipping email.")
        return

    subject = f"Trading Research — Top 5 Picks — {now.strftime('%A, %Y-%m-%d')}"
    msg = MIMEMultipart("alternative")
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    logger.info("Sending research email to %s via %s:%d ...",
                ", ".join(recipients), smtp_host, smtp_port)
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, app_password)
        server.sendmail(sender, recipients, msg.as_string())
    logger.info("Research email sent to %s", ", ".join(recipients))


# ---------------------------------------------------------------------------
# Sector infrastructure — labels, guidance, prompts, and orchestration
# ---------------------------------------------------------------------------

SECTOR_LABELS = {
    "technology":  "Technology",
    "pharma":      "Pharma & Biotech",
    "healthcare":  "Healthcare",
    "finance":     "Finance & Banking",
    "energy":      "Energy",
    "consumer":    "Consumer & Retail",
    "industrials": "Industrials",
    "crypto":      "Crypto",
    "penny":       "Penny Stocks",
}

SECTOR_GUIDANCE = {
    "technology":  "Focus on: AI/ML adoption, semiconductor demand, cloud ARR growth, software innovation, competitive moats, and valuation vs growth rate.",
    "pharma":      "Focus on: FDA approval calendar (next 90 days), Phase 2/3 trial readouts, patent cliffs, pipeline value, biotech M&A activity, and drug pricing dynamics.",
    "healthcare":  "Focus on: insurance reimbursement dynamics, hospital utilization, medical device innovation, Medicare/Medicaid policy shifts, and managed care margins.",
    "finance":     "Focus on: net interest margin trends, loan growth vs credit loss provisions, capital adequacy ratios, fee income, and Federal Reserve rate trajectory.",
    "energy":      "Focus on: crude oil/nat-gas futures curve, production guidance, refining crack spreads, capex discipline, OPEC+ decisions, and energy transition exposure.",
    "consumer":    "Focus on: consumer confidence, same-store sales trends, gross margin recovery, inventory normalization, e-commerce penetration, and brand strength.",
    "industrials": "Focus on: order backlog, defense budget trajectory, infrastructure spending, supply chain normalization, pricing power, and international exposure.",
    "crypto":      "Focus on: on-chain metrics (active addresses, transaction volume), institutional inflows, regulatory developments, network upgrades, and DeFi activity.",
}

DEEP_RESEARCH_PROMPT_TEMPLATE = """\
You are a senior equity research analyst at a top-tier investment fund.
Conduct rigorous, data-driven research on the {sector} assets provided.

SECTOR FOCUS
{sector_guidance}

RESEARCH PROCESS — execute ALL steps via web search:
1. Fetch live price, today's % change, volume vs 30-day average, and 52-week range.
2. Search news from the last 7 days for each ticker.
3. Check analyst ratings and mean price target changes in the last 30 days.
4. Identify upcoming catalysts in the next 60-90 days: earnings, product launches, FDA decisions,\
 analyst days, regulatory filings, macro events.
5. Review latest earnings: EPS beat/miss, revenue growth, guidance, margin trend.
6. Assess balance sheet: cash vs debt, free cash flow, any concerns.
7. Check insider transactions (SEC Form 4) in the last 30 days — note any significant purchases\
 or sales by executives or directors.
8. Note institutional ownership trend — rising or falling (positive or negative signal).
9. Flag any stock with earnings within 7 days — this is high event risk; reduce confidence\
 accordingly and include an earnings_warning in the output.

QUALITY BAR:
- Score each stock 0-100 on short-to-medium term opportunity.
- Set confidence 0-100%. Only include if BOTH score >= 90 AND confidence >= 90%.
- Return UP TO {top_n} picks. Fewer is better than including a weak pick.

Respond ONLY with a valid JSON object — no markdown, no text outside the JSON:
{{
  "date": "YYYY-MM-DD",
  "sector": "{sector}",
  "market_summary": "2-3 sentences on {sector} sector conditions and key themes today",
  "top_picks": [
    {{
      "rank": 1,
      "ticker": "NVDA",
      "company_name": "NVIDIA Corporation",
      "current_price": 135.42,
      "day_change_pct": 2.3,
      "week_change_pct": 5.1,
      "score": 95,
      "confidence_pct": 94,
      "signal": "BUY",
      "why_picked": "Specific 2-3 sentence explanation of WHY this is a strong opportunity RIGHT NOW — not generic. Include the data point that convinced you.",
      "technical_analysis": "Price vs 20/50/200 MA, RSI level, volume trend, key support/resistance",
      "fundamental_snapshot": "Revenue growth %, EPS trend, margin profile, key valuation metric vs peers",
      "key_catalyst": "ONE specific upcoming event (with approximate date) most likely to move the stock",
      "sector_tailwind": "The macro or industry trend directly benefiting this specific stock",
      "analyst_sentiment": "e.g. '18 Buy, 5 Hold, 0 Sell — consensus target $240'",
      "insider_activity": "e.g. 'CEO bought 50,000 shares on 2026-06-10' or 'No notable activity in last 30 days'",
      "earnings_warning": "e.g. 'Reports 2026-06-22 — elevated event risk' or null",
      "news_summary": "1-2 most relevant recent headlines and their market impact",
      "news_sentiment": "Positive",
      "suggested_entry": 134.00,
      "target_price": 160.00,
      "stop_loss": 125.00,
      "upside_pct": 18.2,
      "time_horizon": "2-3 months",
      "risk_factors": [
        "Specific risk 1 that could invalidate the thesis",
        "Specific risk 2"
      ]
    }}
  ],
  "avoid_today": ["TICKER1"],
  "avoid_reason": "Specific reason to avoid these tickers today"
}}

Signal: BUY = high conviction buy now | WATCH = interesting but wait for better entry | HOLD = hold existing position.
Only include picks with score >= 90 AND confidence >= 90%. Rank top_picks by score descending.\
"""

PENNY_DEEP_RESEARCH_PROMPT_TEMPLATE = """\
You are a small-cap and penny stock specialist.
Research the provided stocks (all priced under ${max_price}) for high-conviction recovery or growth plays.

KEY QUESTIONS FOR EACH STOCK:
- Why is it cheap? Temporary headwind (sector downturn, one-time loss) or structural decline (dying business)?
- Is the business viable? Real revenue, path to profitability, defensible niche?
- What catalyst could re-rate it? FDA approval, contract win, earnings surprise, strategic pivot?
- Financial runway: months of cash, revenue trajectory, debt burden.
- Market interest: insider buying, institutional accumulation, short interest (squeeze potential)?

AVOID: pure pump plays, zero-revenue shells, companies in terminal decline, fraudulent operators.

QUALITY BAR: Score >= 90 AND confidence >= 90%. Return UP TO {top_n} picks.

Respond ONLY with a valid JSON object:
{{
  "date": "YYYY-MM-DD",
  "sector": "Penny Stocks",
  "market_summary": "2-3 sentences on small-cap / penny stock conditions today",
  "top_picks": [
    {{
      "rank": 1,
      "ticker": "EXAMPLE",
      "company_name": "Example Corp",
      "current_price": 2.45,
      "day_change_pct": 4.2,
      "week_change_pct": 8.1,
      "score": 92,
      "confidence_pct": 91,
      "signal": "BUY",
      "why_picked": "Specific reason why this cheap stock is a genuine opportunity right now",
      "why_its_cheap": "Why the stock trades at this price — and why that condition is temporary",
      "business_viability": "Assessment of business model, revenue, and path forward",
      "key_catalyst": "Specific event that could re-rate the stock (with approximate date)",
      "financial_health": "Cash runway, revenue trend, debt situation",
      "technical_analysis": "Price trend, volume surge, key levels",
      "news_summary": "Most relevant recent news",
      "news_sentiment": "Positive",
      "suggested_entry": 2.40,
      "target_price": 5.00,
      "stop_loss": 1.80,
      "upside_pct": 104.2,
      "time_horizon": "3-6 months",
      "risk_factors": ["Risk 1", "Risk 2"]
    }}
  ],
  "avoid_today": ["TICKER1"],
  "avoid_reason": "Why these penny stocks should be avoided"
}}

Signal: BUY | WATCH | HOLD. Score and confidence 0-100. Only include if both >= 90%. Rank by score descending.\
"""


def _free_why_picked(r: dict) -> str:
    """Generate a human-readable explanation from the multi-factor score."""
    parts = []

    qtr = r.get("qtr_change_pct", 0)
    mon = r.get("month_change_pct", 0)
    chg = r.get("day_change_pct", 0)
    vol = r.get("vol_ratio", 1)
    pos = r.get("pos_52w", 50)
    rs  = r.get("rs_vs_spy", 0)
    eps = r.get("eps_growth_pct", 0)

    if qtr >= 15:
        parts.append(f"strong 3-month momentum (+{qtr:.1f}%)")
    elif qtr >= 5:
        parts.append(f"positive 3-month trend (+{qtr:.1f}%)")
    elif qtr < 0:
        parts.append(f"3-month decline ({qtr:.1f}%)")

    if rs >= 5:
        parts.append(f"outperforming SPY by {rs:.1f}pp over 3 months")
    elif rs <= -5:
        parts.append(f"underperforming SPY by {abs(rs):.1f}pp")

    if mon >= 5:
        parts.append(f"1-month gain of +{mon:.1f}%")

    if chg >= 3:
        parts.append(f"strong day (+{chg:.1f}%)")
    elif chg >= 1:
        parts.append(f"positive day (+{chg:.1f}%)")

    if vol >= 2.5:
        parts.append(f"volume surge {vol:.1f}× average")
    elif vol >= 1.5:
        parts.append(f"elevated volume ({vol:.1f}×)")

    if pos >= 90:
        parts.append(f"near 52-week high ({pos:.0f}%) — breakout zone")
    elif pos >= 70:
        parts.append(f"in upper 52-week range ({pos:.0f}%)")

    if eps and eps >= 10:
        parts.append(f"EPS growth +{eps:.0f}%")

    surp = r.get("eps_surprise_pct", 0)
    if surp and surp >= 5:
        parts.append(f"last EPS beat by {surp:.1f}%")
    elif surp and surp <= -5:
        parts.append(f"last EPS missed by {abs(surp):.1f}%")

    short = r.get("short_pct_float", 0)
    if r.get("squeeze_flag"):
        parts.append(f"squeeze candidate ({short:.0f}% short float + rising price)")
    elif short and short > 20:
        parts.append(f"high short interest {short:.0f}% — potential headwind")

    if r.get("earnings_flag"):
        pen = r.get("earnings_penalty", 0)
        parts.append(f"earnings due {r['earnings_flag']} — elevated volatility expected (−{pen}pt penalty)")

    target = r.get("analyst_target")
    if target and r.get("num_analysts", 0) >= 2:
        upside = r.get("analyst_upside_pct", 0)
        cons   = r.get("analyst_consensus", "")
        parts.append(f"analyst consensus {cons} — mean target ${target:.2f} ({upside:+.1f}% upside, {r['num_analysts']} analysts)")

    ins_net = r.get("insider_net_shares", 0)
    if ins_net > 20_000:
        parts.append(f"insider net buying {ins_net:+,} shares (last 90 days)")
    elif ins_net < -50_000:
        parts.append(f"insider net selling {ins_net:+,} shares (last 90 days)")

    text = "; ".join(parts)
    return (text[0].upper() + text[1:] + ".") if text else "Composite multi-factor score."


def _enrich_dividend(rows: list, max_check: int = 40) -> list:
    """Fetch dividendYield for each row in parallel and add it to the dict."""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    candidates = rows[:max_check]

    def _get(row):
        try:
            info = yf.Ticker(row["ticker"]).info
            row["dividend_yield"] = float(info.get("dividendYield") or 0)
        except Exception:
            row["dividend_yield"] = 0.0
        return row

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(_get, candidates))


def run_sector_free(sector: str, tickers: list, top_n: int,
                    max_price: float | None, now: datetime,
                    dividend_only: bool = False,
                    min_market_cap: int = 10_000_000) -> dict | None:
    """Run free-mode yfinance research for one sector. Returns section dict."""
    label = f"{SECTOR_LABELS.get(sector, sector.title())} — Top {top_n}"
    if sector == "penny":
        rows = fetch_cheap_stocks(
            max_price=max_price or 5.0,
            min_market_cap=min_market_cap,
            limit=max(top_n * 6, 40),
        )
        label = f"Penny Stocks (< ${max_price or 5:.0f}) — Top {top_n}"
    else:
        if sector == "crypto":
            raw = fetch_all_data([], tickers)
        else:
            raw = fetch_all_data(tickers, [])
        rows = sorted(raw, key=lambda x: x["score"], reverse=True)
        if max_price is not None:
            rows = [r for r in rows if r["current_price"] <= max_price]

    if dividend_only and sector != "crypto":
        # Fetch dividend yields for top candidates, then filter
        rows = _enrich_dividend(rows, max_check=min(len(rows), 40))
        rows = [r for r in rows if r.get("dividend_yield", 0) > 0]
        rows = sorted(rows, key=lambda x: x["score"], reverse=True)
        if label and "Top" in label:
            label = label.replace("Top", "Dividend — Top")

    rows = rows[:top_n]
    for r in rows:
        r["why_picked"] = _free_why_picked(r)

    _print_free_table(label, rows, now)
    return {"label": label, "data": rows, "mode": "free", "sector": sector}


def run_sector_api(sector: str, tickers: list, top_n: int,
                   max_price: float | None, now: datetime, client,
                   min_market_cap: int = 10_000_000) -> dict | None:
    """Run deep research API call for one sector. Returns section dict or None."""
    sector_name = SECTOR_LABELS.get(sector, sector.title())

    if sector == "penny":
        screened = fetch_cheap_stocks(
            max_price=max_price or 5.0,
            min_market_cap=min_market_cap,
            limit=min(top_n * 6, 40),
        )
        tickers = [r["ticker"] for r in screened]
        if not tickers:
            logger.warning("Penny screener returned no tickers — skipping.")
            return None
        system_prompt = PENNY_DEEP_RESEARCH_PROMPT_TEMPLATE.format(
            max_price=max_price or 5.0, top_n=top_n,
        )
        user_msg = (
            f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
            f"Research these penny stocks (all under ${max_price or 5:.2f}) and identify "
            f"the top {top_n} genuine opportunities (score >= 90, confidence >= 90%).\n\n"
            f"Tickers: {', '.join(tickers)}"
            + _build_sentiment_block(tickers) +
            "\n\nSearch recent news, financials, catalysts, and business viability for each. "
            f"Return up to {top_n} picks as JSON."
        )
        label = f"Penny Stocks (< ${max_price or 5:.0f}) — Top {top_n} Deep Research"
    else:
        system_prompt = DEEP_RESEARCH_PROMPT_TEMPLATE.format(
            sector=sector_name,
            sector_guidance=SECTOR_GUIDANCE.get(sector, ""),
            top_n=top_n,
        )
        # Pre-compute technical indicators for context
        tech_context = _build_technical_context(tickers)
        user_msg = (
            f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET.\n\n"
            f"Deep research on the following {sector_name} assets. "
            f"Identify the top {top_n} highest-conviction picks (score >= 90, confidence >= 90%).\n\n"
            f"Tickers: {', '.join(tickers)}"
            + tech_context
            + _build_sentiment_block(tickers) +
            "\n\nSearch live prices, last-7-day news, recent earnings, analyst activity, insider "
            f"transactions, and upcoming catalysts. Return up to {top_n} picks as JSON. Quality over quantity."
        )
        label = f"{sector_name} — Top {top_n} Deep Research"

    data = _run_api_single(client, system_prompt, user_msg, label, now)
    if data is None:
        return None
    return {"label": label, "data": data, "mode": "api", "sector": sector}


def run_research(
    config: dict,
    selected_sectors: list,
    mode: str,
    max_price: float | None,
    top_n: int,
    email_cfg: dict | None = None,
    dividend_only: bool = False,
    min_market_cap: int = 10_000_000,
) -> list:
    """
    Main orchestrator for sector-based research.
    If selected_sectors is empty, runs ALL sectors defined in config.
    Returns list of section dicts for the UI to render.
    """
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    all_sector_cfg = config.get("sectors", {})

    if not selected_sectors:
        selected_sectors = list(all_sector_cfg.keys()) + ["penny"]

    sections = []

    if mode == "api":
        import anthropic
        client = anthropic.Anthropic()
    else:
        client = None

    for sector in selected_sectors:
        tickers = all_sector_cfg.get(sector, [])
        if sector != "penny" and not tickers:
            logger.warning("No tickers configured for sector '%s' — skipping.", sector)
            continue

        logger.info("Research [%s] sector=%s tickers=%d", mode, sector, len(tickers))

        if mode == "api":
            section = run_sector_api(sector, tickers, top_n, max_price, now, client,
                                     min_market_cap=min_market_cap)
        else:
            section = run_sector_free(sector, tickers, top_n, max_price, now,
                                      dividend_only=dividend_only,
                                      min_market_cap=min_market_cap)

        if section:
            sections.append(section)

    if email_cfg and sections:
        html = _build_research_html(sections, now, mode)
        send_research_email(html, email_cfg, now)

    return sections


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research top picks")
    parser.add_argument("--top",         type=int,   default=None)
    parser.add_argument("--mode",        choices=["free", "api"], default=None)
    parser.add_argument("--stocks-only", action="store_true")
    parser.add_argument("--crypto-only", action="store_true")
    parser.add_argument("--max-price",   type=float, default=None,
                        help="Only include assets priced below this value (e.g. 5)")
    parser.add_argument("--email",       action="store_true",
                        help="Email the research output to configured recipients")
    args = parser.parse_args()

    config = load_config()
    research_cfg = config.get("research", {})

    mode      = args.mode      or research_cfg.get("mode",      "free")
    top_n     = args.top       or research_cfg.get("top_n",     PICKS_PER_CATEGORY)
    max_price = args.max_price if args.max_price is not None \
                               else research_cfg.get("max_price") or None

    stocks, crypto = build_universe(config, args.stocks_only, args.crypto_only)

    # Default (no category flags, no price filter): dual-category mode —
    # 5 all-stocks picks + 5 penny-stock picks, both at 90%+ confidence.
    dual      = not args.stocks_only and not args.crypto_only and max_price is None
    email_cfg = config.get("email") if args.email else None

    if mode == "api":
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error("mode=api requires ANTHROPIC_API_KEY to be set.")
            raise SystemExit(1)
        run_api(stocks, crypto, top_n, max_price, dual_category=dual, email_cfg=email_cfg)
    else:
        run_free(stocks, crypto, top_n, max_price, dual_category=dual, email_cfg=email_cfg)
