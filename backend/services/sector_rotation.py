"""Sector rotation heatmap — RS and momentum scores for GICS sector ETFs."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

SECTOR_ETFS = {
    'Technology':              'XLK',
    'Health Care':             'XLV',
    'Financials':              'XLF',
    'Consumer Discretionary':  'XLY',
    'Communication Services':  'XLC',
    'Industrials':             'XLI',
    'Consumer Staples':        'XLP',
    'Energy':                  'XLE',
    'Utilities':               'XLU',
    'Real Estate':             'XLRE',
    'Materials':               'XLB',
}

def _sector_data(sector: str, etf: str, spy_hist) -> dict | None:
    try:
        import yfinance as yf
        import pandas as pd

        hist = yf.Ticker(etf).history(period="1y", interval="1d", auto_adjust=True)
        if len(hist) < 20:
            return None

        close = hist['Close']
        price = float(close.iloc[-1])

        def pct_change(n_days: int) -> float | None:
            if len(close) < n_days + 1:
                return None
            return round((close.iloc[-1] / close.iloc[-(n_days+1)] - 1) * 100, 2)

        ret_1w  = pct_change(5)
        ret_1m  = pct_change(21)
        ret_3m  = pct_change(63)
        ret_ytd = round((close.iloc[-1] / close.iloc[0] - 1) * 100, 2)

        # RS vs SPY
        def spy_ret(n_days: int) -> float | None:
            if spy_hist is None or len(spy_hist) < n_days + 1:
                return None
            sc = spy_hist['Close']
            return (sc.iloc[-1] / sc.iloc[-(n_days+1)] - 1) * 100

        spy_1w = spy_ret(5)
        spy_1m = spy_ret(21)
        spy_3m = spy_ret(63)

        rs_1w = round((ret_1w or 0) - (spy_1w or 0), 2)
        rs_1m = round((ret_1m or 0) - (spy_1m or 0), 2)
        rs_3m = round((ret_3m or 0) - (spy_3m or 0), 2)

        # Trend: is 1W RS improving vs 1M RS?
        trend = 'up' if rs_1w > rs_1m else 'down'

        # Volume ratio
        vol_avg = float(hist['Volume'].rolling(20).mean().iloc[-1]) if len(hist) >= 20 else None
        vol_last = float(hist['Volume'].iloc[-1])
        vol_ratio = round(vol_last / vol_avg, 2) if vol_avg and vol_avg > 0 else None

        # SMA200 position
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        vs_sma200 = round((price / sma200 - 1) * 100, 2) if sma200 else None

        return {
            'sector':    sector,
            'etf':       etf,
            'price':     price,
            'ret_1w':    ret_1w,
            'ret_1m':    ret_1m,
            'ret_3m':    ret_3m,
            'ret_ytd':   ret_ytd,
            'rs_1w':     rs_1w,
            'rs_1m':     rs_1m,
            'rs_3m':     rs_3m,
            'trend':     trend,
            'vol_ratio': vol_ratio,
            'vs_sma200': vs_sma200,
        }
    except Exception as exc:
        logger.debug("Sector data failed for %s: %s", etf, exc)
        return None


def compute_sector_rotation() -> list[dict]:
    import yfinance as yf
    spy_hist = yf.Ticker('SPY').history(period="1y", interval="1d", auto_adjust=True)

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_sector_data, sector, etf, spy_hist): sector
                for sector, etf in SECTOR_ETFS.items()}
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x.get('rs_1m', -999), reverse=True)
    return results
