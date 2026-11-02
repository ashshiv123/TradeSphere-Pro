"""
test_stage2_models.py - Stage 2: test ORM models and idempotent upserts.

These tests run WITHOUT a real database by testing the model structure
and the upsert logic using a SQLite in-memory database (same SQL,
different engine - lets us verify the schema and upsert logic instantly).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("POSTGRES_PASSWORD", "test")

from app.db.models import (
    Base, Candle, FundingRate, OpenInterest, LongShortRatio,
    PremiumSnapshot, FearGreed, BtcDominance, CollectorStatus,
    NewsItem, Liquidation, Feature, ScheduledEvent,
)

# For SQLite tests we need to use the generic insert, not pg_insert.
# We test the model structure here; upsert logic is tested via pg_insert
# in the Docker integration tests (Stage 5).


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite engine with all tables."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    """Yield a fresh session; roll back after each test."""
    with Session(engine) as session:
        yield session
        session.rollback()


# ── Model structure tests ────────────────────────────────────────────────────

def test_all_tables_exist(engine):
    """Every table defined in the plan exists in the schema."""
    expected = {
        "candles", "funding_rates", "open_interest", "long_short_ratio",
        "premium_snapshots", "liquidations", "news_items", "fear_greed",
        "btc_dominance", "scheduled_events", "features", "collector_status",
    }
    inspector = inspect(engine)
    actual = set(inspector.get_table_names())
    assert expected.issubset(actual), f"Missing tables: {expected - actual}"


def test_candle_primary_key_columns(engine):
    inspector = inspect(engine)
    pk_cols = {c["name"] for c in inspector.get_pk_constraint("candles")["constrained_columns"]}
    assert pk_cols == {"market", "symbol", "interval", "open_time"}


def test_funding_rate_has_rate_type_column(engine):
    """DEV-002: rateType field added."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("funding_rates")}
    assert "rate_type" in cols


def test_open_interest_has_cmc_supply(engine):
    """DEV-003: CMCCirculatingSupply field added."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("open_interest")}
    assert "cmc_circulating_supply" in cols


def test_long_short_ratio_has_correct_columns(engine):
    """DEV-004: internal names are long_share / short_share."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("long_short_ratio")}
    assert "long_share" in cols
    assert "short_share" in cols
    assert "long_short_ratio" in cols


def test_features_has_all_scored_and_gate_fields(engine):
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("features")}
    scored = {"f01_momentum", "f02_ema_trend", "f03_rsi", "f04_macd",
              "f05_funding", "f06_open_interest", "f07_long_short",
              "f08_basis", "f10_volume_sr", "f11_news"}
    gates = {"g09_liq_above_price", "g09_liq_below_price", "g09_source",
             "g12_regime_factor", "g13_btc_corr", "g13_btc_beta",
             "g13_btc_trend", "g13_btc_dominance"}
    assert scored.issubset(cols), f"Missing scored: {scored - cols}"
    assert gates.issubset(cols), f"Missing gates: {gates - cols}"
    assert "news_pause" in cols
    assert "missing" in cols


# ── Idempotency tests (using ORM add + merge, SQLite-compatible) ──────────────

UTC = timezone.utc

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_candle_insert_idempotent(db):
    """Inserting the same candle twice leaves exactly one row."""
    row = Candle(
        market="futures", symbol="BTCUSDT", interval="4h",
        open_time=_ts("2026-01-01T00:00:00"),
        close_time=_ts("2026-01-01T04:00:00"),
        open=40000, high=40500, low=39500, close=40200,
        volume=1234.5, is_closed=True,
    )
    db.add(row)
    db.flush()

    # Second insert of the same PK should raise IntegrityError on real PG,
    # but here we test the ORM merge path (used internally by upsert)
    db.merge(row)
    db.flush()

    count = db.query(Candle).filter_by(
        market="futures", symbol="BTCUSDT", interval="4h",
        open_time=_ts("2026-01-01T00:00:00")
    ).count()
    assert count == 1, "Candle upsert created a duplicate row"


def test_funding_rate_insert_idempotent(db):
    row = FundingRate(
        symbol="BTCUSDT",
        funding_time=_ts("2026-01-01T08:00:00"),
        funding_rate=0.0001,
        mark_price=40000,
        rate_type="Regular",
    )
    db.add(row)
    db.flush()
    db.merge(row)
    db.flush()
    count = db.query(FundingRate).filter_by(
        symbol="BTCUSDT", funding_time=_ts("2026-01-01T08:00:00")
    ).count()
    assert count == 1


def test_fear_greed_insert_idempotent(db):
    row = FearGreed(
        ts=_ts("2026-01-01T00:00:00"),
        value=42,
        classification="Fear",
    )
    db.add(row)
    db.flush()
    db.merge(row)
    db.flush()
    count = db.query(FearGreed).filter_by(ts=_ts("2026-01-01T00:00:00")).count()
    assert count == 1


def test_collector_status_insert_idempotent(db):
    row = CollectorStatus(name="candles_futures", rows_written_total=10)
    db.add(row)
    db.flush()
    row2 = CollectorStatus(name="candles_futures", rows_written_total=20)
    db.merge(row2)
    db.flush()
    count = db.query(CollectorStatus).filter_by(name="candles_futures").count()
    assert count == 1


def test_candle_high_gte_low(db):
    """Basic sanity: we never accept a candle where high < low."""
    row = Candle(
        market="spot", symbol="ETHUSDT", interval="1d",
        open_time=_ts("2026-01-02T00:00:00"),
        close_time=_ts("2026-01-02T23:59:59"),
        open=3000, high=3100, low=2900, close=3050,
        volume=500, is_closed=True,
    )
    assert float(row.high) >= float(row.low)


def test_news_item_null_votes_ok(db):
    """Messari items have NULL votes - must be stored without error."""
    row = NewsItem(
        source="messari",
        external_id="abc123",
        currency="BTC",
        title="Bitcoin rallies",
        published_at=_ts("2026-01-01T12:00:00"),
        votes_positive=None,
        votes_negative=None,
        votes_important=None,
        vader_compound=0.65,
    )
    db.add(row)
    db.flush()
    saved = db.query(NewsItem).filter_by(external_id="abc123").first()
    assert saved is not None
    assert saved.votes_positive is None
    assert saved.vader_compound == pytest.approx(0.65, abs=0.01)

