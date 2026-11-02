"""
f01_momentum.py — Feature 1: Momentum.

Plan formula (§8):
  r = close[t - 6] / close[t - 6 - 84] - 1  (14-day return, skipping the latest day)
  Score = squash(rolling_z(r, 1080))
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from app.features.common import rolling_z, squash


def compute_f01_series(df: pd.DataFrame, window: int = 1080) -> pd.Series:
    """
    Compute F1 momentum score for the entire DataFrame (vectorised).
    df must contain 'close' column sorted ascending by time.
    Returns pd.Series in range [-1.0, 1.0].
    """
    close = df["close"].astype(float)
    # close[t - 6] is close shifted by 6, close[t - 90] is shifted by 90
    c_lag6 = close.shift(6)
    c_lag90 = close.shift(90)

    # 14-day return, skipping latest 24 hours (6 x 4h candles)
    r = (c_lag6 / c_lag90) - 1.0
    z = rolling_z(r, window=window, min_periods=30)
    score = squash(z)
    return score.rename("f01_momentum")


def compute_f01_latest(df: pd.DataFrame, window: int = 1080) -> Optional[float]:
    """Compute F1 momentum score for the most recent candle."""
    if len(df) < 91:
        return None
    s = compute_f01_series(df, window=window)
    val = s.iloc[-1]
    return None if pd.isna(val) else float(val)

