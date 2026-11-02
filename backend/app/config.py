"""
config.py — all settings loaded from environment variables / .env file.

Pydantic-settings reads each field from the environment.  No value is
hard-coded here; defaults only exist for the non-secret options that have
a sensible project-wide value.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",          # read from .env when running locally
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",           # ignore env vars not declared here
    )

    # ── Postgres ──────────────────────────────────────────────────────────────
    postgres_user: str = "tradesphere"
    postgres_password: str = ""
    postgres_db: str = "tradesphere"
    database_url: str = ""        # full DSN, e.g. postgresql+psycopg://…

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── External APIs ─────────────────────────────────────────────────────────
    messari_api_key: str = ""     # free at messari.io/account/api
    coingecko_api_key: str = ""   # empty → unauthenticated (free tier)

    # ── Binance base URLs ─────────────────────────────────────────────────────
    binance_futures_rest: str = "https://fapi.binance.com"
    binance_spot_rest: str = "https://api.binance.com"
    binance_futures_ws: str = "wss://fstream.binance.com"

    # ── Universe ──────────────────────────────────────────────────────────────
    symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"
    intervals: str = "4h,1d"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Convenience helpers ───────────────────────────────────────────────────
    @property
    def symbol_list(self) -> List[str]:
        return [s.strip() for s in self.symbols.split(",")]

    @property
    def interval_list(self) -> List[str]:
        return [i.strip() for i in self.intervals.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()

