"""
binance_spot.py — Binance Spot REST client and kline parser.

DATA_PIPELINE_PLAN.md §5:
GET https://api.binance.com/api/v3/klines
Used for spot candles in F8 (Perp-Spot Basis).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.clients.binance_futures import ParsedCandle
from app.clients.http import ResilientHttpClient
from app.config import get_settings


def parse_spot_klines(raw_data: List[List[Any]], symbol: str, interval: str) -> List[ParsedCandle]:
    """Parse raw 12-element Binance Spot klines."""
    candles = []
    for row in raw_data:
        open_time = datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
        close_time = datetime.fromtimestamp(row[6] / 1000.0, tz=timezone.utc)
        c = ParsedCandle(
            market="spot",
            symbol=symbol.upper(),
            interval=interval,
            open_time=open_time,
            close_time=close_time,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            quote_volume=float(row[7]) if row[7] is not None else None,
            trades=int(row[8]) if row[8] is not None else None,
            taker_buy_base=float(row[9]) if row[9] is not None else None,
            taker_buy_quote=float(row[10]) if row[10] is not None else None,
            is_closed=True,
        )
        candles.append(c)
    return candles


class BinanceSpotClient:
    def __init__(self, base_url: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.binance_spot_rest).rstrip("/")
        self.http = ResilientHttpClient()

    def close(self):
        self.http.close()

    def get_klines(self, symbol: str, interval: str = "4h", limit: int = 1000, start_time: Optional[int] = None) -> List[ParsedCandle]:
        url = f"{self.base_url}/api/v3/klines"
        params: Dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        resp = self.http.get(url, params=params)
        return parse_spot_klines(resp.json(), symbol=symbol, interval=interval)
