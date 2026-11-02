"""
coingecko.py — CoinGecko global market data client (BTC dominance).

DATA_PIPELINE_PLAN.md §5:
GET https://api.coingecko.com/api/v3/global
Field: data.market_cap_percentage.btc
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel

from app.clients.http import ResilientHttpClient
from app.config import get_settings


class ParsedBtcDominance(BaseModel):
    ts: datetime
    dominance_pct: float


def parse_coingecko_global(raw_data: Dict[str, Any]) -> Optional[ParsedBtcDominance]:
    """Extract BTC dominance percentage from CoinGecko global payload."""
    data = raw_data.get("data", {})
    market_cap_pct = data.get("market_cap_percentage", {})
    btc_pct = market_cap_pct.get("btc")
    if btc_pct is None:
        return None

    # CoinGecko updated_at is unix seconds
    updated_at = data.get("updated_at")
    if updated_at:
        dt = datetime.fromtimestamp(updated_at, tz=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    return ParsedBtcDominance(ts=dt, dominance_pct=float(btc_pct))


class CoinGeckoClient:
    URL = "https://api.coingecko.com/api/v3/global"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.coingecko_api_key
        self.http = ResilientHttpClient()

    def close(self):
        self.http.close()

    def get_btc_dominance(self) -> Optional[ParsedBtcDominance]:
        headers = {}
        if self.api_key:
            headers["x-cg-demo-api-key"] = self.api_key
        resp = self.http.get(self.URL, headers=headers)
        return parse_coingecko_global(resp.json())

