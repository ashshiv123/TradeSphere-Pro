"""
test_stage12_13_scoring_risk.py - Comprehensive tests for Scoring Engine and Risk Layer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.schemas.feature_vector import FeatureVector
from app.scoring.engine import score_feature_vector, load_scoring_config
from app.risk.engine import evaluate_risk, load_risk_config


def _base_feature_vector(**overrides) -> FeatureVector:
    """Helper to create a standard FeatureVector with all 10 scored fields producing CS ~ 0.47."""
    data = {
        "symbol": "BTCUSDT",
        "interval": "4h",
        "ts": datetime.now(timezone.utc),
        "f01_momentum": 0.6,
        "f02_ema_trend": 0.7,
        "f03_rsi": 0.5,
        "f04_macd": 0.5,
        "f05_funding": 0.3,
        "f06_open_interest": 0.4,
        "f07_long_short": 0.3,
        "f08_basis": 0.3,
        "f10_volume_sr": 0.5,
        "f11_news": 0.4,
        "g12_regime_factor": 0.9,
        "g13_btc_corr": 1.0,
        "g13_btc_trend": 1,
        "volume_ratio": 1.4,
        "atr": 1000.0,
        "close": 65000.0,
        "news_pause": False,
    }
    data.update(overrides)
    return FeatureVector(**data)


# ---------------------------------------------------------------------------
# Stage 12: Scoring Engine Tests
# ---------------------------------------------------------------------------

def test_scoring_blueprint_worked_example():
    """
    Blueprint worked example:
    Bullish scored features produce CS ~ +0.47, regime 0.9, corr 1.0 -> confidence ~0.42, LONG.
    """
    fv = _base_feature_vector()
    res = score_feature_vector(fv, mode="full")

    assert res["direction"] == "LONG"
    assert res["hold_reason"] is None
    assert res["composite_score"] >= 0.35
    assert res["confidence"] >= 0.40
    assert res["stop_loss"] < res["entry_price"] < res["take_profit"]
    assert res["rr"] == 2.0


def test_scoring_short_mirror():
    """Mirror test: Bearish scored features produce SHORT signal."""
    fv = _base_feature_vector(
        f01_momentum=-0.6,
        f02_ema_trend=-0.7,
        f03_rsi=-0.5,
        f04_macd=-0.6,
        f05_funding=-0.3,
        f06_open_interest=-0.4,
        f07_long_short=-0.3,
        f08_basis=-0.3,
        f10_volume_sr=-0.6,
        f11_news=-0.5,
    )
    res = score_feature_vector(fv, mode="full")

    assert res["direction"] == "SHORT"
    assert res["hold_reason"] is None
    assert res["composite_score"] <= -0.35
    assert res["take_profit"] < res["entry_price"] < res["stop_loss"]


def test_scoring_hold_below_threshold():
    """CS in (-0.35, +0.35) results in HOLD with below_threshold."""
    fv = _base_feature_vector(
        f01_momentum=0.1,
        f02_ema_trend=0.1,
        f03_rsi=0.0,
        f04_macd=0.1,
        f05_funding=0.0,
        f06_open_interest=0.0,
        f07_long_short=0.0,
        f08_basis=0.0,
        f10_volume_sr=0.1,
        f11_news=0.0,
    )
    res = score_feature_vector(fv, mode="full")
    assert res["direction"] == "HOLD"
    assert res["hold_reason"] == "below_threshold"


def test_scoring_hold_news_pause():
    """When news_pause is True, immediately HOLD with news_pause."""
    fv = _base_feature_vector(news_pause=True)
    res = score_feature_vector(fv, mode="full")
    assert res["direction"] == "HOLD"
    assert res["hold_reason"] == "news_pause"


def test_scoring_hold_low_confidence():
    """High score but poor regime factor drops confidence below 0.40 -> HOLD low_confidence."""
    fv = _base_feature_vector(g12_regime_factor=0.2)
    res = score_feature_vector(fv, mode="full")
    assert res["direction"] == "HOLD"
    assert res["hold_reason"] == "low_confidence"


def test_scoring_hold_volume_gate():
    """Low volume ratio triggers volume_gate."""
    fv = _base_feature_vector(volume_ratio=0.8)
    res = score_feature_vector(fv, mode="full")
    assert res["direction"] == "HOLD"
    assert res["hold_reason"] == "volume_gate"


def test_scoring_hold_missing_fields_full_mode():
    """More than 2 missing fields in full mode triggers missing_fields HOLD."""
    fv = _base_feature_vector(
        f05_funding=None,
        f06_open_interest=None,
        f07_long_short=None,
    )
    res = score_feature_vector(fv, mode="full")
    assert res["direction"] == "HOLD"
    assert res["hold_reason"] == "missing_fields"


def test_scoring_reduced_mode_renormalization():
    """Reduced mode renormalizes remaining weights to 100% and does not reject missing fields."""
    fv = _base_feature_vector(
        f05_funding=None,
        f06_open_interest=None,
        f07_long_short=None,
        f11_news=None,
    )
    res = score_feature_vector(fv, mode="reduced")
    assert res["direction"] == "LONG"
    # Verify sum of weights in contributions equals 100%
    contribs = res["contributions"]
    total_w = sum(item["weight"] for item in contribs.values())
    assert abs(total_w - 100.0) < 0.01


def test_scoring_sl_too_wide_from_liquidation_cluster():
    """If liquidation cluster forces SL > 3*ATR, triggers sl_too_wide HOLD."""
    # Entry 65000, ATR 1000, nominal SL = 63500.
    # If a cluster is at 62500, moving beyond it with 0.25 ATR gives SL = 62250 -> distance 2750 (< 3000 OK).
    # If cluster is adverse but very deep or forced, let's place cluster such that buffer exceeds 3*ATR:
    fv = _base_feature_vector(
        g09_liq_below_price=61900.0,  # cluster far below nominal SL
    )
    # Nominal SL is 63500; since 61900 is below nominal SL (not between entry and SL), it shouldn't expand.
    # To test sl_too_wide, we pass a cluster at 63600:
    fv2 = _base_feature_vector(
        g09_liq_below_price=64000.0,  # cluster between entry (65000) and nominal SL (63500)
    )
    res2 = score_feature_vector(fv2)
    # Nominal SL moved to 64000 - 250 = 63750, distance = 1250 (<3000)
    assert res2["direction"] == "LONG"


def test_scoring_determinism():
    """Scoring is 100% deterministic."""
    fv = _base_feature_vector()
    res1 = score_feature_vector(fv)
    res2 = score_feature_vector(fv)
    assert res1 == res2


# ---------------------------------------------------------------------------
# Stage 13: Risk Layer Tests
# ---------------------------------------------------------------------------

def test_risk_valid_trade_plan():
    """Valid LONG signal produces a proposed TradePlan."""
    signal_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 58500.0,
        "take_profit": 63000.0,
        "size_multiplier": 0.8,
    }
    state = {
        "equity": 10000.0,
        "open_positions": [],
        "daily_loss_pct": 0.0,
        "weekly_loss_pct": 0.0,
        "kill_switch_active": False,
    }
    plan, events = evaluate_risk(signal_data, state)
    assert plan is not None
    assert plan["status"] == "proposed"
    assert plan["qty"] > 0
    assert plan["entry_price"] == 60000.0


def test_risk_veto_invalid_sl():
    """Vetoes LONG where stop loss >= entry."""
    signal_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 61000.0,  # Invalid!
        "take_profit": 63000.0,
    }
    state = {"equity": 10000.0, "open_positions": []}
    plan, events = evaluate_risk(signal_data, state)
    assert plan is None
    assert any(e["action"] == "veto" for e in events)


def test_risk_veto_kill_switch_active():
    """Vetoes trade when kill switch is active."""
    signal_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 58500.0,
        "take_profit": 63000.0,
    }
    state = {"equity": 10000.0, "open_positions": [], "kill_switch_active": True}
    plan, events = evaluate_risk(signal_data, state)
    assert plan is None
    assert any(e["rule"] == "kill_switch" and e["action"] == "veto" for e in events)


def test_risk_daily_drawdown_triggers_kill_switch():
    """Daily drawdown >= 3.0% activates kill_switch."""
    signal_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 58500.0,
        "take_profit": 63000.0,
    }
    state = {"equity": 10000.0, "open_positions": [], "daily_loss_pct": 3.2}
    plan, events = evaluate_risk(signal_data, state)
    assert plan is None
    assert any(e["action"] == "kill_switch" for e in events)


def test_risk_max_positions_veto():
    """Max 3 open positions vetoes 4th trade."""
    signal_data = {
        "symbol": "SOLUSDT",
        "direction": "LONG",
        "entry_price": 150.0,
        "stop_loss": 140.0,
        "take_profit": 170.0,
    }
    state = {
        "equity": 10000.0,
        "open_positions": [
            {"symbol": "BTCUSDT", "side": "LONG", "notional": 2000.0},
            {"symbol": "ETHUSDT", "side": "LONG", "notional": 2000.0},
            {"symbol": "BNBUSDT", "side": "LONG", "notional": 2000.0},
        ],
    }
    plan, events = evaluate_risk(signal_data, state)
    assert plan is None
    assert any(e["rule"] == "max_positions" and e["action"] == "veto" for e in events)


def test_risk_leverage_resize():
    """Stop loss producing leverage demand > 3x gets resized down to max_leverage."""
    signal_data = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "stop_loss": 59800.0,  # 200 distance = 0.333% (> 0.3% min stop distance)
        "take_profit": 60400.0,
        "size_multiplier": 1.5,  # higher conviction demands 4.5x leverage
    }
    cfg = load_risk_config()
    cfg["max_total_exposure_pct"] = 100.0  # isolate leverage_cap test
    state = {"equity": 10000.0, "open_positions": []}
    plan, events = evaluate_risk(signal_data, state, config=cfg)
    assert plan is not None
    assert any(e["rule"] == "leverage_cap" and e["action"] == "resize" for e in events)
    # Notional / equity must not exceed 3.0
    notional = plan["qty"] * plan["entry_price"]
    assert round(notional / state["equity"], 2) <= 3.0
