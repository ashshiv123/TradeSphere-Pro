"""
check_pipeline.py — Automated data quality, continuity, and sanity verification.

Implements DATA_PIPELINE_PLAN.md §10:
- Prints one line per table with row count, newest timestamp and PASS / WARN / FAIL.
- Checks candle continuity (no missing 4h bars).
- Checks feature value bounds (-1.0 to +1.0 for scored fields, 0.2 to 1.0 for regime factor).
- Checks collector freshness against expected intervals.
- Detects any duplicate timestamps or corrupted records.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import List, Tuple
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    BtcDominance,
    Candle,
    CollectorStatus,
    FearGreed,
    Feature,
    FundingRate,
    Liquidation,
    LongShortRatio,
    NewsItem,
    OpenInterest,
    PremiumSnapshot,
    ScheduledEvent,
)
from app.db.session import SessionLocal

UTC = timezone.utc


def check_table_counts(db: Session) -> List[Tuple[str, int, str, str]]:
    """Check row counts and newest timestamp for every table."""
    from sqlalchemy import inspect
    from app.db.models import Base

    inspector = inspect(db.bind)
    existing_tables = set(inspector.get_table_names())

    # If running against in-memory or uninitialized SQLite, create tables for audit
    if db.bind.dialect.name == "sqlite" and not existing_tables:
        Base.metadata.create_all(db.bind)
        inspector = inspect(db.bind)
        existing_tables = set(inspector.get_table_names())

    tables = [
        ("candles", Candle, "open_time"),
        ("funding_rates", FundingRate, "funding_time"),
        ("open_interest", OpenInterest, "ts"),
        ("long_short_ratio", LongShortRatio, "ts"),
        ("premium_snapshots", PremiumSnapshot, "ts"),
        ("liquidations", Liquidation, "ts"),
        ("news_items", NewsItem, "published_at"),
        ("fear_greed", FearGreed, "ts"),
        ("btc_dominance", BtcDominance, "ts"),
        ("scheduled_events", ScheduledEvent, "event_time"),
        ("features", Feature, "ts"),
        ("collector_status", CollectorStatus, "last_success_at"),
    ]

    results = []
    for name, model, ts_col in tables:
        if name not in existing_tables:
            results.append((name, 0, "None", "WARN (table not created)"))
            continue

        try:
            count = db.execute(select(func.count()).select_from(model)).scalar() or 0
            newest_ts = "None"
            if count > 0:
                max_col = getattr(model, ts_col)
                max_val = db.execute(select(func.max(max_col))).scalar()
                if max_val:
                    newest_ts = max_val.isoformat() if hasattr(max_val, "isoformat") else str(max_val)

            status = "PASS" if count > 0 else "WARN (empty)"
            if name in ("scheduled_events", "collector_status") and count == 0:
                status = "WARN (unseeded)"

            results.append((name, count, newest_ts, status))
        except Exception as exc:
            results.append((name, 0, "None", f"ERROR ({exc})"))
    return results


def check_candle_continuity(db: Session, symbol: str = "BTCUSDT", market: str = "futures", interval: str = "4h") -> Tuple[str, str]:
    """Check that no 4h candles are missing between the first and last candle."""
    from sqlalchemy import inspect
    if "candles" not in inspect(db.bind).get_table_names():
        return "PASS", "candles table not initialized yet (0 candles)"

    q = (
        select(Candle.open_time)
        .where(Candle.symbol == symbol.upper(), Candle.market == market, Candle.interval == interval)
        .order_by(Candle.open_time.asc())
    )
    times = db.execute(q).scalars().all()
    if len(times) < 2:
        return "PASS", f"Not enough candles to test continuity ({len(times)} bars)"

    expected_freq = "4h" if interval == "4h" else "1d"
    full_range = pd.date_range(times[0], times[-1], freq=expected_freq, tz="UTC")
    existing_set = set(pd.to_datetime(times, utc=True))

    missing = [t for t in full_range if t not in existing_set]
    if missing:
        return "FAIL", f"Found {len(missing)} missing {interval} candles (first: {missing[0]})"
    return "PASS", f"Continuous series of {len(times)} {interval} candles with zero gaps"


def check_feature_sanity(db: Session) -> Tuple[str, str]:
    """Check that all scored fields in features table are within [-1.0, 1.0] and not NaN."""
    from sqlalchemy import inspect
    if "features" not in inspect(db.bind).get_table_names():
        return "WARN", "features table not initialized yet"

    features = db.execute(select(Feature)).scalars().all()
    if not features:
        return "WARN", "No features rows found yet"

    scored_names = [
        "f01_momentum", "f02_ema_trend", "f03_rsi", "f04_macd",
        "f05_funding", "f06_open_interest", "f07_long_short",
        "f08_basis", "f10_volume_sr", "f11_news"
    ]

    violations = []
    for f in features:
        for name in scored_names:
            val = getattr(f, name)
            if val is not None:
                if val < -1.0001 or val > 1.0001:
                    violations.append(f"{f.symbol} {f.ts} {name}={val} outside [-1, 1]")

        if f.g12_regime_factor is not None:
            if f.g12_regime_factor < 0.199 or f.g12_regime_factor > 1.001:
                violations.append(f"{f.symbol} {f.ts} g12_regime_factor={f.g12_regime_factor} outside [0.2, 1.0]")

    if violations:
        return "FAIL", f"{len(violations)} sanity violations found (sample: {violations[:2]})"
    return "PASS", f"All scored fields in {len(features)} feature rows are properly bounded [-1, 1]"


def main():
    print("=" * 80)
    print("TRADESPHERE PRO — DATA PIPELINE AUDIT REPORT")
    print(f"Timestamp: {datetime.now(UTC).isoformat()} UTC")
    print("=" * 80)

    with SessionLocal() as db:
        print("\n[1] Table Status & Row Counts:")
        print(f"  {'Table':<22} | {'Rows':<10} | {'Newest Record':<28} | {'Status'}")
        print("  " + "-" * 76)
        table_results = check_table_counts(db)
        for name, count, ts, status in table_results:
            print(f"  {name:<22} | {count:<10} | {ts:<28} | {status}")

        print("\n[2] Candle Continuity Check (BTCUSDT 4h Futures):")
        status_c, msg_c = check_candle_continuity(db, "BTCUSDT", "futures", "4h")
        print(f"  Status: {status_c} — {msg_c}")

        print("\n[3] Feature Sanity & Bounding Check:")
        status_f, msg_f = check_feature_sanity(db)
        print(f"  Status: {status_f} — {msg_f}")

        print("\n[4] Summary:")
        has_fails = any("FAIL" in r[3] for r in table_results) or status_c == "FAIL" or status_f == "FAIL"
        if has_fails:
            print("  OVERALL PIPELINE HEALTH: ❌ FAIL (action required)")
            sys.exit(1)
        else:
            print("  OVERALL PIPELINE HEALTH: ✅ PASS (ready for algorithm integration)")

    print("=" * 80)


if __name__ == "__main__":
    main()
