"""
test_stage16_llm.py - Unit and integration tests for Stage 16 (LLM Explanation Layer).

Verifies:
1. LLM explanation generation with mock mode (valid JSON output).
2. Resilient fallback when provider returns invalid JSON.
3. Resilient fallback on provider timeout.
4. Explaining does NOT modify the Signal or TradePlan (decision invariance).
5. Explain function never raises an unhandled exception.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models_trading import Signal, SignalExplanation, TradePlan
from app.llm.explain import explain_signal, _call_provider, _clean_json_response, LLM_TIMEOUT_SECONDS


@pytest.fixture(scope="function")
def db_session():
    """Provides a transactional database session for each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_dummy_signal(session, symbol="BTCUSDT", direction="LONG") -> Signal:
    """Helper to insert a test signal."""
    ts = datetime.now(timezone.utc)
    sig = Signal(
        symbol=symbol,
        interval="4h",
        ts=ts,
        direction=direction,
        composite_score=0.48,
        regime_factor=0.9,
        corr_factor=1.0,
        confidence=0.43,
        entry_price=68000.0,
        stop_loss=66500.0,
        take_profit=71000.0,
        sl_distance_atr=1.5,
        rr=2.0,
        size_multiplier=0.72,
        contributions={
            "f01_momentum": {"weight": 12, "score": 0.6, "contribution": 0.072},
            "f02_ema_trend": {"weight": 12, "score": 0.8, "contribution": 0.096},
            "f03_rsi": {"weight": 10, "score": -0.2, "contribution": -0.02},
        },
        features_snapshot={"close": 68000.0, "atr14": 1000.0},
        config_version="test_v1",
    )
    session.add(sig)
    session.commit()
    session.refresh(sig)
    return sig


def test_clean_json_response_valid():
    """Test JSON response parsing and validation."""
    valid_str = '''{
        "summary": "BTC shows bullish momentum.",
        "supporting_factors": ["EMA uptrend", "MACD cross"],
        "conflicting_factors": ["Funding slightly elevated"],
        "main_risks": ["Resistance at 70k"]
    }'''
    res = _clean_json_response(valid_str)
    assert res["summary"] == "BTC shows bullish momentum."
    assert len(res["supporting_factors"]) == 2
    assert len(res["conflicting_factors"]) == 1
    assert len(res["main_risks"]) == 1


def test_clean_json_response_markdown_fence():
    """Test extracting JSON from markdown code fence."""
    fenced = '```json\n{"summary": "Test", "supporting_factors": [], "conflicting_factors": [], "main_risks": []}\n```'
    res = _clean_json_response(fenced)
    assert res["summary"] == "Test"


def test_clean_json_response_missing_key():
    """Missing key should raise ValueError."""
    bad = '{"summary": "Test", "supporting_factors": []}'
    with pytest.raises(ValueError):
        _clean_json_response(bad)


def test_explain_signal_mock(db_session, monkeypatch):
    """Test explain_signal using LLM_MOCK=1."""
    monkeypatch.setenv("LLM_MOCK", "1")
    sig = _make_dummy_signal(db_session, symbol="ETHUSDT", direction="LONG")

    expl = explain_signal(sig.id, session=db_session)

    assert expl is not None
    assert expl.signal_id == sig.id
    assert expl.error is None
    assert isinstance(expl.text, dict)
    assert "summary" in expl.text
    assert len(expl.text["supporting_factors"]) > 0

    # Query DB directly to verify persistence
    db_expl = db_session.scalars(
        select(SignalExplanation).where(SignalExplanation.signal_id == sig.id)
    ).first()
    assert db_expl is not None
    assert db_expl.text["summary"] == expl.text["summary"]


def test_explain_signal_handles_invalid_json(db_session, monkeypatch):
    """When provider returns unparseable text, fallback template must be used and error logged."""
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "dummy_key")

    with mock.patch("app.llm.explain._call_provider", return_value="Not a JSON response from model"):
        sig = _make_dummy_signal(db_session, symbol="SOLUSDT", direction="SHORT")
        expl = explain_signal(sig.id, session=db_session)

        assert expl is not None
        assert expl.error is not None
        assert "JSON" in expl.error or "ValueError" in expl.error
        # Valid JSON structure still returned via fallback!
        assert "summary" in expl.text
        assert "supporting_factors" in expl.text
        assert "main_risks" in expl.text


def test_explain_signal_handles_timeout(db_session, monkeypatch):
    """When provider times out, fallback template is stored and caller does not crash."""
    monkeypatch.setenv("LLM_MOCK", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "dummy_key")

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("Provider timed out after 10s")

    with mock.patch("app.llm.explain._call_provider", side_effect=raise_timeout):
        sig = _make_dummy_signal(db_session, symbol="BNBUSDT", direction="HOLD")
        expl = explain_signal(sig.id, session=db_session)

        assert expl is not None
        assert expl.error is not None
        assert "Timeout" in expl.error
        assert "summary" in expl.text
        assert "Hold recommendation" in expl.text["summary"]


def test_decision_invariance_with_explanation(db_session, monkeypatch):
    """
    Core safety rule: Stored signal direction, score, stop-loss, and trade plan
    MUST be 100% identical before and after generating an explanation.
    """
    monkeypatch.setenv("LLM_MOCK", "1")
    sig = _make_dummy_signal(db_session, symbol="BTCUSDT", direction="LONG")

    # Create dummy trade plan
    plan = TradePlan(
        signal_id=sig.id,
        symbol=sig.symbol,
        side="LONG",
        qty=0.05,
        entry_price=sig.entry_price,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        leverage=2.0,
        risk_amount=75.0,
        status="proposed",
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)

    # Record state before explanation
    pre_dir = sig.direction
    pre_score = sig.composite_score
    pre_sl = sig.stop_loss
    pre_tp = sig.take_profit
    pre_qty = plan.qty
    pre_status = plan.status

    # Run explanation
    explain_signal(sig.id, session=db_session)

    # Refresh from DB
    db_session.refresh(sig)
    db_session.refresh(plan)

    assert sig.direction == pre_dir
    assert sig.composite_score == pre_score
    assert sig.stop_loss == pre_sl
    assert sig.take_profit == pre_tp
    assert plan.qty == pre_qty
    assert plan.status == pre_status
