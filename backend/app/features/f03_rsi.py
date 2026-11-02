"""
f03_rsi.py — Feature 3: RSI with Divergence.

Plan formula (§8):
  rsi = RSI14
  If 30 <= rsi <= 70: base = (rsi - 50) / 50
  If rsi > 70:        base = 0.4 - (rsi - 70) / 30
  If rsi < 30:        base = -0.4 + (30 - rsi) / 30

  Divergence over the last 30 candles using swing points (local highs and lows with window 3):
    bearish (price higher high, RSI lower high) adds -0.3
    bullish (price lower low, RSI higher low)   adds +0.3

  Score = clip(base + divergence, -1, 1)
  Note: RSI 61 gives base = +0.22 (matches blueprint worked example).
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import clip, rsi


def compute_rsi_base(rsi_series: pd.Series) -> pd.Series:
    """Map raw 0..100 RSI to base score in [-1.0, 1.0]."""
    r = rsi_series.astype(float)
    base = pd.Series(index=r.index, dtype=float)

    # 30 <= rsi <= 70
    mid_mask = (r >= 30) & (r <= 70)
    base[mid_mask] = (r[mid_mask] - 50.0) / 50.0

    # rsi > 70 (overbought, contrarian negative slope)
    high_mask = r > 70
    base[high_mask] = 0.4 - (r[high_mask] - 70.0) / 30.0

    # rsi < 30 (oversold, contrarian positive slope)
    low_mask = r < 30
    base[low_mask] = -0.4 + (30.0 - r[low_mask]) / 30.0

    return base


def detect_divergence_latest(
    high: pd.Series, low: pd.Series, rsi_series: pd.Series, window: int = 30
) -> float:
    """
    Check for regular bullish or bearish divergence over the last `window` candles.
    Uses window 3 swing points confirmed causally up to current time.
    Returns: -0.3 for bearish, +0.3 for bullish, or 0.0.
    """
    n = len(high)
    if n < window:
        return 0.0

    sub_h = high.iloc[-window:].values
    sub_l = low.iloc[-window:].values
    sub_r = rsi_series.iloc[-window:].values

    # Find swing highs: h[i] is greater than 3 before and 3 after
    # To be causal, i <= len(sub) - 4 (confirmed 3 bars ago)
    swing_highs = []
    for i in range(3, len(sub_h) - 3):
        if (
            sub_h[i] >= np.max(sub_h[i - 3 : i])
            and sub_h[i] >= np.max(sub_h[i + 1 : i + 4])
        ):
            swing_highs.append((sub_h[i], sub_r[i]))

    # Find swing lows
    swing_lows = []
    for i in range(3, len(sub_l) - 3):
        if (
            sub_l[i] <= np.min(sub_l[i - 3 : i])
            and sub_l[i] <= np.min(sub_l[i + 1 : i + 4])
        ):
            swing_lows.append((sub_l[i], sub_r[i]))

    div_adj = 0.0

    # Bearish divergence: price higher high, RSI lower high
    if len(swing_highs) >= 2:
        prev_p, prev_r = swing_highs[-2]
        curr_p, curr_r = swing_highs[-1]
        if curr_p > prev_p and curr_r < prev_r:
            div_adj -= 0.3

    # Bullish divergence: price lower low, RSI higher low
    if len(swing_lows) >= 2:
        prev_p, prev_r = swing_lows[-2]
        curr_p, curr_r = swing_lows[-1]
        if curr_p < prev_p and curr_r > prev_r:
            div_adj += 0.3

    return div_adj


def compute_f03_series(df: pd.DataFrame) -> pd.Series:
    """
    Compute F3 RSI with divergence for each candle in history.
    df must contain 'high', 'low', 'close'.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    rsi14 = rsi(close, 14)
    base = compute_rsi_base(rsi14)

    # Compute divergence across rolling window
    n = len(df)
    div_scores = np.zeros(n, dtype=float)

    for i in range(35, n):
        div_scores[i] = detect_divergence_latest(
            high.iloc[: i + 1], low.iloc[: i + 1], rsi14.iloc[: i + 1], window=30
        )

    score = clip(base + div_scores, -1.0, 1.0)
    return pd.Series(score, index=df.index, name="f03_rsi")


def compute_f03_latest(df: pd.DataFrame) -> Optional[float]:
    """Compute F3 RSI with divergence for the newest candle."""
    if len(df) < 15:
        return None
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    rsi14 = rsi(close, 14)
    base_val = compute_rsi_base(rsi14).iloc[-1]
    div_val = detect_divergence_latest(high, low, rsi14, window=30)
    score = clip(base_val + div_val, -1.0, 1.0)
    return float(score)

