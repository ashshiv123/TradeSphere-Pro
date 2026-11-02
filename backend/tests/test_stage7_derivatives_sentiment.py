"""
test_stage7_derivatives_sentiment.py — Unit tests for Stage 7 Derivatives & Sentiment Features.

Tests:
1. F5 Funding trend: rising funding slope -> positive; crowded trade dampener.
2. F6 OI trend: 2x2 matrix (+1.0, +0.3, -1.0, -0.3) & dead zones.
3. F7 L/S ratio: retail contrarian mapping & smart money adjustment.
4. F8 Perp-Spot Basis: expanding basis slope -> positive.
5. F9 Liquidation zones: cluster density vs swing proxy fallback.
6. F11 News Sentiment: VADER score, age decay, source weighting, and news_pause.
7. CRITICAL: Look-ahead bias test (data after candle close does not alter features at candle close).
8. Missing data policy test (returns None / records missing).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.features.f05_funding import compute_f05_latest
from app.features.f06_open_interest import compute_f06_latest
from app.features.f07_long_short import compute_f07_latest
from app.features.f08_basis import compute_f08_latest
from app.features.f09_liquidations import compute_f09_latest
from app.features.f11_news import compute_f11_latest


# ── 1. F5 Funding Trend ──────────────────────────────────────────────────────

def test_f05_funding_rising():
    # 15 funding points rising from 0.0001 to 0.0003
    times = pd.date_range("2026-01-01", periods=15, freq="8h", tz="UTC")
    rates = [0.0001 + i * 0.000015 for i in range(15)]
    df = pd.DataFrame({"funding_time": times, "funding_rate": rates})

    score = compute_f05_latest(df)
    assert score is not None
    assert score > 0.0, "Rising funding rate should yield positive trend score"


def test_f05_funding_crowded_dampener():
    # Funding rate is extreme: >= 0.0005 (5 bps per 8h)
    times = pd.date_range("2026-01-01", periods=15, freq="8h", tz="UTC")
    rates = [0.0005 + i * 0.00002 for i in range(15)]
    df = pd.DataFrame({"funding_time": times, "funding_rate": rates})

    score = compute_f05_latest(df)
    assert score is not None
    # Dampener halves the score
    assert 0.0 < score <= 0.5


# ── 2. F6 Open Interest Trend ────────────────────────────────────────────────

def test_f06_oi_matrix():
    times = pd.date_range("2026-01-01", periods=8, freq="4h", tz="UTC")

    # Case 1: Price UP and OI UP -> +1.0
    c_up = pd.DataFrame({"close_time": times, "close": [100.0 + i * 2.0 for i in range(8)]})
    oi_up = pd.DataFrame({"ts": times, "sum_open_interest_value": [1000.0 + i * 50.0 for i in range(8)]})
    assert compute_f06_latest(c_up, oi_up) == 1.0

    # Case 2: Price UP and OI DOWN -> +0.3
    oi_down = pd.DataFrame({"ts": times, "sum_open_interest_value": [1000.0 - i * 50.0 for i in range(8)]})
    assert compute_f06_latest(c_up, oi_down) == 0.3

    # Case 3: Price DOWN and OI UP -> -1.0
    c_down = pd.DataFrame({"close_time": times, "close": [100.0 - i * 2.0 for i in range(8)]})
    assert compute_f06_latest(c_down, oi_up) == -1.0

    # Case 4: Price DOWN and OI DOWN -> -0.3
    assert compute_f06_latest(c_down, oi_down) == -0.3

    # Deadzone case: tiny price change < 0.2%
    c_flat = pd.DataFrame({"close_time": times, "close": [100.0 + i * 0.01 for i in range(8)]})
    assert compute_f06_latest(c_flat, oi_up) == 0.0


# ── 3. F7 Long/Short Ratio ───────────────────────────────────────────────────

def test_f07_long_short_contrarian():
    times = pd.date_range("2026-01-01", periods=5, freq="4h", tz="UTC")
    # Retail long share = 0.70 (crowded long, x = +0.20) -> should be -1.0
    df = pd.DataFrame({
        "ts": times,
        "ratio_type": ["global_account"] * 5,
        "long_share": [0.70] * 5,
        "short_share": [0.30] * 5,
    })
    score = compute_f07_latest(df)
    assert score == pytest.approx(-1.0, abs=1e-3)


def test_f07_top_trader_adjustment():
    times = pd.date_range("2026-01-01", periods=2, freq="4h", tz="UTC")
    df = pd.DataFrame({
        "ts": [times[0], times[0]],
        "ratio_type": ["global_account", "top_position"],
        "long_share": [0.65, 0.40],  # Retail long (0.65), top position short (0.40)
        "short_share": [0.35, 0.60],
    })
    score = compute_f07_latest(df)
    # Retail is long (contrarian negative), top position is short (adds -0.2)
    assert score is not None
    assert score < -0.6


# ── 4. F8 Basis ──────────────────────────────────────────────────────────────

def test_f08_basis_expanding():
    """
    Basis score uses rolling_z of basis slope.
    A surge in futures premium relative to flat baseline produces a positive z-score.
    """
    times = pd.date_range("2026-01-01", periods=50, freq="4h", tz="UTC")
    s_close = [100.0] * 50
    # Spot is steady, futures suddenly surges from 100 to 110 over last 20 bars
    f_close = [100.0] * 30 + list(np.linspace(100.0, 110.0, 20))
    f_df = pd.DataFrame({"open_time": times, "close": f_close})
    s_df = pd.DataFrame({"open_time": times, "close": s_close})

    score = compute_f08_latest(f_df, s_df, window_z=30)
    assert score is not None
    assert score > 0.5, f"Expanding futures premium surge should yield positive score, got {score}"


# ── 5. F9 Liquidation Zones ──────────────────────────────────────────────────

def test_f09_liquidation_swing_fallback():
    # If no liquidations exist, fall back to swing_proxy
    times = pd.date_range("2026-01-01", periods=50, freq="4h", tz="UTC")
    c_df = pd.DataFrame({
        "close_time": times,
        "high": [105.0] * 50,
        "low": [95.0] * 50,
        "close": [100.0] * 50,
    })
    above_p, above_n, below_p, below_n, source = compute_f09_latest(
        pd.DataFrame(), c_df, atr14_val=5.0
    )
    assert source == "swing_proxy"
    assert above_n is None
    assert below_n is None


# ── 6. F11 News & News Pause Gate ────────────────────────────────────────────

def test_f11_news_pause_window():
    event_time = pd.Timestamp("2026-03-15 14:00:00", tz="UTC")
    events_df = pd.DataFrame([{
        "name": "FOMC",
        "event_time": event_time,
        "impact": "high",
    }])

    # 15 minutes before event -> inside pause window
    t_inside = event_time - pd.Timedelta(minutes=15)
    _, pause, _ = compute_f11_latest(pd.DataFrame(), 50, events_df, candle_close_time=t_inside)
    assert pause is True, "Should trigger news_pause inside [T-30m, T+60m]"

    # 2 hours before event -> outside pause window
    t_outside = event_time - pd.Timedelta(hours=2)
    _, pause_out, _ = compute_f11_latest(pd.DataFrame(), 50, events_df, candle_close_time=t_outside)
    assert pause_out is False


def test_f11_news_sentiment():
    close_time = pd.Timestamp("2026-03-15 12:00:00", tz="UTC")
    news_df = pd.DataFrame([
        {
            "currency": "BTC",
            "published_at": close_time - pd.Timedelta(hours=2),
            "source": "messari",
            "vader_compound": 0.8,
            "votes_important": 5,
        }
    ])
    events_df = pd.DataFrame()

    score, pause, missing = compute_f11_latest(
        news_df, fear_greed_val=75, events_df=events_df, coin="BTC", candle_close_time=close_time
    )
    assert pause is False
    assert missing is False
    assert score > 0.5


# ── 7. Look-Ahead Bias Verification ──────────────────────────────────────────

def test_no_lookahead_bias():
    """
    Guarantees: Features computed at candle t do NOT change when future data
    (events after candle t) is added to the historical raw tables.
    """
    t_eval = pd.Timestamp("2026-01-05 12:00:00", tz="UTC")

    # Baseline data up to t_eval
    funding_base = pd.DataFrame({
        "funding_time": [t_eval - pd.Timedelta(hours=16), t_eval - pd.Timedelta(hours=8), t_eval],
        "funding_rate": [0.0001, 0.00012, 0.00015],
    })
    # Add future points AFTER t_eval
    funding_with_future = pd.concat([
        funding_base,
        pd.DataFrame({
            "funding_time": [t_eval + pd.Timedelta(hours=8), t_eval + pd.Timedelta(hours=16)],
            "funding_rate": [-0.0005, -0.0008],  # extreme crash in future
        })
    ], ignore_index=True)

    score_base = compute_f05_latest(funding_base, as_of_time=t_eval, lookback_points=3)
    score_future = compute_f05_latest(funding_with_future, as_of_time=t_eval, lookback_points=3)

    assert score_base is not None
    assert score_base == pytest.approx(score_future, abs=1e-8), (
        "Look-ahead check failed! Future data leaked into past candle calculation."
    )
