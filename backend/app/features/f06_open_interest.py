"""
f06_open_interest.py — Feature 6: Open Interest Trend Matrix.

Plan formula (§8):
  Over the last 6 candles (24 hours):
    price_change = (close[t] - close[t - 6]) / close[t - 6]
    oi_change    = (oi[t] - oi[t - 6]) / oi[t - 6]   (from sum_open_interest_value)
  If abs(price_change) < 0.2% or abs(oi_change) < 0.5%:
    score = 0.0
  Otherwise:
    price UP   and OI UP   -> +1.0 (aggressive buyer accumulation)
    price UP   and OI DOWN -> +0.3 (short-covering rally)
    price DOWN and OI UP   -> -1.0 (aggressive short accumulation)
    price DOWN and OI DOWN -> -0.3 (long liquidation cascade)

Returns float in [-1.0, 1.0], or None if OI data is missing.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd


def compute_f06_latest(
    candles_df: pd.DataFrame,
    oi_df: pd.DataFrame,
    as_of_time: Optional[pd.Timestamp] = None,
) -> Optional[float]:
    """
    Compute F6 OI trend score for the candle at as_of_time.
    candles_df must have ['close_time', 'close'].
    oi_df must have ['ts', 'sum_open_interest_value'].
    Guarantees NO lookahead: only records <= as_of_time are used.
    """
    if candles_df.empty or oi_df.empty:
        return None

    c_df = candles_df.copy()
    c_df["close_time"] = pd.to_datetime(c_df["close_time"], utc=True)
    c_df = c_df.sort_values("close_time")

    o_df = oi_df.copy()
    o_df["ts"] = pd.to_datetime(o_df["ts"], utc=True)
    o_df = o_df.sort_values("ts")

    if as_of_time is not None:
        as_of = pd.to_datetime(as_of_time, utc=True)
        c_df = c_df[c_df["close_time"] <= as_of]
        o_df = o_df[o_df["ts"] <= as_of]

    if len(c_df) < 7 or len(o_df) < 2:
        return None

    # Price change over last 6 candles
    close_curr = float(c_df["close"].iloc[-1])
    close_prev = float(c_df["close"].iloc[-7])
    if close_prev <= 0:
        return None
    price_change = (close_curr - close_prev) / close_prev

    # Find OI at or immediately preceding current candle and 6 candles ago (24h)
    t_curr = c_df["close_time"].iloc[-1]
    t_prev = c_df["close_time"].iloc[-7]

    oi_curr_sub = o_df[o_df["ts"] <= t_curr]
    oi_prev_sub = o_df[o_df["ts"] <= t_prev]

    if oi_curr_sub.empty or oi_prev_sub.empty:
        return None

    oi_curr = float(oi_curr_sub["sum_open_interest_value"].iloc[-1])
    oi_prev = float(oi_prev_sub["sum_open_interest_value"].iloc[-1])

    if oi_prev <= 0:
        return None

    oi_change = (oi_curr - oi_prev) / oi_prev

    # Dead zones: < 0.2% price change or < 0.5% OI change
    if abs(price_change) < 0.002 or abs(oi_change) < 0.005:
        return 0.0

    # 2x2 Matrix
    if price_change > 0 and oi_change > 0:
        return 1.0
    elif price_change > 0 and oi_change < 0:
        return 0.3
    elif price_change < 0 and oi_change > 0:
        return -1.0
    else:  # price_change < 0 and oi_change < 0
        return -0.3
