"""
models_trading.py — Database models for TradeSphere Pro Decision & Execution Layer.

DECISION_LAYER_PLAN.md §2:
- signals
- signal_explanations
- trade_plans
- risk_events
- kill_switch_state
- orders
- positions
- equity_snapshots
- backtest_runs
- backtest_trades
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, REAL

from app.db.models import Base

BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")
TZ = DateTime(timezone=True)


class Signal(Base):
    """
    Scored trade signal generated at 4h candle close.
    One row per symbol per interval per candle close time (including HOLD).
    """
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    interval: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(TZ, nullable=False)  # candle close time

    direction: Mapped[str] = mapped_column(Text, nullable=False)  # 'LONG' | 'SHORT' | 'HOLD'
    hold_reason: Mapped[Optional[str]] = mapped_column(Text)      # below_threshold, low_confidence, etc.

    composite_score: Mapped[Optional[float]] = mapped_column(REAL)
    regime_factor: Mapped[Optional[float]] = mapped_column(REAL)
    corr_factor: Mapped[Optional[float]] = mapped_column(REAL)
    confidence: Mapped[Optional[float]] = mapped_column(REAL)

    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))

    sl_distance_atr: Mapped[Optional[float]] = mapped_column(REAL)
    rr: Mapped[Optional[float]] = mapped_column(REAL)
    size_multiplier: Mapped[Optional[float]] = mapped_column(REAL)

    contributions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)
    features_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)
    config_version: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("symbol", "interval", "ts", name="uq_signals_symbol_interval_ts"),
        Index("ix_signals_ts", "ts"),
    )


class SignalExplanation(Base):
    """LLM explanation for a signal (provider-agnostic, text only)."""
    __tablename__ = "signal_explanations"

    signal_id: Mapped[int] = mapped_column(BIGINT_ID, ForeignKey("signals.id"), primary_key=True)
    provider: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(Text)
    text: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)


class TradePlan(Base):
    """Risk-approved trade proposal built from a LONG or SHORT signal."""
    __tablename__ = "trade_plans"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(BIGINT_ID, ForeignKey("signals.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)  # 'LONG' | 'SHORT'

    qty: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    stop_loss: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    take_profit: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)

    leverage: Mapped[float] = mapped_column(REAL, nullable=False)
    risk_amount: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False)  # proposed | approved | rejected | filled | closed...
    approved_by: Mapped[Optional[str]] = mapped_column(Text)   # 'manual' | 'auto'

    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)


class RiskEvent(Base):
    """Audit log of risk layer decisions, vetos, resizes, and kill-switch activations."""
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)
    symbol: Mapped[Optional[str]] = mapped_column(Text)
    signal_id: Mapped[Optional[int]] = mapped_column(BIGINT_ID)
    plan_id: Mapped[Optional[int]] = mapped_column(BIGINT_ID)

    rule: Mapped[str] = mapped_column(Text, nullable=False)    # max_positions, daily_drawdown, etc.
    action: Mapped[str] = mapped_column(Text, nullable=False)  # veto | resize | kill_switch | info
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)


class KillSwitchState(Base):
    """Global emergency stop state (single row id=1)."""
    __tablename__ = "kill_switch_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    reset_at: Mapped[Optional[datetime]] = mapped_column(TZ)


class Order(Base):
    """Order placed on exchange or simulated."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BIGINT_ID, ForeignKey("trade_plans.id"), nullable=False)
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(Text)

    type: Mapped[str] = mapped_column(Text, nullable=False)  # entry | stop | take_profit | exit
    side: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))

    status: Mapped[str] = mapped_column(Text, nullable=False)
    filled_qty: Mapped[float] = mapped_column(Numeric(30, 8), default=0.0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    fee: Mapped[float] = mapped_column(Numeric(24, 8), default=0.0)
    raw: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)

    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)


class Position(Base):
    """Open or closed position."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BIGINT_ID, ForeignKey("trade_plans.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))

    opened_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(TZ)

    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    pnl: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    fees: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    funding: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    exit_reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # open | closed


class EquitySnapshot(Base):
    """Periodic portfolio equity marks for drawdown tracking and performance analysis."""
    __tablename__ = "equity_snapshots"

    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    equity: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    unrealised_pnl: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(Text, default="exchange")  # exchange | backtest


class BacktestRun(Base):
    """Recorded backtest execution parameters and aggregated summary metrics."""
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)  # full | reduced
    params: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    symbols: Mapped[List[str]] = mapped_column(JSON_TYPE, nullable=False)
    start_ts: Mapped[datetime] = mapped_column(TZ, nullable=False)
    end_ts: Mapped[datetime] = mapped_column(TZ, nullable=False)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE)
    report_path: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, default=datetime.utcnow)


class BacktestTrade(Base):
    """Individual trade executed during a backtest simulation."""
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT_ID, ForeignKey("backtest_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)

    entry_ts: Mapped[datetime] = mapped_column(TZ, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    exit_ts: Mapped[Optional[datetime]] = mapped_column(TZ)
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))

    exit_reason: Mapped[Optional[str]] = mapped_column(Text)
    qty: Mapped[float] = mapped_column(Numeric(30, 8), nullable=False)
    pnl: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    fees: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    funding: Mapped[Optional[float]] = mapped_column(Numeric(24, 8))
    r_multiple: Mapped[Optional[float]] = mapped_column(REAL)
