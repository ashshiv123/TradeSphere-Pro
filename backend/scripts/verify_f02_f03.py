"""
verify_f02_f03.py — Independent verification of F2 (EMA Trend) and F3 (RSI) against separate reference calculation.
"""
from __future__ import annotations

import httpx
import numpy as np
import pandas as pd

from app.features.f02_ema_trend import compute_f02_latest
from app.features.f03_rsi import compute_f03_latest, compute_rsi_base


def fetch_real_candles(symbol: str = "BTCUSDT", interval: str = "4h", limit: int = 100) -> pd.DataFrame:
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = httpx.get(url, timeout=10)
    data = r.json()
    # [0]=open_time [1]=open [2]=high [3]=low [4]=close [5]=volume
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def independent_ema_trend(df: pd.DataFrame) -> dict:
    close = df["close"].values
    # Independent manual EMA calculation
    def calc_ema(arr, span):
        alpha = 2.0 / (span + 1.0)
        ema_arr = np.zeros_like(arr)
        ema_arr[0] = arr[0]
        for t in range(1, len(arr)):
            ema_arr[t] = alpha * arr[t] + (1 - alpha) * ema_arr[t - 1]
        return ema_arr

    ema21 = calc_ema(close, 21)
    ema55 = calc_ema(close, 55)

    # Independent True Range and Wilder ATR
    high = df["high"].values
    low = df["low"].values
    tr = np.zeros_like(close)
    tr[0] = high[0] - low[0]
    for t in range(1, len(close)):
        tr[t] = max(high[t] - low[t], abs(high[t] - close[t - 1]), abs(low[t] - close[t - 1]))

    alpha_atr = 1.0 / 14.0
    atr14 = np.zeros_like(tr)
    atr14[0] = tr[0]
    for t in range(1, len(tr)):
        atr14[t] = alpha_atr * tr[t] + (1 - alpha_atr) * atr14[t - 1]

    gap = (ema21[-1] - ema55[-1]) / atr14[-1]
    raw_score = max(-1.0, min(1.0, gap / 2.0))
    slope3 = ema21[-1] - ema21[-4]

    sign_gap = np.sign(gap)
    sign_slope = np.sign(slope3)
    disagree = (sign_gap != sign_slope)
    final_score = raw_score * 0.5 if disagree else raw_score

    return {
        "ema21": ema21[-1],
        "ema55": ema55[-1],
        "atr14": atr14[-1],
        "gap": gap,
        "score": final_score,
    }


def independent_rsi(df: pd.DataFrame) -> dict:
    close = df["close"].values
    diffs = np.diff(close)
    gains = np.maximum(diffs, 0)
    losses = np.maximum(-diffs, 0)

    alpha = 1.0 / 14.0
    avg_gain = gains[0]
    avg_loss = losses[0]
    for i in range(1, len(diffs)):
        avg_gain = alpha * gains[i] + (1 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1 - alpha) * avg_loss

    rs = avg_gain / (avg_loss if avg_loss != 0 else 1e-10)
    rsi_val = 100.0 - (100.0 / (1.0 + rs))

    # Base score
    if 30 <= rsi_val <= 70:
        base = (rsi_val - 50.0) / 50.0
    elif rsi_val > 70:
        base = 0.4 - (rsi_val - 70.0) / 30.0
    else:
        base = -0.4 + (30.0 - rsi_val) / 30.0

    return {"rsi": rsi_val, "base": base}


def run_verification():
    df = fetch_real_candles("BTCUSDT", "4h", 100)
    f02_pipeline = compute_f02_latest(df)
    f02_indep = independent_ema_trend(df)

    f03_pipeline = compute_f03_latest(df)
    f03_indep = independent_rsi(df)

    print("=" * 65)
    print("INDEPENDENT VERIFICATION FOR BTCUSDT (4h Real Data)")
    print("=" * 65)
    print(f"F2 (EMA Trend):")
    print(f"  Pipeline Output:    {f02_pipeline:.6f}")
    print(f"  Independent Calc:   {f02_indep['score']:.6f}")
    print(f"  EMA21:              {f02_indep['ema21']:.2f}")
    print(f"  EMA55:              {f02_indep['ema55']:.2f}")
    print(f"  ATR14:              {f02_indep['atr14']:.2f}")
    diff_f02 = abs(f02_pipeline - f02_indep["score"])
    print(f"  Difference:         {diff_f02:.8f} (tolerance: < 1e-4) -> {'PASS' if diff_f02 < 1e-4 else 'FAIL'}")

    print("\nF3 (RSI with base mapping):")
    print(f"  Pipeline Output:    {f03_pipeline:.6f}")
    print(f"  Independent Base:   {f03_indep['base']:.6f}")
    print(f"  Raw RSI(14):        {f03_indep['rsi']:.2f}")
    diff_f03 = abs(f03_pipeline - f03_indep["base"])
    print(f"  Difference:         {diff_f03:.8f} (tolerance: < 0.35) -> {'PASS' if diff_f03 < 0.35 else 'FAIL'}")
    print("=" * 65)


if __name__ == "__main__":
    run_verification()

