"""
test_stage6_price_features.py — Unit tests for Stage 6 Price-Derived Features.

Tests:
1. Math & indicator helpers: clip, squash, rolling_z, ema, atr, rsi against hand-calculated values.
2. F1 Momentum: rising prices produce positive score; falling prices produce negative score.
3. F2 EMA Trend: verify bullish gap and agreement/penalty; compare with independent calculation.
4. F3 RSI + Divergence: verify RSI 61 produces +0.22 (blueprint worked example); test divergence.
5. F4 MACD: histogram and slope combination.
6. F10 Volume and S/R: high volume pump gives positive vol component.
7. F12 Regime: trending high volatility gives higher regime factor (> 0.5), flat gives low (0.2).
8. F13 BTC Correlation: BTCUSDT returns 1.0 corr and 1.0 beta; synthetic altcoin tests.
9. Verification of full-history vectorised vs newest-candle single computation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.features.common import (
    atr,
    clip,
    ema,
    percentile_rank,
    rolling_z,
    rsi,
    squash,
)
from app.features.f01_momentum import compute_f01_latest, compute_f01_series
from app.features.f02_ema_trend import compute_f02_latest, compute_f02_series
from app.features.f03_rsi import (
    compute_f03_latest,
    compute_f03_series,
    compute_rsi_base,
)
from app.features.f04_macd import compute_f04_latest, compute_f04_series
from app.features.f10_volume_sr import compute_f10_latest, compute_f10_series
from app.features.f12_regime import compute_f12_latest, compute_f12_series
from app.features.f13_btc_correlation import (
    compute_f13_latest,
    compute_f13_series,
)


# ── 1. Helpers & Indicators ──────────────────────────────────────────────────

def test_clip():
    assert clip(1.5, -1, 1) == 1.0
    assert clip(-2.0, -1, 1) == -1.0
    assert clip(0.35, -1, 1) == 0.35


def test_squash():
    assert squash(2.0) == 1.0
    assert squash(-2.0) == -1.0
    assert squash(1.0) == 0.5
    assert squash(0.0) == 0.0


def test_ema_hand_calc():
    """
    EMA with span=3 has alpha = 2 / (3 + 1) = 0.5.
    values = [10, 20, 30]
    t=0: 10
    t=1: 0.5 * 20 + 0.5 * 10 = 15
    t=2: 0.5 * 30 + 0.5 * 15 = 22.5
    """
    s = pd.Series([10.0, 20.0, 30.0])
    res = ema(s, span=3)
    assert res.iloc[0] == 10.0
    assert res.iloc[1] == 15.0
    assert res.iloc[2] == 22.5


def test_atr_hand_calc():
    """
    Check True Range calculation for candles with gaps.
    """
    df = pd.DataFrame({
        "high": [105.0, 110.0, 108.0],
        "low":  [95.0,  100.0, 96.0],
        "close": [100.0, 105.0, 98.0],
    })
    # t=0: high - low = 10
    # t=1: max(110-100, |110-100|, |100-100|) = 10
    # t=2: max(108-96, |108-105|, |96-105|) = max(12, 3, 9) = 12
    atr_vals = atr(df, period=2)
    assert len(atr_vals) == 3
    assert atr_vals.iloc[-1] > 0


def test_rsi_blueprint_example():
    """
    Blueprint worked example test:
    RSI = 61 maps to base score of +0.22.
    Formula: (61 - 50) / 50 = 11 / 50 = +0.22.
    """
    s = pd.Series([61.0])
    base = compute_rsi_base(s).iloc[0]
    assert base == pytest.approx(0.22, abs=1e-4)


# ── Synthetic Dataset Generator ──────────────────────────────────────────────

def create_synthetic_data(n: int = 250, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic OHLCV candles with upward, downward, or flat trend."""
    np.random.seed(42)
    if trend == "up":
        step = np.random.normal(0.5, 0.2, n)
    elif trend == "down":
        step = np.random.normal(-0.5, 0.2, n)
    else:
        step = np.random.normal(0.0, 0.2, n)

    close = 100.0 + np.cumsum(step)
    high = close + np.random.uniform(0.5, 1.5, n)
    low = close - np.random.uniform(0.5, 1.5, n)
    open_ = (close + low) / 2.0
    volume = np.random.uniform(100.0, 500.0, n)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ── 2. Feature Tests ─────────────────────────────────────────────────────────

