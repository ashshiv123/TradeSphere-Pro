"""
main.py — FastAPI application entry point.

Registers:
  - Logging
  - Routers (health, data)
  - Startup event (optional DB connectivity check)
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_setup import configure_logging
from app.config import get_settings

settings = get_settings()
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TradeSphere Pro API",
    description="Market data, scoring, risk management, trade execution, and LLM explanations.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.routes_health import router as health_router  # noqa: E402
from app.api.routes_data import router as data_router      # noqa: E402
from app.api.routes_trading import router as trading_router  # noqa: E402

app.include_router(health_router)
app.include_router(data_router)
app.include_router(trading_router)


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup() -> None:
    logger.info("TradeSphere Pro API starting up (log level=%s)", settings.log_level)

