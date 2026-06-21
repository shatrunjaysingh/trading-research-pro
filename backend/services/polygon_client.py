"""
Polygon.io real-time price integration.

Architecture:
  - PolygonClient opens a WebSocket to wss://socket.polygon.io/stocks
    and subscribes to minute-aggregate events (AM.*) for requested tickers.
  - PriceCache is a thread-safe in-memory store updated on every WS message.
  - REST fallback (get_snapshot) is used when the cache is cold or stale.
  - Module-level singletons: price_cache and _client.
  - Call init_polygon(api_key) once on FastAPI startup.
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class LiveQuote:
    ticker: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    volume: int = 0
    vwap: float | None = None
    updated_at: float = field(default_factory=time.time)


class PriceCache:
    """Thread-safe in-memory store of live quotes."""

    def __init__(self) -> None:
        self._data: dict[str, LiveQuote] = {}
        self._lock = threading.Lock()

    def update(self, quote: LiveQuote) -> None:
        with self._lock:
            self._data[quote.ticker] = quote

    def get(self, ticker: str) -> LiveQuote | None:
        with self._lock:
            return self._data.get(ticker.upper())

    def get_all(self) -> dict[str, LiveQuote]:
        with self._lock:
            return dict(self._data)

    def tickers(self) -> set[str]:
        with self._lock:
            return set(self._data.keys())


price_cache = PriceCache()


class PolygonClient:
    WS_URL   = "wss://socket.polygon.io/stocks"
    REST_BASE = "https://api.polygon.io"

    def __init__(self, api_key: str) -> None:
        self.api_key   = api_key
        self._subscribed: set[str] = set()
        self._ws       = None
        self._running  = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[LiveQuote], None]] = []

    # ── public API ─────────────────────────────────────────────────────────────

    def subscribe(self, tickers: list[str]) -> None:
        new = {t.upper() for t in tickers} - self._subscribed
        if not new:
            return
        self._subscribed.update(new)
        if self._ws and self._running and self._loop:
            asyncio.run_coroutine_threadsafe(self._send_subscribe(list(new)), self._loop)

    def add_callback(self, cb: Callable[[LiveQuote], None]) -> None:
        self._callbacks.append(cb)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Try WebSocket first; fall back to REST polling if auth fails
        self._poll_thread = threading.Thread(
            target=self._probe_and_start, daemon=True, name="polygon-init"
        )
        self._poll_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── Startup probe ──────────────────────────────────────────────────────────

    def _probe_and_start(self) -> None:
        """Test WebSocket auth; start WS loop if supported, else fall back to polling."""
        try:
            import websockets, asyncio as _aio

            async def _probe():
                async with websockets.connect(self.WS_URL, open_timeout=8) as ws:
                    await ws.recv()   # connected banner
                    await ws.send(json.dumps({"action": "auth", "params": self.api_key}))
                    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    return any(m.get("status") == "auth_success" for m in resp)

            loop = _aio.new_event_loop()
            ws_ok = loop.run_until_complete(_probe())
            loop.close()
        except Exception:
            ws_ok = False

        if ws_ok:
            logger.info("Polygon WebSocket available — starting real-time stream")
            self._loop   = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._thread_main, daemon=True, name="polygon-ws")
            self._thread.start()
        else:
            logger.info("Polygon WebSocket not available on this plan — using REST polling (60s interval)")
            self._poll_thread2 = threading.Thread(
                target=self._rest_poll_loop, daemon=True, name="polygon-poll"
            )
            self._poll_thread2.start()

    # ── WebSocket internals ────────────────────────────────────────────────────

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ws_loop())

    async def _ws_loop(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — run: pip install websockets")
            return

        backoff = 1
        while self._running:
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20) as ws:
                    self._ws = ws
                    backoff  = 1
                    await ws.send(json.dumps({"action": "auth", "params": self.api_key}))
                    if self._subscribed:
                        await self._send_subscribe(list(self._subscribed))
                    async for raw in ws:
                        for msg in json.loads(raw):
                            await self._handle(msg)
            except Exception as exc:
                self._ws = None
                if self._running:
                    logger.warning("Polygon WS disconnected: %s — retry in %ds", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)

    async def _send_subscribe(self, tickers: list[str]) -> None:
        if self._ws:
            params = ",".join(f"AM.{t}" for t in tickers)
            await self._ws.send(json.dumps({"action": "subscribe", "params": params}))
            logger.debug("Polygon subscribed: %s", params)

    async def _handle(self, msg: dict) -> None:
        ev = msg.get("ev")
        if ev == "auth_success":
            logger.info("Polygon WS authenticated — real-time prices active")
        elif ev == "auth_failed":
            logger.warning("Polygon WS auth failed — falling back to REST polling")
            self._running = False
        elif ev == "AM":
            ticker = msg.get("sym", "")
            if not ticker:
                return
            close  = msg.get("c") or msg.get("vw")
            op     = msg.get("op")   # official session open from Polygon
            prev_q = price_cache.get(ticker)
            prev_c = prev_q.prev_close if prev_q else op

            change_pct: float | None = None
            if close and op and op > 0:
                change_pct = round((close - op) / op * 100, 3)
            elif close and prev_c and prev_c > 0:
                change_pct = round((close - prev_c) / prev_c * 100, 3)

            quote = LiveQuote(
                ticker     = ticker,
                price      = close or 0,
                open       = msg.get("o"),
                high       = msg.get("h"),
                low        = msg.get("l"),
                prev_close = prev_c or op,
                change_pct = change_pct,
                volume     = msg.get("av", 0),
                vwap       = msg.get("vw"),
            )
            price_cache.update(quote)
            for cb in self._callbacks:
                try:
                    cb(quote)
                except Exception:
                    pass

    # ── REST polling fallback (free tier) ────────────────────────────────────

    def _rest_poll_loop(self, interval: int = 60) -> None:
        """Poll Polygon REST for all subscribed tickers every `interval` seconds."""
        while self._running:
            tickers = list(self._subscribed)
            if tickers:
                for ticker in tickers:
                    try:
                        snap = self.get_snapshot(ticker)
                        if snap and snap.get("price"):
                            quote = LiveQuote(
                                ticker     = snap["ticker"],
                                price      = snap["price"],
                                open       = snap.get("open"),
                                high       = snap.get("high"),
                                low        = snap.get("low"),
                                prev_close = snap.get("prev_close"),
                                change_pct = snap.get("change_pct"),
                                volume     = int(snap.get("volume") or 0),
                                vwap       = snap.get("vwap"),
                            )
                            price_cache.update(quote)
                            for cb in self._callbacks:
                                try:
                                    cb(quote)
                                except Exception:
                                    pass
                    except Exception as exc:
                        logger.debug("Poll failed %s: %s", ticker, exc)
                logger.debug("Polygon REST poll complete: %d tickers", len(tickers))
            time.sleep(interval)

    # ── REST API ───────────────────────────────────────────────────────────────

    def get_snapshot(self, ticker: str) -> dict | None:
        """
        Single-ticker quote using free-tier Polygon REST endpoints.
        Uses /prev for previous close and /range/1/day for today's bar.
        The /v2/snapshot endpoint requires a paid tier and is not used.
        """
        try:
            import httpx
            sym   = ticker.strip().upper()
            today = date.today()
            start = today - timedelta(days=5)  # buffer for weekends/holidays

            # Today's daily bar (delayed on free tier, but available)
            r_day = httpx.get(
                f"{self.REST_BASE}/v2/aggs/ticker/{sym}/range/1/day/{start}/{today}",
                params={"adjusted": "true", "sort": "desc", "limit": 2, "apiKey": self.api_key},
                timeout=5,
            )
            bars = r_day.json().get("results") or []
            close      = bars[0]["c"] if bars else None
            day_open   = bars[0].get("o") if bars else None
            day_high   = bars[0].get("h") if bars else None
            day_low    = bars[0].get("l") if bars else None
            day_vol    = bars[0].get("v") if bars else None
            day_vwap   = bars[0].get("vw") if bars else None
            prev_close = bars[1]["c"] if len(bars) >= 2 else None

            # Fallback: /prev endpoint for previous close
            if prev_close is None:
                r_prev = httpx.get(
                    f"{self.REST_BASE}/v2/aggs/ticker/{sym}/prev",
                    params={"apiKey": self.api_key},
                    timeout=5,
                )
                prev_results = r_prev.json().get("results") or []
                prev_close = prev_results[0]["c"] if prev_results else None

            change_pct = None
            if close and prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 3)

            return {
                "ticker":     sym,
                "price":      close,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "volume":     day_vol,
                "vwap":       day_vwap,
                "open":       day_open,
                "high":       day_high,
                "low":        day_low,
                "source":     "polygon_rest",
            }
        except Exception as exc:
            logger.debug("Polygon REST snapshot failed %s: %s", ticker, exc)
            return None

    def get_aggs(self, ticker: str, days: int = 90) -> list[dict]:
        """Historical daily OHLCV bars via Polygon REST."""
        try:
            import httpx
            end   = date.today()
            start = end - timedelta(days=days + 10)
            r = httpx.get(
                f"{self.REST_BASE}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start}/{end}",
                params={"adjusted": "true", "sort": "asc", "limit": 300, "apiKey": self.api_key},
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("results") or []
        except Exception as exc:
            logger.debug("Polygon aggs failed %s: %s", ticker, exc)
            return []


# ── Module-level singletons ───────────────────────────────────────────────────

_client: PolygonClient | None = None


def get_polygon_client() -> PolygonClient | None:
    return _client


def init_polygon(api_key: str) -> PolygonClient:
    global _client
    _client = PolygonClient(api_key)
    _client.start()
    return _client
