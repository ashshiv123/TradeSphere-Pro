"""
f07_long_short.py — Feature 7: Long / Short Ratio (Retail Contrarian + Smart Money Alignment).

Plan formula (§8):
  x = global_account long_share - 0.5
  Dead zone 0.06, full scale at 0.20:
    s = -sign(x) * clip((abs(x) - 0.06) / 0.14, 0, 1)  (contrarian to crowded retail)

  If top_position long share is on the opposite side of 0.5 from retail by > 0.05:
    add +0.2 in the top-trader direction:
    if top_position long_share > 0.5 -> add +0.2
    if top_position long_share < 0.5 -> add -0.2

  Score = clip(s + top_adjustment, -1, 1)
  Returns None if ratio data is missing.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from app.features.common import clip


def compute_f07_latest(
    ls_df: pd.DataFrame,
    as_of_time: Optional[pd.Timestamp] = None,
) -> Optional[float]:
    """
    Compute F7 Long/Short ratio score.
    ls_df must have ['ts', 'ratio_type', 'long_share', 'short_share'].
    Guarantees NO lookahead: only records <= as_of_time are used.
    """
    if ls_df.empty:
        return None

    df = ls_df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts")

    if as_of_time is not None:
        as_of = pd.to_datetime(as_of_time, utc=True)
        df = df[df["ts"] <= as_of]

    if df.empty:
        return None

    # Global account ratio (retail sentiment)
    global_sub = df[df["ratio_type"] == "global_account"]
    if global_sub.empty:
        return None

    retail_long_share = float(global_sub["long_share"].iloc[-1])
    x = retail_long_share - 0.5

    # Retail contrarian score
    sign_x = np.sign(x)
    scaled_mag = clip((abs(x) - 0.06) / 0.14, 0.0, 1.0)
    s = -sign_x * scaled_mag

    # Top trader position ratio
    top_sub = df[df["ratio_type"] == "top_position"]
    top_adj = 0.0

    if not top_sub.empty:
        top_long_share = float(top_sub["long_share"].iloc[-1])
        top_side = top_long_share - 0.5
        # Opposite side check: retail > 0.5 while top < 0.5, or retail < 0.5 while top > 0.5
        if (x * top_side < 0) and (abs(top_side) > 0.05):
            top_adj = 0.2 if top_side > 0 else -0.2

    final_score = clip(s + top_adj, -1.0, 1.0)
    return float(final_score)
