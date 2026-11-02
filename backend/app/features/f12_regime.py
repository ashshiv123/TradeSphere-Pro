"""
f12_regime.py — Feature 12: Regime Filter (Volatility / Trending Gate).

Plan formula (§8):
  atr_pct = percentile rank of ATR14 over the last 540 candles (90 days)
  bb_pct  = percentile rank of Bollinger width (upper - lower) / middle (20, 2) over 540 candles
  m = (atr_pct + bb_pct) / 2
  regime_factor = 0.2 + 0.8 * clip((m - 0.2) / 0.6, 0, 1)

Output: 0.2 (choppy/low-volatility range) to 1.0 (strong trending regime).
Acts as a position-size / confidence gate, not a directional vote.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import atr, clip, percentile_rank


def compute_f12_series(df: pd.DataFrame, window: int = 540) -> pd.Series:
    """
    Compute F12 regime factor for the entire DataFrame (vectorised).
    Returns pd.Series in range [0.2, 1.0].
    """
    close = df["close"].astype(float)
    atr14 = atr(df, 14)

    # Bollinger Bands (20, 2)
    bb_mid = close.rolling(20, min_periods=5).mean()
    bb_std = close.rolling(20, min_periods=5).std()
    bb_width = ((4.0 * bb_std) / bb_mid.replace(0, np.nan)).fillna(0.0)

    # Percentile ranks over window (default 540 = 90 days of 4h candles)
    atr_pct = percentile_rank(atr14, window=window, min_periods=20)
    bb_pct = percentile_rank(bb_width, window=window, min_periods=20)

    m = (atr_pct + bb_pct) / 2.0
    scaled = clip((m - 0.2) / 0.6, 0.0, 1.0)
    regime_factor = 0.2 + 0.8 * scaled
    return pd.Series(regime_factor, index=df.index, name="g12_regime_factor")


def compute_f12_latest(df: pd.DataFrame, window: int = 540) -> Optional[float]:
    """Compute F12 regime factor for the newest candle."""
    if len(df) < 20:
        return None
    s = compute_f12_series(df, window=window)
    val = s.iloc[-1]
    return None if pd.isna(val) else float(val)
