"""
f05_funding.py — Feature 5: Funding Rate Trend.

Plan formula (§8):
  Funding points arrive every 8 hours.
  Take the last 12 points (4 days).
  Compute linear-regression slope.
  Divide by rolling std of slope over 90 days (270 points), and squash:
    score = squash(slope / rolling_std)
  If latest funding rate has the same sign as score and abs(funding) >= 0.0005:
    score = score * 0.5 (crowded trade dampener)
  Output: -1.0 to +1.0. If < 12 points available, returns None.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import squash


def compute_funding_slope(rates: np.ndarray) -> float:
    """Calculate linear-regression slope of funding rates across points."""
    n = len(rates)
    if n < 2:
        return 0.0
    x = np.arange(n)
    # polyfit degree 1: returns [slope, intercept]
    slope, _ = np.polyfit(x, rates, 1)
    return float(slope)


def compute_f05_latest(
    funding_df: pd.DataFrame,
    as_of_time: Optional[pd.Timestamp] = None,
    lookback_points: int = 12,
    window_std_points: int = 270,
) -> Optional[float]:
    """
    Compute F5 funding trend score for a candle as-of time.
    funding_df must have columns ['funding_time', 'funding_rate'].
    Guarantees NO lookahead: only records with funding_time <= as_of_time are used.
    """
    if funding_df.empty:
        return None

    df = funding_df.copy()
    df["funding_time"] = pd.to_datetime(df["funding_time"], utc=True)
    df = df.sort_values("funding_time")

    if as_of_time is not None:
        as_of = pd.to_datetime(as_of_time, utc=True)
        df = df[df["funding_time"] <= as_of]

    if len(df) < lookback_points:
        return None

    rates = df["funding_rate"].astype(float).values
    recent_rates = rates[-lookback_points:]
    slope = compute_funding_slope(recent_rates)

    # Compute rolling std of 12-point slopes over the 90-day history (up to 270 points)
    hist_len = min(len(rates), window_std_points)
    if hist_len >= 24:
        # Calculate rolling slopes
        slopes = []
        for i in range(lookback_points, hist_len + 1):
            slopes.append(compute_funding_slope(rates[i - lookback_points : i]))
        slope_std = float(np.std(slopes)) if len(slopes) > 1 else 0.0
    else:
        # Fallback std estimate if early in collection
        slope_std = float(np.std(recent_rates)) if len(recent_rates) > 1 else 0.0

    if slope_std <= 0:
        slope_std = 1e-6

    z = slope / slope_std
    score = float(squash(z))

    # Crowded trade dampener: if latest funding has same sign and abs >= 0.0005 (0.05%)
    latest_funding = recent_rates[-1]
    if (np.sign(latest_funding) == np.sign(score)) and (abs(latest_funding) >= 0.0005):
        score *= 0.5

    return score
