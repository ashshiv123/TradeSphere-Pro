"""
f02_ema_trend.py — Feature 2: EMA Trend.

Plan formula (§8):
  ema21, ema55
  gap = (ema21 - ema55) / ATR14
  Score = clip(gap / 2, -1, 1)
  If sign(gap) disagrees with slope of ema21 over the last 3 candles, multiply score by 0.5.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import atr, clip, ema


def compute_f02_series(df: pd.DataFrame) -> pd.Series:
    """
    Compute F2 EMA trend score for the entire DataFrame (vectorised).
    df must contain 'high', 'low', 'close' columns sorted ascending by time.
    Returns pd.Series in range [-1.0, 1.0].
    """
    close = df["close"].astype(float)
    ema21 = ema(close, 21)
    ema55 = ema(close, 55)
    atr14 = atr(df, 14).replace(0, np.nan)

    gap = (ema21 - ema55) / atr14
    score = clip(gap / 2.0, -1.0, 1.0)

    # Slope of ema21 over last 3 candles
    slope3 = ema21 - ema21.shift(3)

    # Disagreement: sign(gap) != sign(slope3)
    sign_gap = np.sign(gap)
    sign_slope = np.sign(slope3)

    disagree = (sign_gap != 0) & (sign_slope != 0) & (sign_gap != sign_slope)
    # Also if slope is flat (0) while gap is nonzero, dampen
    disagree = disagree | ((sign_gap != 0) & (sign_slope == 0))

    score = np.where(disagree, score * 0.5, score)
    return pd.Series(score, index=df.index, name="f02_ema_trend")


def compute_f02_latest(df: pd.DataFrame) -> Optional[float]:
    """Compute F2 EMA trend score for the newest candle."""
    if len(df) < 55:
        return None
    s = compute_f02_series(df)
    val = s.iloc[-1]
    return None if pd.isna(val) else float(val)