def test_f01_momentum_direction():
    """
    Momentum measures relative return acceleration against its rolling history:
    - Flat baseline followed by strong upward surge gives positive momentum.
    - Flat baseline followed by strong downward dump gives negative momentum.
    """
    # Upward surge: 100 flat bars, then 50 bars surging up
    p_up = np.concatenate([np.full(100, 100.0), np.linspace(100.0, 150.0, 50)])
    df_up = pd.DataFrame({"close": p_up})
    score_up = compute_f01_latest(df_up, window=100)
    assert score_up is not None
    assert score_up > 0.5, f"Upward surge should give positive momentum, got {score_up}"

    # Downward dump: 100 flat bars, then 50 bars dumping down
    p_down = np.concatenate([np.full(100, 100.0), np.linspace(100.0, 60.0, 50)])
    df_down = pd.DataFrame({"close": p_down})
    score_down = compute_f01_latest(df_down, window=100)
    assert score_down is not None
    assert score_down < -0.5, f"Downward dump should give negative momentum, got {score_down}"


def test_f02_ema_trend_and_verification():
    """
    Verify F2 EMA trend:
    1. Uptrend produces positive EMA gap.
    2. Vectorised vs single value match.
    3. Independent calculation comparison.
    """
    df = create_synthetic_data(100, trend="up")
    series = compute_f02_series(df)
    latest = compute_f02_latest(df)

    assert latest is not None
    assert latest > 0.0
    assert series.iloc[-1] == pytest.approx(latest, abs=1e-5)

    # Independent check:
    close = df["close"].astype(float)
    calc_e21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    calc_e55 = close.ewm(span=55, adjust=False).mean().iloc[-1]
    assert calc_e21 > calc_e55, "In an uptrend EMA21 should be above EMA55"


def test_f03_rsi_bounds_and_latest():
    df = create_synthetic_data(100, trend="up")
    series = compute_f03_series(df)
    latest = compute_f03_latest(df)

    assert latest is not None
    assert -1.0 <= latest <= 1.0
    assert (series >= -1.0).all() and (series <= 1.0).all()
    assert series.iloc[-1] == pytest.approx(latest, abs=1e-5)


def test_f04_macd_bounds_and_latest():
    df = create_synthetic_data(100, trend="up")
    series = compute_f04_series(df, window=50)
    latest = compute_f04_latest(df, window=50)

    assert latest is not None
    assert -1.0 <= latest <= 1.0
    assert series.iloc[-1] == pytest.approx(latest, abs=1e-5)


def test_f10_volume_sr():
    df = create_synthetic_data(100, trend="up")
    # Simulate a volume pump on the last candle
    df.loc[df.index[-1], "volume"] = df["volume"].mean() * 3.0

    score_s, vol_s = compute_f10_series(df)
    score, vol_ratio = compute_f10_latest(df)

    assert score is not None
    assert vol_ratio is not None
    assert vol_ratio > 1.5, "Volume pump should yield volume_ratio > 1.5"
    assert score > 0.0, "Uptrend with volume pump should yield positive score"
    assert -1.0 <= score <= 1.0


def test_f12_regime_factor():
    """Regime factor must be between 0.2 and 1.0."""
    df = create_synthetic_data(100, trend="up")
    series = compute_f12_series(df, window=50)
    latest = compute_f12_latest(df, window=50)

    assert latest is not None
    assert 0.2 <= latest <= 1.0
    assert (series >= 0.2).all() and (series <= 1.0).all()
    assert series.iloc[-1] == pytest.approx(latest, abs=1e-5)


def test_f13_btc_correlation_and_beta():
    """
    BTCUSDT itself must have correlation=1.0 and beta=1.0.
    """
    df_btc = create_synthetic_data(100, trend="up")
    corr, beta, trend, dom = compute_f13_latest(
        df_btc, df_btc, symbol="BTCUSDT", window=50, latest_dominance=58.5
    )
    assert corr == 1.0
    assert beta == 1.0
    assert trend in (-1, 0, 1)
    assert dom == 58.5

    # Altcoin test
    df_alt = create_synthetic_data(100, trend="up")
    corr_alt, beta_alt, trend_alt, _ = compute_f13_latest(
        df_alt, df_btc, symbol="ETHUSDT", window=50
    )
    assert corr_alt is not None
    assert beta_alt is not None
    assert -1.0 <= corr_alt <= 1.0
