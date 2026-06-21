"""
Social sentiment fetcher — StockTwits + CNN Fear & Greed + Crypto Fear & Greed.

Sources (all require zero API keys):
  StockTwits        — per-ticker bullish/bearish message counts
  CNN Fear & Greed  — macro market sentiment index (stocks)
  Alternative.me    — dedicated crypto fear & greed index

Reddit requires OAuth registration.  If you add REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET to .env it will be included automatically.

Results are cached in-process for 30 minutes.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── In-process cache {ticker -> (result_dict, fetched_at)} ───────────────────
_CACHE: dict[str, tuple[dict, datetime]] = {}
_CACHE_TTL = timedelta(minutes=30)

# Shared macro caches — refreshed once per session
_CNN_FG_CACHE:    Optional[tuple[int, str, datetime]] = None   # (score, label, fetched_at)
_CRYPTO_FG_CACHE: Optional[tuple[int, str, datetime]] = None

# Reddit OAuth token cache — (token, expires_at)
_REDDIT_TOKEN_CACHE: Optional[tuple[str, datetime]] = None

# Compiled sentiment keyword patterns (module-level so they're built once)
_BULL = re.compile(
    r"\b(bull(?:ish)?|long|calls?|moon(?:ing)?|buy|buying|bought|breakout|squeeze|"
    r"rally|ripping|rip|upside|beat|beats|strong|surge|pumping|rocket|ATH|"
    r"green|gains?|winner|printing)\b",
    re.IGNORECASE,
)
_BEAR = re.compile(
    r"\b(bear(?:ish)?|short|puts?|dump(?:ing)?|crash(?:ing)?|sell|selling|sold|"
    r"downside|miss(?:es)?|weak|tank(?:ing)?|falling|fall|red|loss(?:es)?|"
    r"baghold(?:er|ing)?|rug|rekt|down)\b",
    re.IGNORECASE,
)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "TradingResearch/1.0 (research bot; contact ssingh327@gmail.com)",
    "Accept":     "application/json",
})

_CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "XLM", "BCH", "BNB", "XRP", "DOT", "MATIC", "UNI", "ATOM",
    "ALGO", "VET", "SHIB", "NEAR",
}


def _cached(ticker: str) -> Optional[dict]:
    entry = _CACHE.get(ticker)
    if entry:
        result, fetched_at = entry
        if datetime.utcnow() - fetched_at < _CACHE_TTL:
            return result
    return None


def _store(ticker: str, result: dict) -> dict:
    _CACHE[ticker] = (result, datetime.utcnow())
    return result


def _neutral() -> dict:
    return {
        "bullish_pct":      50,
        "bearish_pct":      50,
        "message_volume":   0,
        "st_bullish":       0,
        "st_bearish":       0,
        "st_total":         0,
        "reddit_mentions":  0,
        "fg_score":         None,
        "fg_label":         None,
        "sentiment_score":  50,
        "sentiment_label":  "Neutral",
        "sources":          [],
    }


# ── StockTwits ────────────────────────────────────────────────────────────────

def _fetch_stocktwits(ticker: str) -> tuple[int, int, int]:
    """Return (bullish, bearish, total) message counts."""
    st_ticker = ticker.replace("-USD", "").replace("-", ".")
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{st_ticker}.json?limit=30"
    try:
        resp = _SESSION.get(url, timeout=6)
        if resp.status_code in (429, 403):
            logger.debug("StockTwits rate-limited for %s", ticker)
            return 0, 0, 0
        if resp.status_code != 200:
            return 0, 0, 0
        messages = resp.json().get("messages", [])
        bull = bear = 0
        for m in messages:
            basic = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            if basic == "Bullish":
                bull += 1
            elif basic == "Bearish":
                bear += 1
        return bull, bear, len(messages)
    except Exception as exc:
        logger.debug("StockTwits error %s: %s", ticker, exc)
        return 0, 0, 0


# ── CNN Fear & Greed (stocks macro) ──────────────────────────────────────────

def _fetch_cnn_fear_greed() -> tuple[int, str]:
    """
    Return (score 0-100, label) from CNN Fear & Greed.
    Score > 50 = Greed (bullish), < 50 = Fear (bearish).
    Cached for the session lifetime.
    """
    global _CNN_FG_CACHE
    if _CNN_FG_CACHE:
        score, label, fetched_at = _CNN_FG_CACHE
        if datetime.utcnow() - fetched_at < _CACHE_TTL:
            return score, label

    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        resp = _SESSION.get(url, timeout=8)
        if resp.status_code != 200:
            return 50, "Neutral"
        data  = resp.json()
        score = int(round(float(data["fear_and_greed"]["score"])))
        label = data["fear_and_greed"]["rating"].replace("_", " ").title()
        _CNN_FG_CACHE = (score, label, datetime.utcnow())
        logger.info("CNN Fear & Greed: %d (%s)", score, label)
        return score, label
    except Exception as exc:
        logger.debug("CNN F&G error: %s", exc)
        return 50, "Neutral"


# ── Alternative.me Crypto Fear & Greed ───────────────────────────────────────

def _fetch_crypto_fear_greed() -> tuple[int, str]:
    """Return (score 0-100, label) for the overall crypto market."""
    global _CRYPTO_FG_CACHE
    if _CRYPTO_FG_CACHE:
        score, label, fetched_at = _CRYPTO_FG_CACHE
        if datetime.utcnow() - fetched_at < _CACHE_TTL:
            return score, label

    try:
        resp = _SESSION.get("https://api.alternative.me/fng/?limit=1", timeout=6)
        if resp.status_code != 200:
            return 50, "Neutral"
        entry = resp.json()["data"][0]
        score = int(entry["value"])
        label = entry["value_classification"]
        _CRYPTO_FG_CACHE = (score, label, datetime.utcnow())
        logger.info("Crypto Fear & Greed: %d (%s)", score, label)
        return score, label
    except Exception as exc:
        logger.debug("Crypto F&G error: %s", exc)
        return 50, "Neutral"


# ── Reddit (optional — requires env credentials) ──────────────────────────────

_REDDIT_UA = "TradingResearch:v1.0 (by /u/tradingresearchbot)"
_REDDIT_SUBS = "wallstreetbets+stocks+investing+StockMarket+pennystocks+cryptocurrency"


def _get_reddit_token() -> str:
    """Return a cached Reddit OAuth token, fetching a new one only when expired."""
    global _REDDIT_TOKEN_CACHE
    if _REDDIT_TOKEN_CACHE:
        token, expires_at = _REDDIT_TOKEN_CACHE
        if datetime.utcnow() < expires_at:
            return token

    client_id     = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return ""

    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _REDDIT_UA},
            timeout=8,
        )
        if resp.status_code != 200:
            logger.warning("Reddit token fetch failed: %s", resp.status_code)
            return ""
        data       = resp.json()
        token      = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 3600))
        _REDDIT_TOKEN_CACHE = (token, datetime.utcnow() + timedelta(seconds=expires_in - 60))
        logger.info("Reddit OAuth token obtained (expires in %ds)", expires_in)
        return token
    except Exception as exc:
        logger.debug("Reddit token error: %s", exc)
        return ""


def _fetch_reddit_oauth(ticker: str) -> tuple[int, int, int]:
    """
    Return (post_count, bull_score 0-100, post_count) via Reddit OAuth.
    Only runs when REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are set in .env.
    Searches wallstreetbets, stocks, investing, StockMarket, pennystocks, cryptocurrency.
    """
    token = _get_reddit_token()
    if not token:
        return 0, 50, 0

    clean = ticker.replace("-USD", "")
    headers = {"Authorization": f"bearer {token}", "User-Agent": _REDDIT_UA}

    try:
        url = (
            f"https://oauth.reddit.com/r/{_REDDIT_SUBS}/search.json"
            f"?q={clean}&sort=new&limit=25&t=day&restrict_sr=on"
        )
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 401:
            # Token may have been invalidated; clear cache so next call re-fetches
            global _REDDIT_TOKEN_CACHE
            _REDDIT_TOKEN_CACHE = None
            return 0, 50, 0
        if resp.status_code != 200:
            logger.debug("Reddit search %s: HTTP %s", ticker, resp.status_code)
            return 0, 50, 0

        posts     = resp.json().get("data", {}).get("children", [])
        bull_hits = bear_hits = 0
        for post in posts:
            d    = post.get("data", {})
            text = f"{d.get('title', '')} {d.get('selftext', '')}"
            bull_hits += len(_BULL.findall(text))
            bear_hits += len(_BEAR.findall(text))

        rd_score = 50
        if bull_hits + bear_hits > 0:
            rd_score = int(round(bull_hits / (bull_hits + bear_hits) * 100))
        logger.debug("Reddit %s: %d posts  bull=%d bear=%d score=%d",
                     ticker, len(posts), bull_hits, bear_hits, rd_score)
        return len(posts), rd_score, len(posts)
    except Exception as exc:
        logger.debug("Reddit OAuth error %s: %s", ticker, exc)
        return 0, 50, 0


# ── Public API ────────────────────────────────────────────────────────────────

def get_social_sentiment(ticker: str) -> dict:
    """
    Fetch and aggregate social + macro sentiment for *ticker*.

    Sources:
      - StockTwits        (per-ticker, always attempted)
      - CNN Fear & Greed  (macro, stocks only)
      - Alternative.me    (macro, crypto only)
      - Reddit            (per-ticker, only when env creds are set)

    Returns a dict ready to merge into the _score_asset result.
    """
    cached = _cached(ticker)
    if cached is not None:
        return cached

    is_crypto = ticker.replace("-USD", "") in _CRYPTO_TICKERS
    sources:   list[str] = []

    # ── StockTwits (per-ticker) ────────────────────────────────────────────
    st_bull, st_bear, st_total = _fetch_stocktwits(ticker)
    if st_total:
        sources.append("StockTwits")

    time.sleep(0.2)

    # ── Macro fear & greed ────────────────────────────────────────────────
    if is_crypto:
        fg_score, fg_label = _fetch_crypto_fear_greed()
        sources.append("Crypto F&G")
    else:
        fg_score, fg_label = _fetch_cnn_fear_greed()
        sources.append("CNN F&G")

    # ── Reddit (optional) ─────────────────────────────────────────────────
    rd_posts, rd_score, _ = _fetch_reddit_oauth(ticker)
    if rd_posts:
        sources.append("Reddit")

    # ── Combine ────────────────────────────────────────────────────────────
    st_score = 50.0
    if st_bull + st_bear > 0:
        st_score = st_bull / (st_bull + st_bear) * 100

    # Weight: StockTwits 50% · Fear&Greed 35% · Reddit 15% (if present)
    if rd_posts:
        raw = 0.50 * st_score + 0.35 * fg_score + 0.15 * rd_score
    elif st_total:
        raw = 0.60 * st_score + 0.40 * fg_score
    else:
        raw = float(fg_score)

    sentiment_score = int(round(min(max(raw, 0), 100)))
    bullish_pct     = sentiment_score
    bearish_pct     = 100 - sentiment_score

    if sentiment_score >= 65:
        label = "Bullish"
    elif sentiment_score >= 55:
        label = "Leaning Bullish"
    elif sentiment_score >= 45:
        label = "Neutral"
    elif sentiment_score >= 35:
        label = "Leaning Bearish"
    else:
        label = "Bearish"

    result = {
        "bullish_pct":     bullish_pct,
        "bearish_pct":     bearish_pct,
        "message_volume":  st_total + rd_posts,
        "st_bullish":      st_bull,
        "st_bearish":      st_bear,
        "st_total":        st_total,
        "reddit_mentions": rd_posts,
        "fg_score":        fg_score,
        "fg_label":        fg_label,
        "sentiment_score": sentiment_score,
        "sentiment_label": label,
        "sources":         sources,
    }
    return _store(ticker, result)
