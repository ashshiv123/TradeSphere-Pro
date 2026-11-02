"""
print_candle_tv.py — Print candle OHLCV, EMA21, EMA55, and RSI(14) for TradingView comparison.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd

from app.features.f02_ema_trend import compute_f02_latest
from app.features.f03_rsi import compute_f03_latest
from scripts.verify_f02_f03 import fetch_real_candles, independent_ema_trend, independent_rsi


def main():
    # Fetch 300 4h candles so EMAs have plenty of warm-up
    df = fetch_real_candles("BTCUSDT", "4h", limit=300)
    # The last candle in live Binance feed is usually open/incomplete; take the last closed candle
    closed_df = df.iloc[:-1].copy()

    last_c = closed_df.iloc[-1]
    open_dt = datetime.fromtimestamp(last_c["open_time"] / 1000.0, tz=timezone.utc)
    close_dt = datetime.fromtimestamp(last_c["close_time"] / 1000.0, tz=timezone.utc)

    ema_res = independent_ema_trend(closed_df)
    rsi_res = independent_rsi(closed_df)

    f02_score = compute_f02_latest(closed_df)
    f03_score = compute_f03_latest(closed_df)

    print("=" * 70)
    print("TRADINGVIEW COMPARISON REFERENCE: BTCUSDT (Binance Futures 4h)")
    print("=" * 70)
    print(f"Candle Open  (UTC): {open_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Candle Close (UTC): {close_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Open:               {last_c['open']:,.2f}")
    print(f"High:               {last_c['high']:,.2f}")
    print(f"Low:                {last_c['low']:,.2f}")
    print(f"Close:              {last_c['close']:,.2f}")
    print(f"Volume:             {last_c['volume']:,.3f}")
    print("-" * 70)
    print(f"EMA(21):            {ema_res['ema21']:,.2f}")
    print(f"EMA(55):            {ema_res['ema55']:,.2f}")
    print(f"RSI(14):            {rsi_res['rsi']:.2f}")
    print(f"ATR(14):            {ema_res['atr14']:,.2f}")
    print("-" * 70)
    print(f"Pipeline F02 (EMA Trend Score): {f02_score:+.6f}")
    print(f"Pipeline F03 (RSI Base Score):  {f03_score:+.6f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
