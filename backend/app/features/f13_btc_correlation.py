"""
f13_btc_correlation.py — Feature 13: BTC Correlation, Beta, Trend and Dominance.

Plan formula (§8):
  4h log returns over the last 180 candles (30 days) for coin and BTCUSDT:
    ret_coin = ln(close / close_prev)
    ret_btc  = ln(btc_close / btc_close_prev)
  g13_btc_corr = correlation(ret_coin, ret_btc) over 180 candles
  g13_btc_beta = cov(ret_coin, ret_btc) / var(ret_btc) over 180 candles
  g13_btc_trend = sign of (BTC ema21 - BTC ema55) (+1, -1, or 0 if tiny gap)
  g13_btc_dominance = latest btc_dominance at or before candle close
  For BTCUSDT itself: corr = 1.0, beta = 1.0
"""
from __future__ import annotations

from typing import Optional, Tuple
import numpy as np
import pandas as pd

from app.features.common import atr, clip, ema


def compute_f13_series(
    coin_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    symbol: str = "ETHUSDT",
    window: int = 180,
    latest_dominance: Optional[float] = None,
) -> pd.DataFrame:
    """
    Compute BTC correlation, beta, trend, and dominance for each candle.
    Returns DataFrame with columns:
      ['g13_btc_corr', 'g13_btc_beta', 'g13_btc_trend', 'g13_btc_dominance']
    """
    coin_c = coin_df["close"].astype(float)
    btc_c = btc_df["close"].astype(float)

    # BTC Trend: EMA21 vs EMA55 on BTC
    btc_ema21 = ema(btc_c, 21)
    btc_ema55 = ema(btc_c, 55)
    btc_atr14 = atr(btc_df, 14)
    btc_gap = btc_ema21 - btc_ema55

    # Small gap threshold: 0.001 * ATR
    tiny_threshold = 0.001 * btc_atr14.replace(0, np.nan)
    btc_trend = pd.Series(0, index=btc_df.index, dtype=int)
    btc_trend[btc_gap > tiny_threshold] = 1
    btc_trend[btc_gap < -tiny_threshold] = -1

    if symbol.upper() == "BTCUSDT":
        corr = pd.Series(1.0, index=coin_df.index)
        beta = pd.Series(1.0, index=coin_df.index)
    else:
        # 4h log returns
        ret_coin = np.log(coin_c / coin_c.shift(1))
        ret_btc = np.log(btc_c / btc_c.shift(1))

        # Rolling covariance and variance over 180 candles
        roll_cov = ret_coin.rolling(window, min_periods=30).cov(ret_btc)
        roll_var = ret_btc.rolling(window, min_periods=30).var()
        roll_std_coin = ret_coin.rolling(window, min_periods=30).std()
        roll_std_btc = ret_btc.rolling(window, min_periods=30).std()

        corr = roll_cov / (roll_std_coin * roll_std_btc).replace(0, np.nan)
        beta = roll_cov / roll_var.replace(0, np.nan)

        corr = clip(corr.fillna(1.0), -1.0, 1.0)
        beta = clip(beta.fillna(1.0), -5.0, 5.0)

    dom = pd.Series(latest_dominance, index=coin_df.index, dtype=float)

    out = pd.DataFrame(
        {
            "g13_btc_corr": corr,
            "g13_btc_beta": beta,
            "g13_btc_trend": btc_trend,
            "g13_btc_dominance": dom,
        },
        index=coin_df.index,
    )
    return out


def compute_f13_latest(
    coin_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    symbol: str = "ETHUSDT",
    window: int = 180,
    latest_dominance: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], Optional[int], Optional[float]]:
    """Compute (corr, beta, trend, dominance) for the newest candle."""
    if len(coin_df) < 30 or len(btc_df) < 30:
        return None, None, None, latest_dominance

    res = compute_f13_series(
        coin_df, btc_df, symbol=symbol, window=window, latest_dominance=latest_dominance
    )
    row = res.iloc[-1]
    return (
        None if pd.isna(row["g13_btc_corr"]) else float(row["g13_btc_corr"]),
        None if pd.isna(row["g13_btc_beta"]) else float(row["g13_btc_beta"]),
        None if pd.isna(row["g13_btc_trend"]) else int(row["g13_btc_trend"]),
        latest_dominance,
    )

