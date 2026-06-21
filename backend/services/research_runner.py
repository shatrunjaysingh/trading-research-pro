"""
Bridges the synchronous run_research() into an async SSE generator.
Each sector completion yields a JSON-serialisable dict.
"""
import asyncio
import json
import logging
import queue
import sys
import os
from concurrent.futures import ThreadPoolExecutor

# Make sure root-level Python files (database.py, auth.py, research.py) are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

_executor = ThreadPoolExecutor(max_workers=4)


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.SimpleQueue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record))


async def stream_research(
    config: dict,
    selected_sectors: list[str],
    mode: str,
    max_price: float | None,
    top_n: int,
    email_cfg: dict | None,
    dividend_only: bool = False,
    min_market_cap: int = 10_000_000,
):
    """
    Async generator yielding SSE-formatted strings.
    Events:
      data: {"type":"progress","message":"..."}
      data: {"type":"section","section":{...}}
      data: {"type":"done"}
      data: {"type":"error","message":"..."}
    """
    from research import run_research   # import here to avoid circular issues at module load

    log_q: queue.SimpleQueue = queue.SimpleQueue()
    handler = _QueueHandler(log_q)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)

    loop = asyncio.get_event_loop()
    result_holder: list = []
    error_holder:  list = []

    def _run():
        try:
            sections = run_research(
                config=config,
                selected_sectors=selected_sectors,
                mode=mode,
                max_price=max_price,
                top_n=top_n,
                email_cfg=email_cfg,
                dividend_only=dividend_only,
                min_market_cap=min_market_cap,
            ) or []
            result_holder.extend(sections)
            # Log free-mode picks to backtest table
            if mode == "free":
                try:
                    from database import log_backtest_picks
                    from datetime import date
                    today_str = date.today().isoformat()
                    for section in sections:
                        picks = section.get("data") or []
                        sector = section.get("sector", "unknown")
                        if isinstance(picks, list):
                            log_backtest_picks(today_str, sector, picks)
                except Exception as exc:
                    logging.getLogger(__name__).warning("Backtest logging failed: %s", exc)
        except Exception as exc:
            error_holder.append(str(exc))
        finally:
            log_q.put(None)   # sentinel

    future = loop.run_in_executor(_executor, _run)

    # Drain log queue while the executor is running
    while True:
        try:
            msg = log_q.get_nowait()
        except queue.Empty:
            if future.done():
                break
            await asyncio.sleep(0.1)
            continue

        if msg is None:   # sentinel
            break

        yield f"data: {json.dumps({'type': 'progress', 'message': msg})}\n\n"

    await future   # propagate any executor exception

    root.removeHandler(handler)

    if error_holder:
        yield f"data: {json.dumps({'type': 'error', 'message': error_holder[0]})}\n\n"
        return

    for section in result_holder:
        # Ensure the section data is JSON-serialisable
        try:
            payload = json.dumps({"type": "section", "section": section})
            yield f"data: {payload}\n\n"
        except TypeError:
            pass

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
