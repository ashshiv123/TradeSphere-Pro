"""
f04_macd.py — Feature 4: MACD.

Plan formula (§8):
  hist = MACD(12, 26, 9).histogram
  slope = hist - hist.shift(1)
  Score = clip(0.6 * squash(rolling_z(hist / close, 1080)) + 0.4 * squash(rolling_z(slope / close, 1080)), -1, 1)
"""
from __future__ import annotations

from typing import Optional
import pandas as pd

from app.features.common import clip, ema, rolling_z, squash


def compute_f04_series(df: pd.DataFrame, window: int = 1080) -> pd.Series:
    """
    Compute F4 MACD score for the entire DataFrame (vectorised).
    df must contain 'close' column sorted ascending by time.
    Returns pd.Series in range [-1.0, 1.0].
    """
    close = df["close"].astype(float)
    fast = ema(close, 12)
    slow = ema(close, 26)
    macd_line = fast - slow
    signal_line = ema(macd_line, 9)
    hist = macd_line - signal_line

    slope = hist.diff()

    # Normalize by close price so different price levels / coins are comparable
    norm_hist = hist / close
    norm_slope = slope / close

    z_hist = rolling_z(norm_hist, window=window, min_periods=30)
    z_slope = rolling_z(norm_slope, window=window, min_periods=30)

    score = 0.6 * squash(z_hist) + 0.4 * squash(z_slope)
    return clip(score, -1.0, 1.0).rename("f04_macd")


def compute_f04_latest(df: pd.DataFrame, window: int = 1080) -> Optional[float]:
    """Compute F4 MACD score for the newest candle."""
    if len(df) < 35:
        return None
    s = compute_f04_series(df, window=window)
    val = s.iloc[-1]
    return None if pd.isna(val) else float(val)

