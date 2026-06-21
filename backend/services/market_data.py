"""
Fetch live market overview: major indices, sector ETFs, commodities, crypto.
Uses yfinance fast_info for speed; runs all tickers in parallel threads.
Supports multi-market (US, IN, JP, AU, UK, DE, CA) via the `market` param.
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pytz

logger = logging.getLogger(__name__)

# ── Market-specific indices ───────────────────────────────────────────────────

_MARKET_INDICES: dict[str, dict[str, str]] = {
    "US": {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI":  "Dow Jones",
        "^RUT":  "Russell 2000",
        "^VIX":  "VIX",
    },
    "IN": {
        "^NSEI":    "Nifty 50",
        "^BSESN":   "BSE Sensex",
        "^NSEBANK": "Nifty Bank",
        "^CNXIT":   "Nifty IT",
    },
    "JP": {
        "^N225": "Nikkei 225",
        "^TOPX": "TOPIX",
    },
    "AU": {
        "^AXJO": "ASX 200",
        "^AORD": "All Ordinaries",
    },
    "UK": {
        "^FTSE": "FTSE 100",
        "^FTMC": "FTSE 250",
    },
    "DE": {
        "^GDAXI": "DAX 40",
        "^MDAXI": "MDAX",
    },
    "CA": {
        "^GSPTSE": "S&P/TSX Composite",
    },
}

# ── Market-specific sector proxies (ETFs / index ETFs) ───────────────────────

_MARKET_SECTORS: dict[str, dict[str, str]] = {
    "US": {
        "XLK":  "Technology",
        "XLV":  "Healthcare",
        "XLF":  "Financials",
        "XLE":  "Energy",
        "XLP":  "Consumer Staples",
        "XLY":  "Consumer Disc.",
        "XLI":  "Industrials",
        "XLB":  "Materials",
        "XLRE": "Real Estate",
        "XLU":  "Utilities",
        "XLC":  "Comm. Services",
    },
    "IN": {
        "NIFTYBEES.NS":  "Nifty 50 ETF",
        "BANKBEES.NS":   "Banking ETF",
        "ITBEES.NS":     "IT ETF",
        "PHARMABEES.NS": "Pharma ETF",
        "CPSE.NS":       "PSU ETF",
    },
    "JP": {
        "1306.T": "TOPIX ETF",
        "1321.T": "Nikkei 225 ETF",
        "1615.T": "Banking ETF",
        "1540.T": "Gold ETF",
    },
    "AU": {
        "IOZ.AX": "ASX 200 ETF",
        "VAS.AX": "ASX 300 ETF",
        "MVB.AX": "Banks ETF",
        "QRE.AX": "Resources ETF",
        "VHY.AX": "High Yield ETF",
    },
    "UK": {
        "ISF.L":  "FTSE 100 ETF",
        "VMID.L": "FTSE 250 ETF",
        "IUKP.L": "UK Property ETF",
        "IUKD.L": "UK Dividend ETF",
    },
    "DE": {
        "EXS1.DE": "iShares DAX ETF",
        "EXX3.DE": "iShares MDAX ETF",
        "EXH1.DE": "iShares STOXX 600 ETF",
    },
    "CA": {
        "XIU.TO": "S&P/TSX 60 ETF",
        "XIC.TO": "Core S&P/TSX ETF",
        "XFN.TO": "Financials ETF",
        "XEG.TO": "Energy ETF",
        "XRE.TO": "Real Estate ETF",
    },
}

# ── Market timezone + hours ───────────────────────────────────────────────────

_MARKET_TZ: dict[str, tuple[str, int, int, int, int]] = {
    # (timezone, open_hour, open_min, close_hour, close_min)
    "US": ("America/New_York",  9,  30, 16,  0),
    "IN": ("Asia/Kolkata",      9,  15, 15, 30),
    "JP": ("Asia/Tokyo",        9,   0, 15, 30),
    "AU": ("Australia/Sydney", 10,   0, 16,  0),
    "UK": ("Europe/London",     8,   0, 16, 30),
    "DE": ("Europe/Berlin",     9,   0, 17, 30),
    "CA": ("America/Toronto",   9,  30, 16,  0),
}

# ── Global (market-independent) assets ───────────────────────────────────────

COMMODITIES: dict[str, str] = {
    "GLD": "Gold",
    "SLV": "Silver",
    "USO": "Crude Oil",
    "TLT": "20Y Treasury",
    "UUP": "US Dollar",
}

CRYPTO: dict[str, str] = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "BNB",
}


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _fetch_one(symbol: str, name: str) -> dict:
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        current    = _safe(getattr(fi, "last_price",     None))
        prev_close = _safe(getattr(fi, "previous_close", None))
        high_52w   = _safe(getattr(fi, "year_high",      None))
        low_52w    = _safe(getattr(fi, "year_low",       None))
        open_price = _safe(getattr(fi, "open",           None))
        day_high   = _safe(getattr(fi, "day_high",       None))
        day_low    = _safe(getattr(fi, "day_low",        None))

        change     = round(current - prev_close, 4) if (current and prev_close) else None
        change_pct = round((current - prev_close) / prev_close * 100, 2) if (current and prev_close) else None
        pos_52w    = (
            round((current - low_52w) / (high_52w - low_52w) * 100, 1)
            if (current and high_52w and low_52w and high_52w != low_52w) else None
        )

        return {
            "symbol":     symbol,
            "name":       name,
            "price":      round(current, 4) if current else None,
            "change":     change,
            "change_pct": change_pct,
            "prev_close": round(prev_close, 4) if prev_close else None,
            "open":       round(open_price, 4) if open_price else None,
            "day_high":   round(day_high, 4) if day_high else None,
            "day_low":    round(day_low, 4) if day_low else None,
            "high_52w":   round(high_52w, 4) if high_52w else None,
            "low_52w":    round(low_52w, 4) if low_52w else None,
            "pos_52w":    pos_52w,
        }
    except Exception as exc:
        logger.warning("market_data: failed to fetch %s — %s", symbol, exc)
        return {
            "symbol": symbol, "name": name,
            "price": None, "change": None, "change_pct": None,
            "prev_close": None, "open": None,
            "day_high": None, "day_low": None,
            "high_52w": None, "low_52w": None, "pos_52w": None,
        }


def _is_market_open(market_id: str) -> bool:
    cfg = _MARKET_TZ.get(market_id, _MARKET_TZ["US"])
    tz_name, o_h, o_m, c_h, c_m = cfg
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    dow = now.weekday()  # 0=Mon … 6=Sun
    if dow > 4:
        return False
    open_mins  = o_h * 60 + o_m
    close_mins = c_h * 60 + c_m
    cur_mins   = now.hour * 60 + now.minute
    return open_mins <= cur_mins < close_mins


def fetch_market_overview(market: str = "all") -> dict:
    # Resolve market key — "all" falls back to US indices
    mkey = market.upper() if market and market != "all" else "US"
    indices = _MARKET_INDICES.get(mkey, _MARKET_INDICES["US"])
    sectors = _MARKET_SECTORS.get(mkey, _MARKET_SECTORS["US"])

    all_symbols: dict[str, tuple[str, str]] = {}
    for sym, name in indices.items():
        all_symbols[sym] = ("index", name)
    for sym, name in sectors.items():
        all_symbols[sym] = ("sector", name)
    for sym, name in COMMODITIES.items():
        all_symbols[sym] = ("commodity", name)
    for sym, name in CRYPTO.items():
        all_symbols[sym] = ("crypto", name)

    raw: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {
            ex.submit(_fetch_one, sym, cat_name[1]): (sym, cat_name[0])
            for sym, cat_name in all_symbols.items()
        }
        for fut in as_completed(futures):
            sym, cat = futures[fut]
            data = fut.result()
            data["category"] = cat
            raw[sym] = data

    market_open = _is_market_open(mkey)

    # Build timestamp in the market's local time
    tz_name = _MARKET_TZ.get(mkey, _MARKET_TZ["US"])[0]
    tz = pytz.timezone(tz_name)
    now_local = datetime.now(tz)
    tz_abbr = now_local.strftime("%Z")
    as_of = now_local.strftime(f"%Y-%m-%d %H:%M:%S {tz_abbr}")

    return {
        "as_of":       as_of,
        "market_open": market_open,
        "indices":     [raw[k] for k in indices     if k in raw],
        "sectors":     [raw[k] for k in sectors     if k in raw],
        "commodities": [raw[k] for k in COMMODITIES if k in raw],
        "crypto":      [raw[k] for k in CRYPTO      if k in raw],
    }
