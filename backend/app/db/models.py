"""
models.py - SQLAlchemy ORM models for every table in DATA_PIPELINE_PLAN.md section 6.

Each model has a primary key that makes INSERTs safe to repeat (idempotent upserts).
All timestamps use DateTime(timezone=True) which works on both PostgreSQL (TIMESTAMPTZ)
and SQLite (for unit tests).
Numbers in raw tables use NUMERIC (no rounding surprises); features use REAL (float).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Index, Integer, JSON,
    Numeric, REAL, SmallInteger, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Alias: timezone-aware datetime. On Postgres this becomes TIMESTAMPTZ.
# On SQLite (used in unit tests) it stores tz info correctly too.
TZ = DateTime(timezone=True)
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")
BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """All ORM models inherit from this base.
    Alembic reads Base.metadata for autogenerate."""
    pass


# ---------------------------------------------------------------------------
# Candles (futures and spot, all intervals)
# ---------------------------------------------------------------------------
class Candle(Base):
    """
    One OHLCV bar. market='futures' or 'spot', interval='4h' or '1d'.
    Primary key covers all four dimensions so the same bar from two
    different backfill runs leaves only one row.
    Kline column mapping (DEV-006):
      [0]=open_time [1]=open [2]=high [3]=low [4]=close [5]=volume
      [6]=close_time [7]=quote_volume [8]=trades [9]=taker_buy_base
      [10]=taker_buy_quote [11]=ignore
    """
    __tablename__ = "candles"

    market: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    interval: Mapped[str] = mapped_column(Text, primary_key=True)
    open_time: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    close_time: Mapped[datetime] = mapped_column(TZ, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    quote_volume: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    trades: Mapped[Optional[int]] = mapped_column(Integer)
    taker_buy_base: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    taker_buy_quote: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Funding rates
# ---------------------------------------------------------------------------
class FundingRate(Base):
    """
    Binance perpetual funding rate, paid every 8 hours.
    High positive rate = longs are paying shorts = crowded long side.
    Extra field rate_type added per DEV-002.
    """
    __tablename__ = "funding_rates"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    funding_time: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    funding_rate: Mapped[float] = mapped_column(Numeric(18, 10), nullable=False)
    mark_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    rate_type: Mapped[Optional[str]] = mapped_column(Text)   # DEV-002


# ---------------------------------------------------------------------------
# Open interest history
# ---------------------------------------------------------------------------
class OpenInterest(Base):
    """
    Aggregate open interest for a futures market at a point in time.
    Only ~30 days of history available - must accumulate from day 1.
    Extra field cmc_circulating_supply added per DEV-003.
    """
    __tablename__ = "open_interest"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    sum_open_interest: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    sum_open_interest_value: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    cmc_circulating_supply: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))


# ---------------------------------------------------------------------------
# Long/short ratios (3 types per symbol)
# ---------------------------------------------------------------------------
class LongShortRatio(Base):
    """
    Share of accounts or positions that are long vs short.
    ratio_type: 'global_account' | 'top_account' | 'top_position'
    API returns longAccount/shortAccount -> mapped to long_share/short_share (DEV-004).
    """
    __tablename__ = "long_short_ratio"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    ratio_type: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    long_share: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    short_share: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    long_short_ratio: Mapped[Optional[float]] = mapped_column(Numeric(14, 6))


# ---------------------------------------------------------------------------
# Premium snapshots (mark price, written every minute from WebSocket)
# ---------------------------------------------------------------------------
class PremiumSnapshot(Base):
    """
    One row per minute per symbol, written from the markPrice WebSocket.
    API 'time' field (Unix ms) maps to ts (DEV-005).
    """
    __tablename__ = "premium_snapshots"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    mark_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    index_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    funding_rate: Mapped[Optional[float]] = mapped_column(Numeric(18, 10))
    next_funding_time: Mapped[Optional[datetime]] = mapped_column(TZ)


# ---------------------------------------------------------------------------
# Liquidations (from forceOrder WebSocket)
# ---------------------------------------------------------------------------
class Liquidation(Base):
    """
    Every forced liquidation event. No history - must collect from day 1.
    side='SELL' = a long was liquidated; side='BUY' = a short was liquidated.
    """
    __tablename__ = "liquidations"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(TZ, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    avg_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    quantity: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    notional: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "ts", "side", "price", "quantity",
                         name="uq_liquidations_event"),
        Index("ix_liquidations_symbol_ts", "symbol", "ts"),
    )


# ---------------------------------------------------------------------------
# News items
# ---------------------------------------------------------------------------
class NewsItem(Base):
    """
    One news headline from Messari (or future sources).
    votes_* columns NULL for Messari (DEV-001).
    vader_compound: VADER sentiment on title, range -1..+1.
    """
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    votes_positive: Mapped[Optional[int]] = mapped_column(Integer)
    votes_negative: Mapped[Optional[int]] = mapped_column(Integer)
    votes_important: Mapped[Optional[int]] = mapped_column(Integer)
    vader_compound: Mapped[Optional[float]] = mapped_column(REAL)
    raw: Mapped[Optional[dict]] = mapped_column(JSON_TYPE)

    __table_args__ = (
        UniqueConstraint("source", "external_id", "currency",
                         name="uq_news_items_source_id_currency"),
        Index("ix_news_items_currency_published", "currency", "published_at"),
    )


# ---------------------------------------------------------------------------
# Fear & Greed Index
# ---------------------------------------------------------------------------
class FearGreed(Base):
    """
    Daily Fear & Greed index (0=Extreme Fear, 100=Extreme Greed).
    API returns value and timestamp as strings - parser converts (DEV-007).
    """
    __tablename__ = "fear_greed"

    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------
# BTC dominance
# ---------------------------------------------------------------------------
class BtcDominance(Base):
    """
    BTC market cap as % of total crypto market cap, from CoinGecko.
    No historical API - must accumulate from day 1.
    """
    __tablename__ = "btc_dominance"

    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    dominance_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)


# ---------------------------------------------------------------------------
# Scheduled events (macro calendar)
# ---------------------------------------------------------------------------
class ScheduledEvent(Base):
    """
    Hand-kept macro events (FOMC, CPI, etc.) from data/scheduled_events.json.
    Used by F11 to set news_pause flag: window is 30 min before to 60 min after.
    """
    __tablename__ = "scheduled_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    event_time: Mapped[datetime] = mapped_column(TZ, nullable=False)
    impact: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "event_time", name="uq_scheduled_events"),
    )


# ---------------------------------------------------------------------------
# Features (the output table the scoring engine reads)
# ---------------------------------------------------------------------------
class Feature(Base):
    """
    One row per symbol per interval per 4h candle close time.
    Scored fields (f01..f10) are each in -1..+1.
    Gate fields (g09, g12, g13) are stored but not part of the weighted sum.
    missing: JSON list of field names that could not be computed.
    """
    __tablename__ = "features"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    interval: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)

    # Scored fields (-1..+1)
    f01_momentum: Mapped[Optional[float]] = mapped_column(REAL)
    f02_ema_trend: Mapped[Optional[float]] = mapped_column(REAL)
    f03_rsi: Mapped[Optional[float]] = mapped_column(REAL)
    f04_macd: Mapped[Optional[float]] = mapped_column(REAL)
    f05_funding: Mapped[Optional[float]] = mapped_column(REAL)
    f06_open_interest: Mapped[Optional[float]] = mapped_column(REAL)
    f07_long_short: Mapped[Optional[float]] = mapped_column(REAL)
    f08_basis: Mapped[Optional[float]] = mapped_column(REAL)
    f10_volume_sr: Mapped[Optional[float]] = mapped_column(REAL)
    f11_news: Mapped[Optional[float]] = mapped_column(REAL)

    # Gate fields (stored, used as filters/multipliers, not scored)
    g09_liq_above_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    g09_liq_above_notional: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    g09_liq_below_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    g09_liq_below_notional: Mapped[Optional[float]] = mapped_column(Numeric(30, 8))
    g09_source: Mapped[Optional[str]] = mapped_column(Text)

    g12_regime_factor: Mapped[Optional[float]] = mapped_column(REAL)
    g13_btc_corr: Mapped[Optional[float]] = mapped_column(REAL)
    g13_btc_beta: Mapped[Optional[float]] = mapped_column(REAL)
    g13_btc_trend: Mapped[Optional[int]] = mapped_column(SmallInteger)
    g13_btc_dominance: Mapped[Optional[float]] = mapped_column(REAL)

    volume_ratio: Mapped[Optional[float]] = mapped_column(REAL)
    atr: Mapped[Optional[float]] = mapped_column(REAL)
    close: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    news_pause: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[Optional[dict]] = mapped_column(JSON_TYPE)
    missing: Mapped[Optional[list]] = mapped_column(JSON_TYPE)
    computed_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


# ---------------------------------------------------------------------------
# Collector status
# ---------------------------------------------------------------------------
class CollectorStatus(Base):
    """
    One row per named collector. Updated on every success or failure.
    The /collectors/status API route reads this table.
    """
    __tablename__ = "collector_status"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    rows_written_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
