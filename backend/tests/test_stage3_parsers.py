"""
test_stage3_parsers.py — Unit tests for API parsers using saved JSON fixtures from Stage 1.

Verifies:
1. Futures klines (12 columns parsed correctly).
2. Spot klines (12 columns parsed correctly).
3. Funding rates (rateType parsed correctly, DEV-002).
4. Open interest (CMCCirculatingSupply parsed, DEV-003).
5. Global and top Long/Short ratios (longAccount/shortAccount mapped, DEV-004).
6. Premium index snapshots (markPrice, indexPrice, lastFundingRate parsed, DEV-005).
7. Fear & Greed Index (string value and timestamp parsed to int, DEV-007).
8. CoinGecko global market data (data.market_cap_percentage.btc).
9. Messari news parser & VADER sentiment scoring.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.clients.binance_futures import (
    parse_funding_rates,
    parse_futures_klines,
    parse_long_short_ratio,
    parse_open_interest,
    parse_premium_index,
)
from app.clients.binance_spot import parse_spot_klines
from app.clients.coingecko import parse_coingecko_global
from app.clients.fear_greed import parse_fear_greed
from app.clients.messari import parse_messari_news

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str):
    path = FIXTURES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_futures_klines():
    raw = load_fixture("futures_klines_BTCUSDT.json")
    candles = parse_futures_klines(raw, symbol="BTCUSDT", interval="4h")
    assert len(candles) == len(raw)
    c0 = candles[0]
    assert c0.symbol == "BTCUSDT"
    assert c0.market == "futures"
    assert c0.close > 0
    assert c0.high >= c0.low
    assert c0.volume > 0


def test_parse_spot_klines():
    raw = load_fixture("spot_klines_BTCUSDT.json")
    candles = parse_spot_klines(raw, symbol="BTCUSDT", interval="4h")
    assert len(candles) == len(raw)
    c0 = candles[0]
    assert c0.market == "spot"
    assert c0.close > 0


def test_parse_funding_rates():
    raw = load_fixture("futures_funding_BTCUSDT.json")
    rates = parse_funding_rates(raw)
    assert len(rates) == len(raw)
    r0 = rates[0]
    assert r0.symbol == "BTCUSDT"
    assert r0.rate_type == "Regular"  # DEV-002
    assert isinstance(r0.funding_rate, float)


def test_parse_open_interest():
    raw = load_fixture("futures_oi_hist_BTCUSDT.json")
    records = parse_open_interest(raw, period="4h")
    assert len(records) == len(raw)
    rec0 = records[0]
    assert rec0.symbol == "BTCUSDT"
    assert rec0.sum_open_interest_value is not None
    assert rec0.cmc_circulating_supply is not None  # DEV-003


def test_parse_long_short_ratios():
    raw_global = load_fixture("futures_ls_global_BTCUSDT.json")
    records_global = parse_long_short_ratio(raw_global, ratio_type="global_account")
    assert len(records_global) == len(raw_global)
    assert records_global[0].long_share > 0
    assert records_global[0].short_share > 0

    raw_top = load_fixture("futures_ls_top_position_BTCUSDT.json")
    records_top = parse_long_short_ratio(raw_top, ratio_type="top_position")
    assert len(records_top) == len(raw_top)
    assert records_top[0].ratio_type == "top_position"


def test_parse_premium_index():
    raw = load_fixture("futures_premium_BTCUSDT.json")
    snapshot = parse_premium_index(raw)
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.mark_price > 0
    assert snapshot.index_price > 0
    assert snapshot.funding_rate is not None


def test_parse_fear_greed():
    raw = load_fixture("fear_greed_full.json")
    records = parse_fear_greed(raw)
    assert len(records) > 0
    r0 = records[0]
    assert 0 <= r0.value <= 100
    assert isinstance(r0.value, int)  # DEV-007


def test_parse_coingecko():
    raw = load_fixture("coingecko_global.json")
    dom = parse_coingecko_global(raw)
    assert dom is not None
    assert 40.0 <= dom.dominance_pct <= 80.0


def test_parse_messari_news_synthetic():
    sample = {
        "data": [
            {
                "id": "news_123",
                "title": "Bitcoin surges past new highs on strong spot ETF inflows",
                "published_at": "2026-03-15T12:00:00Z",
                "tags": ["btc"],
            }
        ]
    }
    items = parse_messari_news(sample, coin_ticker="BTC")
    assert len(items) == 1
    assert items[0].currency == "BTC"
    assert items[0].vader_compound is not None
    assert items[0].vader_compound > 0.3  # Positive headline should score positive

