"""
common.py — Shared mathematical, indicator, and alignment helpers for feature calculation.

Follows DATA_PIPELINE_PLAN.md §8 strictly.
"""
from __future__ import annotations

from typing import Union
import numpy as np
import pandas as pd


def clip(x: Union[float, np.ndarray, pd.Series], lower: float = -1.0, upper: float = 1.0):
    """Clip a scalar or array between lower and upper bounds."""
    if isinstance(x, (pd.Series, np.ndarray)):
        return np.clip(x, lower, upper)
    return max(lower, min(upper, float(x)))


def squash(z: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """squash(z) = clip(z / 2, -1, 1). Maps roughly [-2, 2] standard deviations to [-1, 1]."""
    return clip(z / 2.0, -1.0, 1.0)


def rolling_z(series: pd.Series, window: int = 1080, min_periods: int = 30) -> pd.Series:
    """
    Compute rolling z-score: (value - rolling_mean) / rolling_std.
    Falls back to min_periods if not enough history, returns 0.0 where std is 0.
    """
    r_mean = series.rolling(window=window, min_periods=min_periods).mean()
    r_std = series.rolling(window=window, min_periods=min_periods).std()
    z = (series - r_mean) / r_std.replace(0, np.nan)
    return z.fillna(0.0)


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average using ewm(span=span, adjust=False)."""
    return series.ewm(span=span, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range = max(high - low, abs(high - close_prev), abs(low - close_prev)).
    df must contain 'high', 'low', 'close'.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder smoothing (ewm(alpha=1/period, adjust=False))."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index using Wilder smoothing:
    ewm(alpha=1/period, adjust=False) for average gain and average loss.
    """
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    res = 100.0 - (100.0 / (1.0 + rs))

    # Where loss is 0 and gain > 0 -> 100; where both 0 -> 50
    res = res.fillna(50.0)
    res = res.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    res = res.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return res


def percentile_rank(series: pd.Series, window: int = 540, min_periods: int = 30) -> pd.Series:
    """
    Rolling percentile rank of the current value within the last `window` values.
    Returns float in range [0.0, 1.0].
    """
    def _pct(arr: np.ndarray) -> float:
        val = arr[-1]
        valid = arr[~np.isnan(arr)]
        if len(valid) == 0:
            return 0.5
        return float(np.sum(valid <= val) / len(valid))

    return series.rolling(window=window, min_periods=min_periods).apply(_pct, raw=True).fillna(0.5)


def asof_join(
    candles_df: pd.DataFrame,
    slower_df: pd.DataFrame,
    candle_time_col: str = "close_time",
    slower_time_col: str = "ts",
) -> pd.DataFrame:
    """
    Attach the most recent value from slower_df available at or before candle close.
    Guarantees NO look-ahead bias: slower timestamp <= candle close_time.
    """
    if slower_df.empty:
        return candles_df

    c_sorted = candles_df.sort_values(candle_time_col).copy()
    s_sorted = slower_df.sort_values(slower_time_col).copy()

    # pandas merge_asof requires exact datetime64 types
    c_sorted[candle_time_col] = pd.to_datetime(c_sorted[candle_time_col], utc=True)
    s_sorted[slower_time_col] = pd.to_datetime(s_sorted[slower_time_col], utc=True)

    merged = pd.merge_asof(
        c_sorted,
        s_sorted,
        left_on=candle_time_col,
        right_on=slower_time_col,
        direction="backward",
    )
    return merged
