"""
test_stage17_api.py - Integration tests for Stage 17 Trading & Decision API routes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.db.models_trading import KillSwitchState, Signal, TradePlan

client = TestClient(app)


def test_get_market_overview():
    resp = client.get("/market_overview")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    symbols = [item["symbol"] for item in data]
    assert "BTCUSDT" in symbols


def test_get_signals():
    resp = client.get("/signals?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert "symbol" in data[0]
        assert "direction" in data[0]


def test_get_signal_detail():
    with SessionLocal() as db:
        sig = db.query(Signal).first()
        if not sig:
            pytest.skip("No signal available for detail test")
        sig_id = sig.id

    resp = client.get(f"/signals/{sig_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "signal" in data
    assert "explanation" in data


def test_plan_lifecycle_approve_reject():
    # Ensure kill switch is inactive before testing approvals
    client.post("/killswitch/reset")

    # Insert a dummy plan to test approval
    with SessionLocal() as db:
        sig = db.query(Signal).first()
        sig_id = sig.id
        plan = TradePlan(
            signal_id=sig_id,
            symbol="BTCUSDT",
            side="LONG",
            qty=0.01,
            entry_price=65000.0,
            stop_loss=63500.0,
            take_profit=68000.0,
            leverage=2.0,
            risk_amount=50.0,
            status="proposed",
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        plan_id = plan.id

    # Test approve
    resp = client.post(f"/plans/{plan_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Test reject on another plan
    with SessionLocal() as db:
        plan2 = TradePlan(
            signal_id=sig_id,
            symbol="ETHUSDT",
            side="SHORT",
            qty=0.1,
            entry_price=3500.0,
            stop_loss=3600.0,
            take_profit=3300.0,
            leverage=2.0,
            risk_amount=40.0,
            status="proposed",
        )
        db.add(plan2)
        db.commit()
        db.refresh(plan2)
        plan2_id = plan2.id

    resp2 = client.post(f"/plans/{plan2_id}/reject")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "rejected"


def test_risk_status_and_kill_switch_lifecycle():
    # Check initial risk status
    resp = client.get("/risk/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "kill_switch" in data
    assert "portfolio" in data
    assert "rules" in data

    # Trigger kill switch
    t_resp = client.post("/killswitch/trigger?reason=Unit+test+trigger")
    assert t_resp.status_code == 200
    assert t_resp.json()["status"] == "kill_switch_active"

    # Verify risk status reports active kill switch
    resp_active = client.get("/risk/status")
    assert resp_active.json()["kill_switch"]["active"] is True

    # Reset kill switch
    r_resp = client.post("/killswitch/reset")
    assert r_resp.status_code == 200
    assert r_resp.json()["status"] == "kill_switch_reset"

    # Verify reset
    resp_reset = client.get("/risk/status")
    assert resp_reset.json()["kill_switch"]["active"] is False


def test_backtests_and_equity_endpoints():
    b_resp = client.get("/backtests")
    assert b_resp.status_code == 200
    assert isinstance(b_resp.json(), list)

    e_resp = client.get("/equity")
    assert e_resp.status_code == 200
    assert isinstance(e_resp.json(), list)
