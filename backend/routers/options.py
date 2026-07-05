import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
from fastapi import APIRouter, HTTPException, Depends
from backend.auth_middleware import get_current_user
import database as db

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/scan")
async def options_scan(tickers: str = "", current_user: dict = Depends(get_current_user)):
    """
    Scan options for unusual activity.
    If tickers is empty, uses the user's watchlist + saved portfolio.
    """
    if tickers.strip():
        ticker_list = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    else:
        user_id = current_user["id"]
        wl = [i["ticker"] for i in db.get_watchlist(user_id)]
        pf = [i["ticker"] for i in db.get_user_portfolio(user_id)]
        ticker_list = list(set(wl + pf))

    if not ticker_list:
        return []
    if len(ticker_list) > 20:
        ticker_list = ticker_list[:20]

    from backend.services.options_scanner import scan_options
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: scan_options(ticker_list))
    return result


@router.get("/chain/{ticker}")
async def options_chain_view(ticker: str, exp: str = "", current_user: dict = Depends(get_current_user)):
    """Return the full options chain for a ticker (nearest expiration if exp not specified)."""
    def _fetch():
        import yfinance as yf
        tk = yf.Ticker(ticker.upper())
        exps = tk.options
        if not exps:
            return None
        use_exp = exp if exp in exps else exps[0]
        chain = tk.option_chain(use_exp)
        def df_to_list(df):
            if df is None or df.empty:
                return []
            df = df.copy()
            for col in df.select_dtypes(include='number').columns:
                df[col] = df[col].where(df[col].notna(), None)
            return df.to_dict(orient='records')
        return {
            "ticker": ticker.upper(),
            "expiration": use_exp,
            "all_expirations": list(exps[:12]),
            "calls": df_to_list(chain.calls),
            "puts":  df_to_list(chain.puts),
        }
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch)
    if not result:
        raise HTTPException(status_code=404, detail=f"No options data for {ticker}")
    return result
