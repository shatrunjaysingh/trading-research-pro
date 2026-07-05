import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import auth, research, admin, profile, analysis, market, prices, watchlist, portfolio
from database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.polygon_api_key:
        from backend.services.polygon_client import init_polygon
        init_polygon(settings.polygon_api_key)
        logger.info("Polygon.io WebSocket client initialised")
    yield
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


@app.get("/health")
def health():
    return {"status": "ok"}
