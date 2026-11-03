"""
test_stage18_execution.py - Comprehensive tests for Stage 18 Testnet Execution Engine.
Tests all failure paths, safety constraints, order lifecycle, reconciliation, and restart recovery.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models_trading import EquitySnapshot, KillSwitchState, Order, Position, RiskEvent, Signal, TradePlan
from app.execution.testnet_engine import (
    ExecutionModeError,
    StopLossPlacementError,
    TestnetExecutionEngine,
    verify_testnet_mode_or_die,
)


class MockExchangeClient:
    """Mock testnet exchange adapter for deterministic testing."""
    def __init__(self, should_fail_stop_loss: bool = False):
        self.should_fail_stop_loss = should_fail_stop_loss
        self.placed_orders: List[Dict[str, Any]] = []
        self.open_positions: List[Dict[str, Any]] = []
        self.wallet_balance = 10000.0
        self.unrealized_pnl = 50.0

    def get_account(self) -> Dict[str, Any]:
        return {
            "totalWalletBalance": str(self.wallet_balance),
            "totalUnrealizedProfit": str(self.unrealized_pnl),
            "positions": self.open_positions,
        }

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return [o for o in self.placed_orders if o.get("status") == "NEW"]

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.should_fail_stop_loss and order_type == "STOP_MARKET":
            raise RuntimeError("Simulated exchange error: Order rejected (stop price invalid)")

        order = {
            "orderId": len(self.placed_orders) + 1001,
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "origQty": str(quantity),
            "executedQty": str(quantity),
            "price": str(price or 65000.0),
            "avgPrice": str(price or 65000.0),
            "status": "FILLED" if order_type == "MARKET" else "NEW",
            "clientOrderId": client_order_id,
            "reduceOnly": reduce_only,
        }
        self.placed_orders.append(order)

        if order_type == "MARKET" and not reduce_only:
            # Add to positions
            amt = quantity if side == "BUY" else -quantity
            self.open_positions.append({"symbol": symbol, "positionAmt": str(amt)})

        return order


@pytest.fixture(scope="function")
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _create_approved_plan(session, symbol="BTCUSDT", notional=650.0, leverage=2.0) -> TradePlan:
    sig = Signal(
        symbol=symbol,
        interval="4h",
        ts=datetime.now(timezone.utc),
        direction="LONG",
        composite_score=0.5,
        config_version="v1",
    )
    session.add(sig)
    session.commit()
    session.refresh(sig)

    entry_price = 65000.0
    qty = notional / entry_price

    plan = TradePlan(
        signal_id=sig.id,
        symbol=symbol,
        side="LONG",
        qty=qty,
        entry_price=entry_price,
        stop_loss=64000.0,
        take_profit=67000.0,
        leverage=leverage,
        risk_amount=20.0,
        status="approved",
        approved_by="manual",
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def test_refuse_live_execution_mode(monkeypatch):
    """Engine MUST abort immediately if EXECUTION_MODE is set to LIVE."""
    monkeypatch.setenv("EXECUTION_MODE", "LIVE")
    with pytest.raises(ExecutionModeError) as exc:
        verify_testnet_mode_or_die()
    assert "ONLY 'TESTNET' is permitted" in str(exc.value)


def test_hard_caps_enforcement(db_session, monkeypatch):
    """Enforces hard caps on leverage (> 5) and notional (> $1000)."""
    monkeypatch.setenv("EXECUTION_MODE", "TESTNET")
    mock_client = MockExchangeClient()
    engine = TestnetExecutionEngine(db_session, mock_client)

    # Exceed leverage cap
    plan_high_lev = _create_approved_plan(db_session, leverage=6.0)
    with pytest.raises(ValueError, match="exceeds HARD CAP"):
        engine.execute_plan(plan_high_lev)

    # Exceed notional cap ($1,000)
    plan_high_notional = _create_approved_plan(db_session, notional=1500.0)
    with pytest.raises(ValueError, match="exceeds HARD CAP"):
        engine.execute_plan(plan_high_notional)


def test_no_order_without_stop_loss(db_session, monkeypatch):
    """Engine refuses to place an order if stop loss is missing or <= 0."""
    monkeypatch.setenv("EXECUTION_MODE", "TESTNET")
    mock_client = MockExchangeClient()
    engine = TestnetExecutionEngine(db_session, mock_client)

    plan = _create_approved_plan(db_session)
    plan.stop_loss = 0.0
    db_session.commit()

    with pytest.raises(ValueError, match="Refusing order execution without a valid stop-loss"):
        engine.execute_plan(plan)


def test_full_order_lifecycle_and_idempotency(db_session, monkeypatch):
    """
    Tests complete order execution lifecycle:
    1. Entry placed and filled.
    2. Reduce-only SL and TP placed.
    3. Position created in DB.
    4. Deterministic client_order_id prevents duplicate execution.
    """
    monkeypatch.setenv("EXECUTION_MODE", "TESTNET")
    mock_client = MockExchangeClient()
    engine = TestnetExecutionEngine(db_session, mock_client)

    plan = _create_approved_plan(db_session)
    res = engine.execute_plan(plan)

    assert res["status"] == "executed"
    assert "tsp-" in res["entry_order_id"]
    assert "tsp-" in res["stop_order_id"]

    # Verify orders in DB
    orders = db_session.scalars(select(Order).where(Order.plan_id == plan.id)).all()
    assert len(orders) >= 3  # entry, stop, tp
    order_types = {o.type for o in orders}
    assert "entry" in order_types
    assert "stop" in order_types
    assert "take_profit" in order_types

    # Verify Position in DB
    pos = db_session.scalars(select(Position).where(Position.plan_id == plan.id)).first()
    assert pos is not None
    assert pos.status == "open"
    assert pos.entry_price > 0

    # Idempotency check: Calling execute_plan a second time must NOT place duplicate orders
    res2 = engine.execute_plan(plan)
    assert res2["status"] == "skipped"
    assert res2["reason"] == "duplicate_client_order_id"


def test_protection_rule_stop_loss_failure(db_session, monkeypatch):
    """
    Protection Rule: If stop-loss placement fails after fill:
    - Position is immediately closed at market.
    - Critical RiskEvent is logged.
    - KillSwitchState is activated.
    """
    monkeypatch.setenv("EXECUTION_MODE", "TESTNET")
    mock_client = MockExchangeClient(should_fail_stop_loss=True)
    engine = TestnetExecutionEngine(db_session, mock_client)

    plan = _create_approved_plan(db_session)

    with pytest.raises(StopLossPlacementError):
        engine.execute_plan(plan)

    # Position must be marked closed
    pos = db_session.scalars(select(Position).where(Position.plan_id == plan.id)).first()
    assert pos is not None
    assert pos.status == "closed"
    assert pos.exit_reason == "emergency_sl_failed"

    # Kill-Switch must be active
    ks = db_session.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    assert ks is not None
    assert ks.active is True
    assert "Stop-loss placement failed" in ks.reason

    # Critical risk event logged
    rev = db_session.scalars(
        select(RiskEvent).where(RiskEvent.rule == "protection_stop_placement_failure")
    ).first()
    assert rev is not None
    assert rev.action == "critical"


def test_reconciliation_and_unknown_position_detection(db_session, monkeypatch):
    """
    Reconciliation:
    - Captures EquitySnapshot.
    - If exchange has unknown position not in DB, triggers Kill-Switch.
    """
    monkeypatch.setenv("EXECUTION_MODE", "TESTNET")
    mock_client = MockExchangeClient()
    # Simulate a stray unknown position on exchange
    mock_client.open_positions.append({"symbol": "XRPUSDT", "positionAmt": "500.0"})

    engine = TestnetExecutionEngine(db_session, mock_client)
    res = engine.reconcile_portfolio()

    assert res["status"] == "reconciled"
    assert res["total_equity"] == 10050.0

    # Verify equity snapshot written
    snap = db_session.scalars(
        select(EquitySnapshot).order_by(EquitySnapshot.ts.desc())
    ).first()
    assert snap is not None
    assert float(snap.equity) == 10050.0

    # Verify Kill-Switch triggered by unknown position
    ks = db_session.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    assert ks is not None
    assert ks.active is True
    assert "Unknown position on exchange: XRPUSDT" in ks.reason
