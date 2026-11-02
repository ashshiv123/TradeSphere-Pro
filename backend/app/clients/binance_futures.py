"""
binance_futures.py — Binance USDⓈ-M Futures REST client and response parsers.

Parses endpoints verified during Stage 1 discovery against saved fixtures:
- /fapi/v1/klines (12 columns)
- /fapi/v1/fundingRate (DEV-002: rateType)
- /futures/data/openInterestHist (DEV-003: CMCCirculatingSupply)
- /futures/data/globalLongShortAccountRatio, topLongShortAccountRatio, topLongShortPositionRatio (DEV-004)
- /fapi/v1/premiumIndex (DEV-005)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from app.clients.http import ResilientHttpClient
from app.config import get_settings


class ParsedCandle(BaseModel):
    market: str = "futures"
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: Optional[float] = None
    trades: Optional[int] = None
    taker_buy_base: Optional[float] = None
    taker_buy_quote: Optional[float] = None
    is_closed: bool = True


class ParsedFundingRate(BaseModel):
    symbol: str
    funding_time: datetime
    funding_rate: float
    mark_price: Optional[float] = None
    rate_type: Optional[str] = None


class ParsedOpenInterest(BaseModel):
    symbol: str
    period: str
    ts: datetime
    sum_open_interest: Optional[float] = None
    sum_open_interest_value: Optional[float] = None
    cmc_circulating_supply: Optional[float] = None


class ParsedLongShortRatio(BaseModel):
    symbol: str
    ratio_type: str
    period: str
    ts: datetime
    long_share: float
    short_share: float
    long_short_ratio: float


class ParsedPremiumSnapshot(BaseModel):
    symbol: str
    ts: datetime
    mark_price: float
    index_price: float
    funding_rate: Optional[float] = None
    next_funding_time: Optional[datetime] = None


# ── Standalone Parsers (Testable with JSON fixtures without live network) ─────

def parse_futures_klines(raw_data: List[List[Any]], symbol: str, interval: str) -> List[ParsedCandle]:
    """Parse raw 12-element Binance kline rows (DEV-006)."""
    candles = []
    for row in raw_data:
        open_time = datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
        close_time = datetime.fromtimestamp(row[6] / 1000.0, tz=timezone.utc)
        c = ParsedCandle(
            market="futures",
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


def parse_funding_rates(raw_data: List[Dict[str, Any]]) -> List[ParsedFundingRate]:
    """Parse fundingRate response objects (DEV-002: includes rateType)."""
    rates = []
    for item in raw_data:
        ft = datetime.fromtimestamp(item["fundingTime"] / 1000.0, tz=timezone.utc)
        r = ParsedFundingRate(
            symbol=item["symbol"].upper(),
            funding_time=ft,
            funding_rate=float(item["fundingRate"]),
            mark_price=float(item["markPrice"]) if item.get("markPrice") else None,
            rate_type=item.get("rateType"),
        )
        rates.append(r)
    return rates


def parse_open_interest(raw_data: List[Dict[str, Any]], period: str = "4h") -> List[ParsedOpenInterest]:
    """Parse openInterestHist response objects (DEV-003: CMCCirculatingSupply)."""
    records = []
    for item in raw_data:
        ts = datetime.fromtimestamp(item["timestamp"] / 1000.0, tz=timezone.utc)
        rec = ParsedOpenInterest(
            symbol=item["symbol"].upper(),
            period=period,
            ts=ts,
            sum_open_interest=float(item["sumOpenInterest"]) if item.get("sumOpenInterest") else None,
            sum_open_interest_value=float(item["sumOpenInterestValue"]) if item.get("sumOpenInterestValue") else None,
            cmc_circulating_supply=float(item["CMCCirculatingSupply"]) if item.get("CMCCirculatingSupply") else None,
        )
        records.append(rec)
    return records


def parse_long_short_ratio(raw_data: List[Dict[str, Any]], ratio_type: str, period: str = "4h") -> List[ParsedLongShortRatio]:
    """Parse global/top long-short ratios (DEV-004: longAccount/shortAccount mapping)."""
    records = []
    for item in raw_data:
        ts = datetime.fromtimestamp(item["timestamp"] / 1000.0, tz=timezone.utc)
        rec = ParsedLongShortRatio(
            symbol=item["symbol"].upper(),
            ratio_type=ratio_type,
            period=period,
            ts=ts,
            long_share=float(item["longAccount"]),
            short_share=float(item["shortAccount"]),
            long_short_ratio=float(item["longShortRatio"]),
        )
        records.append(rec)
    return records


def parse_premium_index(raw_data: Dict[str, Any]) -> ParsedPremiumSnapshot:
    """Parse premiumIndex endpoint (DEV-005)."""
    ts = datetime.fromtimestamp(raw_data["time"] / 1000.0, tz=timezone.utc)
    nft = None
    if raw_data.get("nextFundingTime"):
        nft = datetime.fromtimestamp(raw_data["nextFundingTime"] / 1000.0, tz=timezone.utc)

    return ParsedPremiumSnapshot(
        symbol=raw_data["symbol"].upper(),
        ts=ts,
        mark_price=float(raw_data["markPrice"]),
        index_price=float(raw_data["indexPrice"]),
        funding_rate=float(raw_data["lastFundingRate"]) if raw_data.get("lastFundingRate") else None,
        next_funding_time=nft,
    )


# ── Client Class ─────────────────────────────────────────────────────────────

class BinanceFuturesClient:
    def __init__(self, base_url: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.binance_futures_rest).rstrip("/")
        self.http = ResilientHttpClient()

    def close(self):
        self.http.close()

    def get_klines(self, symbol: str, interval: str = "4h", limit: int = 1500, start_time: Optional[int] = None) -> List[ParsedCandle]:
        url = f"{self.base_url}/fapi/v1/klines"
        params: Dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        resp = self.http.get(url, params=params)
        return parse_futures_klines(resp.json(), symbol=symbol, interval=interval)

    def get_funding_rates(self, symbol: str, limit: int = 1000, start_time: Optional[int] = None) -> List[ParsedFundingRate]:
        url = f"{self.base_url}/fapi/v1/fundingRate"
        params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": limit}
        if start_time:
            params["startTime"] = start_time
        resp = self.http.get(url, params=params)
        return parse_funding_rates(resp.json())

    def get_open_interest_hist(self, symbol: str, period: str = "4h", limit: int = 500, start_time: Optional[int] = None) -> List[ParsedOpenInterest]:
        url = f"{self.base_url}/futures/data/openInterestHist"
        params: Dict[str, Any] = {"symbol": symbol.upper(), "period": period, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        resp = self.http.get(url, params=params)
        return parse_open_interest(resp.json(), period=period)

    def get_global_long_short_ratio(self, symbol: str, period: str = "4h", limit: int = 500) -> List[ParsedLongShortRatio]:
        url = f"{self.base_url}/futures/data/globalLongShortAccountRatio"
        resp = self.http.get(url, params={"symbol": symbol.upper(), "period": period, "limit": limit})
        return parse_long_short_ratio(resp.json(), ratio_type="global_account", period=period)

    def get_top_long_short_position_ratio(self, symbol: str, period: str = "4h", limit: int = 500) -> List[ParsedLongShortRatio]:
        url = f"{self.base_url}/futures/data/topLongShortPositionRatio"
        resp = self.http.get(url, params={"symbol": symbol.upper(), "period": period, "limit": limit})
        return parse_long_short_ratio(resp.json(), ratio_type="top_position", period=period)

    def get_premium_index(self, symbol: str) -> ParsedPremiumSnapshot:
        url = f"{self.base_url}/fapi/v1/premiumIndex"
        resp = self.http.get(url, params={"symbol": symbol.upper()})
        return parse_premium_index(resp.json())

