"""
f10_volume_sr.py — Feature 10: Volume and Support / Resistance.

Plan formula (§8):
  volume_ratio = volume / SMA20(volume)
  vol_component = sign(close - close[t - 6]) * clip(volume_ratio - 1, 0, 1)

  Find swing highs (resistance) and swing lows (support) over the last 60 candles.
  If close is within 1 ATR above a support level:   sr_component = +0.3
  If close is within 1 ATR below a resistance level: sr_component = -0.3
  otherwise: 0.0

  Score = clip(0.6 * vol_component + 0.4 * sr_component, -1, 1)
  Also returns volume_ratio (scoring engine uses volume_ratio >= 1.2 as a confirmation gate).
"""
from __future__ import annotations

from typing import Optional, Tuple
import numpy as np
import pandas as pd

from app.features.common import atr, clip


def find_sr_levels(
    high: pd.Series, low: pd.Series, window: int = 60
) -> Tuple[list[float], list[float]]:
    """
    Find swing highs (resistance) and swing lows (support) over the last `window` candles.
    Uses window 3 swing points.
    """
    if len(high) < 7:
        return [], []

    sub_h = high.iloc[-window:].values
    sub_l = low.iloc[-window:].values

    resistances = []
    supports = []

    for i in range(3, len(sub_h) - 3):
        if (
            sub_h[i] >= np.max(sub_h[i - 3 : i])
            and sub_h[i] >= np.max(sub_h[i + 1 : i + 4])
        ):
            resistances.append(float(sub_h[i]))
        if (
            sub_l[i] <= np.min(sub_l[i - 3 : i])
            and sub_l[i] <= np.min(sub_l[i + 1 : i + 4])
        ):
            supports.append(float(sub_l[i]))

    return supports, resistances


def compute_f10_series(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """
    Compute F10 score and volume_ratio for the entire DataFrame.
    Returns (f10_score_series, volume_ratio_series).
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    sma20 = vol.rolling(20, min_periods=5).mean().replace(0, np.nan)
    volume_ratio = (vol / sma20).fillna(1.0)

    # 24h price return direction: close vs close 6 candles ago
    c_lag6 = close.shift(6)
    direction = np.sign(close - c_lag6).fillna(0.0)

    vol_comp = direction * clip(volume_ratio - 1.0, 0.0, 1.0)
    atr14 = atr(df, 14)

    n = len(df)
    sr_comp = np.zeros(n, dtype=float)

    for i in range(25, n):
        cur_c = close.iloc[i]
        cur_atr = atr14.iloc[i]
        if pd.isna(cur_atr) or cur_atr <= 0:
            continue

        supports, resistances = find_sr_levels(
            high.iloc[: i + 1], low.iloc[: i + 1], window=60
        )

        component = 0.0
        # If close is within 1 ATR above a support level: +0.3
        near_support = any(0.0 <= (cur_c - s) <= cur_atr for s in supports)
        # If close is within 1 ATR below a resistance level: -0.3
        near_resistance = any(0.0 <= (r - cur_c) <= cur_atr for r in resistances)

        if near_support and not near_resistance:
            component = 0.3
        elif near_resistance and not near_support:
            component = -0.3
        elif near_support and near_resistance:
            component = 0.0  # conflicting near both levels

        sr_comp[i] = component

    score = clip(0.6 * vol_comp + 0.4 * sr_comp, -1.0, 1.0)
    return (
        pd.Series(score, index=df.index, name="f10_volume_sr"),
        pd.Series(volume_ratio, index=df.index, name="volume_ratio"),
    )


def compute_f10_latest(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
    """Compute (f10_score, volume_ratio) for the newest candle."""
    if len(df) < 20:
        return None, None
    score_s, vol_s = compute_f10_series(df)
    v1 = score_s.iloc[-1]
    v2 = vol_s.iloc[-1]
    return (
        None if pd.isna(v1) else float(v1),
        None if pd.isna(v2) else float(v2),
    )
