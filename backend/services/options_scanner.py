"""Options flow scanner — put/call ratio, unusual volume, IV percentile from yfinance."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def _scan_one(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        import math

        tk = yf.Ticker(ticker)
        exps = tk.options
        if not exps:
            return None

        # Use the nearest 3 expirations
        near_exps = exps[:3]
        total_call_vol = 0; total_put_vol = 0
        total_call_oi  = 0; total_put_oi  = 0
        all_ivs = []
        unusual_calls = []; unusual_puts = []

        for exp in near_exps:
            try:
                chain = tk.option_chain(exp)
                calls = chain.calls; puts = chain.puts

                cv = int(calls['volume'].sum()) if 'volume' in calls.columns else 0
                pv = int(puts['volume'].sum())  if 'volume' in puts.columns  else 0
                co = int(calls['openInterest'].sum()) if 'openInterest' in calls.columns else 0
                po = int(puts['openInterest'].sum())  if 'openInterest' in puts.columns  else 0

                total_call_vol += cv; total_put_vol += pv
                total_call_oi  += co; total_put_oi  += po

                # Collect IVs
                if 'impliedVolatility' in calls.columns:
                    all_ivs += [float(v) for v in calls['impliedVolatility'].dropna() if v < 5]
                if 'impliedVolatility' in puts.columns:
                    all_ivs += [float(v) for v in puts['impliedVolatility'].dropna() if v < 5]

                # Unusual volume: vol/OI > 3x and vol > 100
                def find_unusual(df, option_type):
                    if df.empty or 'volume' not in df.columns or 'openInterest' not in df.columns:
                        return []
                    rows = []
                    for _, r in df.iterrows():
                        vol = r.get('volume', 0) or 0
                        oi  = r.get('openInterest', 1) or 1
                        iv  = r.get('impliedVolatility', 0) or 0
                        if vol > 200 and vol / max(oi, 1) > 2.0:
                            rows.append({
                                "type": option_type, "exp": exp,
                                "strike": float(r.get('strike', 0)),
                                "volume": int(vol), "open_interest": int(oi),
                                "vol_oi_ratio": round(vol / max(oi, 1), 2),
                                "iv": round(float(iv) * 100, 1),
                                "last_price": float(r.get('lastPrice', 0)),
                            })
                    return sorted(rows, key=lambda x: x['vol_oi_ratio'], reverse=True)[:3]

                unusual_calls += find_unusual(calls, 'call')
                unusual_puts  += find_unusual(puts,  'put')

            except Exception:
                continue

        put_call_ratio = round(total_put_vol / max(total_call_vol, 1), 2)
        avg_iv = round(sum(all_ivs) / len(all_ivs) * 100, 1) if all_ivs else None

        # Signal based on P/C ratio
        if put_call_ratio > 1.5:
            pc_signal = "bearish"
        elif put_call_ratio < 0.6:
            pc_signal = "bullish"
        else:
            pc_signal = "neutral"

        unusual = (unusual_calls + unusual_puts)
        unusual.sort(key=lambda x: x['vol_oi_ratio'], reverse=True)

        fi = tk.fast_info
        price = float(fi.last_price) if fi.last_price else None

        return {
            "ticker":           ticker,
            "price":            price,
            "put_call_ratio":   put_call_ratio,
            "pc_signal":        pc_signal,
            "total_call_vol":   total_call_vol,
            "total_put_vol":    total_put_vol,
            "total_call_oi":    total_call_oi,
            "total_put_oi":     total_put_oi,
            "avg_iv_pct":       avg_iv,
            "unusual_activity": unusual[:5],
            "expirations_used": list(near_exps),
        }
    except Exception as exc:
        logger.debug("Options scan failed for %s: %s", ticker, exc)
        return None


def scan_options(tickers: list[str]) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_scan_one, t): t for t in tickers}
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda x: len(x.get('unusual_activity', [])), reverse=True)
    return results
