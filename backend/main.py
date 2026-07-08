import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import auth, research, admin, profile, analysis, market, prices, watchlist, portfolio, alerts, earnings, options, journal
from database import init_db

logger = logging.getLogger(__name__)


async def _digest_scheduler():
    """Background coroutine: checks every 5 minutes and fires digest at 9am ET on weekdays."""
    from datetime import date
    last_run_date: date | None = None

    while True:
        try:
            await asyncio.sleep(300)   # check every 5 minutes
            # Check price alerts every cycle
            try:
                from backend.services.price_alert_checker import check_price_alerts
                check_result = await asyncio.get_event_loop().run_in_executor(None, check_price_alerts)
                if check_result.get("triggered", 0) > 0:
                    logger.info("Alert checker: triggered %d alerts", check_result["triggered"])
            except Exception as exc:
                logger.error("Price alert checker error: %s", exc)

            try:
                from zoneinfo import ZoneInfo
                et = ZoneInfo("America/New_York")
            except ImportError:
                import pytz
                et = pytz.timezone("America/New_York")

            from datetime import datetime
            now    = datetime.now(et)
            today  = now.date()
            # Fire between 09:00–09:30 ET on weekdays, once per day
            if (now.weekday() < 5
                    and now.hour == 9
                    and now.minute < 30
                    and last_run_date != today):
                logger.info("Scheduler: running daily digest")
                from backend.services.daily_digest import run_daily_digest
                result = await asyncio.get_event_loop().run_in_executor(None, run_daily_digest)
                last_run_date = today
                logger.info("Scheduler: digest complete — %s", result)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Digest scheduler error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.polygon_api_key:
        from backend.services.polygon_client import init_polygon
        init_polygon(settings.polygon_api_key)
        logger.info("Polygon.io WebSocket client initialised")

    # Start background digest scheduler
    scheduler_task = asyncio.create_task(_digest_scheduler())
    logger.info("Daily digest scheduler started")

    yield

    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    from backend.services.polygon_client import get_polygon_client
    client = get_polygon_client()
    if client:
        client.stop()


app = FastAPI(
    title="Trading Research Pro API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api/v1")
app.include_router(research.router, prefix="/api/v1")
app.include_router(admin.router,    prefix="/api/v1")
app.include_router(profile.router,  prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(market.router,     prefix="/api/v1")
app.include_router(prices.router,     prefix="/api/v1")
app.include_router(watchlist.router,  prefix="/api/v1")
app.include_router(portfolio.router,  prefix="/api/v1")
app.include_router(alerts.router,     prefix="/api/v1")
app.include_router(earnings.router, prefix="/api/v1")
app.include_router(options.router,  prefix="/api/v1")
app.include_router(journal.router,   prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
