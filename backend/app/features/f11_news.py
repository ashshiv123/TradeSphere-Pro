"""
f11_news.py — Feature 11: News and Event Sentiment & News Pause Gate.

Plan formula (§8 + DEV-001):
  Take news for the coin and market-wide news in the last 24h before candle close.
  Per item:
    item_score = vader_compound
    weight = exp(-age_hours / 12) * source_credibility (Messari = 1.3, other = 1.0)
    if votes_important >= 3: weight *= 1.5
    news_score = sum(w * item) / sum(w)
  fg = (fear_greed - 50) / 50
  score = clip(0.8 * news_score + 0.2 * fg, -1, 1)

  news_pause = TRUE if candle close_time is inside [event_time - 30min, event_time + 60min]
  for any scheduled_event with impact = 'high'.
"""
from __future__ import annotations

from typing import Optional, Tuple
import numpy as np
import pandas as pd

from app.features.common import clip


def compute_f11_latest(
    news_df: pd.DataFrame,
    fear_greed_val: Optional[int],
    events_df: pd.DataFrame,
    coin: str = "BTC",
    candle_close_time: Optional[pd.Timestamp] = None,
) -> Tuple[Optional[float], bool, bool]:
    """
    Compute (f11_score, news_pause, is_news_missing).
    Guarantees NO lookahead: only news published <= candle_close_time are evaluated.
    """
    if candle_close_time is None:
        candle_close = pd.Timestamp.now(tz="UTC")
    else:
        candle_close = pd.to_datetime(candle_close_time, utc=True)

    # 1. News Pause Check
    news_pause = False
    if not events_df.empty:
        ev = events_df.copy()
        ev["event_time"] = pd.to_datetime(ev["event_time"], utc=True)
        high_impact = ev[ev["impact"].str.lower() == "high"]
        for _, row in high_impact.iterrows():
            t_event = row["event_time"]
            window_start = t_event - pd.Timedelta(minutes=30)
            window_end = t_event + pd.Timedelta(minutes=60)
            if window_start <= candle_close <= window_end:
                news_pause = True
                break

    # 2. Filter news in the last 24 hours prior to candle close
    is_missing = True
    news_score = 0.0

    if not news_df.empty:
        n_df = news_df.copy()
        n_df["published_at"] = pd.to_datetime(n_df["published_at"], utc=True)

        t_24h_ago = candle_close - pd.Timedelta(hours=24)
        coin_upper = coin.upper().replace("USDT", "")

        # Coin specific OR market-wide (currency is NULL or 'ALL' or empty)
        sub = n_df[
            (n_df["published_at"] >= t_24h_ago)
            & (n_df["published_at"] <= candle_close)
            & (
                n_df["currency"].isna()
                | (n_df["currency"] == "")
                | (n_df["currency"].str.upper() == coin_upper)
            )
        ]

        if not sub.empty:
            weights = []
            scores = []
            for _, item in sub.iterrows():
                # VADER compound score
                vader = float(item.get("vader_compound") or 0.0)

                # Source weight
                src = str(item.get("source") or "").lower()
                src_weight = 1.3 if "messari" in src else 1.0

                # Age decay
                age_hours = (candle_close - item["published_at"]).total_seconds() / 3600.0
                w = np.exp(-age_hours / 12.0) * src_weight

                # Important votes booster
                votes_imp = item.get("votes_important")
                if votes_imp and int(votes_imp) >= 3:
                    w *= 1.5

                weights.append(w)
                scores.append(vader)

            total_w = sum(weights)
            if total_w > 0:
                news_score = float(np.sum(np.array(weights) * np.array(scores)) / total_w)
                is_missing = False

    # 3. Fear & Greed (-1..+1)
    if fear_greed_val is not None:
        fg = (float(fear_greed_val) - 50.0) / 50.0
    else:
        fg = 0.0

    # 4. Final blended score
    if not is_missing:
        score = clip(0.8 * news_score + 0.2 * fg, -1.0, 1.0)
    else:
        # News missing: fall back to Fear & Greed sentiment
        score = clip(fg, -1.0, 1.0) if fear_greed_val is not None else 0.0

    return float(score), news_pause, is_missing

