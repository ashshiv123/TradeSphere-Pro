"""
f08_basis.py — Feature 8: Perpetual-to-Spot Basis Trend.

Plan formula (§8):
  basis = (futures_close - spot_close) / spot_close per candle
  slope = linear regression slope of basis over last 18 candles (3 days)
  Score = squash(rolling_z(slope, window=540))

Positive slope means futures premium is expanding (speculative bullish positioning).
Returns float in [-1.0, 1.0], or None if spot/futures candles are missing.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import rolling_z, squash


def compute_basis_slope_18(basis_series: pd.Series) -> pd.Series:
    """Compute rolling linear-regression slope over 18 candles."""
    def _slope(arr: np.ndarray) -> float:
        if len(arr) < 2 or np.isnan(arr).any():
            return 0.0
        x = np.arange(len(arr))
        slope, _ = np.polyfit(x, arr, 1)
        return float(slope)

    return basis_series.rolling(18, min_periods=6).apply(_slope, raw=True)


def compute_f08_latest(
    futures_df: pd.DataFrame,
    spot_df: pd.DataFrame,
    as_of_time: Optional[pd.Timestamp] = None,
    window_z: int = 540,
) -> Optional[float]:
    """
    Compute F8 perp-spot basis score.
    futures_df and spot_df must have ['open_time', 'close'].
    Guarantees NO lookahead: only candles <= as_of_time are used.
    """
    if futures_df.empty or spot_df.empty:
        return None

    f_df = futures_df.copy()
    s_df = spot_df.copy()

    f_df["open_time"] = pd.to_datetime(f_df["open_time"], utc=True)
    s_df["open_time"] = pd.to_datetime(s_df["open_time"], utc=True)

    if as_of_time is not None:
        as_of = pd.to_datetime(as_of_time, utc=True)
        f_df = f_df[f_df["open_time"] <= as_of]
        s_df = s_df[s_df["open_time"] <= as_of]

    # Align futures and spot candles on open_time
    merged = pd.merge(
        f_df[["open_time", "close"]].rename(columns={"close": "f_close"}),
        s_df[["open_time", "close"]].rename(columns={"close": "s_close"}),
        on="open_time",
        how="inner",
    ).sort_values("open_time")

    if len(merged) < 18:
        return None

    f_c = merged["f_close"].astype(float)
    s_c = merged["s_close"].astype(float)
    basis = (f_c - s_c) / s_c.replace(0, np.nan)

    basis_slopes = compute_basis_slope_18(basis)
    z = rolling_z(basis_slopes, window=window_z, min_periods=18)
    score = squash(z)

    val = score.iloc[-1]
    return None if pd.isna(val) else float(val)
