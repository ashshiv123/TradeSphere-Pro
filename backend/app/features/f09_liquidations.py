"""
f09_liquidations.py — Feature 9: Liquidation Zones and Clusters (Gate Field).

Plan formula (§8):
  Take the last 7 days of liquidations for the symbol.
  Bucket prices into bins of width 0.25 * ATR14. Sum notional per bin.
  A cluster is a bin >= 90th percentile of non-empty bins.
  Store nearest cluster above and below close (price and notional), g09_source = 'liquidation_clusters'.
  If < 200 events in the 7-day window:
    fall back to nearest swing high (above) and swing low (below) from candles,
    g09_source = 'swing_proxy', notional = None.
"""
from __future__ import annotations

from typing import Optional, Tuple
import numpy as np
import pandas as pd

from app.features.f10_volume_sr import find_sr_levels


def compute_f09_latest(
    liq_df: pd.DataFrame,
    candles_df: pd.DataFrame,
    atr14_val: float,
    as_of_time: Optional[pd.Timestamp] = None,
) -> Tuple[
    Optional[float], Optional[float], Optional[float], Optional[float], str
]:
    """
    Compute liquidation cluster levels (above & below) for current candle.
    Returns:
      (liq_above_price, liq_above_notional, liq_below_price, liq_below_notional, source)
    """
    if candles_df.empty:
        return None, None, None, None, "swing_proxy"

    c_df = candles_df.copy()
    c_df["close_time"] = pd.to_datetime(c_df["close_time"], utc=True)
    c_df = c_df.sort_values("close_time")

    if as_of_time is not None:
        as_of = pd.to_datetime(as_of_time, utc=True)
        c_df = c_df[c_df["close_time"] <= as_of]

    current_close = float(c_df["close"].iloc[-1])
    current_time = c_df["close_time"].iloc[-1]

    # Filter liquidations in the 7 days prior to candle close
    has_liq_data = False
    valid_events = pd.DataFrame()

    if not liq_df.empty:
        l_df = liq_df.copy()
        l_df["ts"] = pd.to_datetime(l_df["ts"], utc=True)
        seven_days_ago = current_time - pd.Timedelta(days=7)
        valid_events = l_df[
            (l_df["ts"] >= seven_days_ago) & (l_df["ts"] <= current_time)
        ]
        has_liq_data = len(valid_events) >= 200

    # Primary method: Liquidation clusters
    if has_liq_data and atr14_val > 0:
        bin_width = 0.25 * atr14_val
        prices = valid_events["price"].astype(float).values
        notionals = valid_events["notional"].astype(float).values

        min_p = np.min(prices)
        max_p = np.max(prices)

        if max_p > min_p:
            bins = np.arange(min_p, max_p + bin_width, bin_width)
            digitized = np.digitize(prices, bins)

            # Sum notional per bin
            bin_sums = {}
            for bin_idx, notional in zip(digitized, notionals):
                bin_sums[bin_idx] = bin_sums.get(bin_idx, 0.0) + notional

            non_empty_values = list(bin_sums.values())
            p90 = np.percentile(non_empty_values, 90)

            # High-density clusters
            cluster_above_p = None
            cluster_above_n = None
            cluster_below_p = None
            cluster_below_n = None

            min_dist_above = float("inf")
            min_dist_below = float("inf")

            for b_idx, n_sum in bin_sums.items():
                if n_sum >= p90 and b_idx < len(bins):
                    bin_center = bins[b_idx] + (bin_width / 2.0)
                    if bin_center > current_close:
                        dist = bin_center - current_close
                        if dist < min_dist_above:
                            min_dist_above = dist
                            cluster_above_p = float(bin_center)
                            cluster_above_n = float(n_sum)
                    elif bin_center < current_close:
                        dist = current_close - bin_center
                        if dist < min_dist_below:
                            min_dist_below = dist
                            cluster_below_p = float(bin_center)
                            cluster_below_n = float(n_sum)

            if cluster_above_p is not None or cluster_below_p is not None:
                return (
                    cluster_above_p,
                    cluster_above_n,
                    cluster_below_p,
                    cluster_below_n,
                    "liquidation_clusters",
                )

    # Fallback method: swing_proxy
    supports, resistances = find_sr_levels(
        c_df["high"].astype(float), c_df["low"].astype(float), window=60
    )

    above_levels = [r for r in resistances if r > current_close]
    below_levels = [s for s in supports if s < current_close]

    nearest_above = min(above_levels) if above_levels else None
    nearest_below = max(below_levels) if below_levels else None

    return nearest_above, None, nearest_below, None, "swing_proxy"

