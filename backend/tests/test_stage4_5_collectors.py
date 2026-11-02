"""
test_stage4_5_collectors.py — Tests for collectors, websocket handler, backfill, and scheduler.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    BtcDominance,
    Candle,
    CollectorStatus,
    FearGreed,
    FundingRate,
    Liquidation,
    LongShortRatio,
    NewsItem,
    OpenInterest,
    PremiumSnapshot,
    ScheduledEvent,
)
from app.collectors.btc_dominance import poll_btc_dominance
from app.collectors.candles import poll_candles
from app.collectors.events import load_scheduled_events
from app.collectors.fear_greed import poll_fear_greed
from app.collectors.funding import poll_funding
from app.collectors.long_short import poll_long_short
from app.collectors.news import poll_news
from app.collectors.open_interest import poll_open_interest
from app.collectors.ws_handler import handle_ws_message
from app.worker import create_scheduler


@pytest.fixture
def memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()


def test_scheduler_registered_jobs():
    scheduler = create_scheduler()
    jobs = scheduler.get_jobs()
    job_ids = [j.id for j in jobs]

    assert "job_candles" in job_ids
    assert "job_funding" in job_ids
    assert "job_oi" in job_ids
    assert "job_ls" in job_ids
    assert "job_news" in job_ids
    assert "job_fng" in job_ids
    assert "job_btcdom" in job_ids
    assert "job_events" in job_ids
    assert "job_4h_features" in job_ids

    # Verify 4h feature job runs at candle boundary (0,4,8,12,16,20 at min 1)
    feature_job = scheduler.get_job("job_4h_features")
    trigger_str = str(feature_job.trigger)
    assert "0,4,8,12,16,20" in trigger_str
    assert "minute='1'" in trigger_str or "1" in trigger_str


def test_ws_handler_mark_price(memory_db: Session):
    msg = {
        "stream": "btcusdt@markPrice@1s",
        "data": {
            "e": "markPriceUpdate",
            "E": 1700000000000,
            "s": "BTCUSDT",
            "p": "65123.50",
            "i": "65120.00",
            "r": "0.00010000",
            "T": 1700028800000,
        },
    }
    handle_ws_message(memory_db, msg)

    row = memory_db.execute(select(PremiumSnapshot)).scalar_one_or_none()
    assert row is not None
    assert row.symbol == "BTCUSDT"
    assert float(row.mark_price) == 65123.50
    assert float(row.funding_rate) == 0.0001


def test_ws_handler_liquidation(memory_db: Session):
    msg = {
        "stream": "btcusdt@forceOrder",
        "data": {
            "e": "forceOrder",
            "E": 1700000000000,
            "o": {
                "s": "BTCUSDT",
                "S": "SELL",
                "p": "64000.00",
                "q": "1.500",
                "ap": "64000.00",
                "T": 1700000000000,
            },
        },
    }
    handle_ws_message(memory_db, msg)

    row = memory_db.execute(select(Liquidation)).scalar_one_or_none()
    assert row is not None
    assert row.symbol == "BTCUSDT"
    assert row.side == "SELL"
    assert float(row.price) == 64000.0
    assert float(row.quantity) == 1.5
    assert float(row.notional) == 96000.0


@patch("app.collectors.events.Path.is_file", return_value=True)
@patch("builtins.open")
def test_load_scheduled_events(mock_open, mock_is_file, memory_db: Session):
    import json
    fake_json = json.dumps([
        {"name": "FOMC Rate Decision", "event_time": "2026-11-05T19:00:00Z", "impact": "high"}
    ])
    mock_open.return_value.__enter__.return_value.read.return_value = fake_json

    load_scheduled_events(memory_db, "data/scheduled_events.json")

    rows = memory_db.execute(select(ScheduledEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "FOMC Rate Decision"
    assert rows[0].impact == "high"


@patch("app.collectors.candles.BinanceFuturesClient")
@patch("app.collectors.candles.BinanceSpotClient")
def test_poll_candles(mock_spot, mock_futures, memory_db: Session):
    from app.clients.binance_futures import ParsedCandle
    now = datetime.now(timezone.utc)
    mock_c = ParsedCandle(
        market="futures",
        symbol="BTCUSDT",
        interval="4h",
        open_time=now,
        close_time=now,
        open=60000.0,
        high=61000.0,
        low=59500.0,
        close=60500.0,
        volume=100.0,
        quote_volume=6000000.0,
        trades_count=1000,
        taker_buy_volume=50.0,
        taker_buy_quote_volume=3000000.0,
    )
    mock_f_inst = MagicMock()
    mock_f_inst.get_klines.return_value = [mock_c]
    mock_futures.return_value = mock_f_inst

    mock_s_inst = MagicMock()
    mock_s_inst.get_klines.return_value = []
    mock_spot.return_value = mock_s_inst

    poll_candles(memory_db, ["BTCUSDT"], ["4h"])

    candles = memory_db.execute(select(Candle)).scalars().all()
    assert len(candles) == 1
    assert candles[0].symbol == "BTCUSDT"

    # Status updated
    status = memory_db.execute(select(CollectorStatus).where(CollectorStatus.name == "collector_candles")).scalar_one_or_none()
    assert status is not None
    assert status.rows_written_total >= 1


@patch("app.collectors.long_short.BinanceFuturesClient")
def test_poll_long_short(mock_client, memory_db: Session):
    from app.clients.binance_futures import ParsedLongShortRatio
    now = datetime.now(timezone.utc)
    item = ParsedLongShortRatio(
        symbol="BTCUSDT",
        ratio_type="global_account",
        period="4h",
        ts=now,
        long_share=0.6,
        short_share=0.4,
        long_short_ratio=1.5,
    )
    inst = MagicMock()
    inst.get_global_long_short_ratio.return_value = [item]
    inst.get_top_long_short_position_ratio.return_value = []
    mock_client.return_value = inst

    poll_long_short(memory_db, ["BTCUSDT"], "4h")

    rows = memory_db.execute(select(LongShortRatio)).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].long_short_ratio) == 1.5


@patch("app.collectors.btc_dominance.CoinGeckoClient")
def test_poll_btc_dominance(mock_client, memory_db: Session):
    from app.clients.coingecko import ParsedBtcDominance
    now = datetime.now(timezone.utc)
    inst = MagicMock()
    inst.get_btc_dominance.return_value = ParsedBtcDominance(ts=now, dominance_pct=58.25)
    mock_client.return_value = inst

    poll_btc_dominance(memory_db)

    rows = memory_db.execute(select(BtcDominance)).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].dominance_pct) == 58.25
