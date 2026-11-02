"""
audit_history.py — Audit history completeness and compute monthly NULL share per field.

DATA_PIPELINE_PLAN.md & DECISION_LAYER_PLAN.md Stage 11:
- Show row counts and first/last ts per symbol
- Show share of NULL per field per month
- Highlight where derivatives data (F6, F7) is thin due to exchange API limits (~30 days).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Candle, Feature
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

SCORED_FIELDS = [
    "f01_momentum",
    "f02_ema_trend",
    "f03_rsi",
    "f04_macd",
    "f05_funding",
    "f06_open_interest",
    "f07_long_short",
    "f08_basis",
    "f10_volume_sr",
    "f11_news",
]

GATE_FIELDS = [
    "g09_liq_above_price",
    "g12_regime_factor",
    "g13_btc_corr",
]


def audit_feature_table(db: Session, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    results = {}
    for sym in symbols:
        rows = db.execute(
            select(Feature)
            .where(Feature.symbol == sym.upper(), Feature.interval == "4h")
            .order_by(Feature.ts.asc())
        ).scalars().all()

        if not rows:
            print(f"[{sym}] No feature records found in database.")
            continue

        data = []
        for r in rows:
            rec = {
                "ts": r.ts,
                "month": r.ts.strftime("%Y-%m"),
            }
            for f in SCORED_FIELDS + GATE_FIELDS:
                val = getattr(r, f, None)
                rec[f] = 1 if val is None else 0  # 1 indicates NULL
            data.append(rec)

        df = pd.DataFrame(data)
        first_ts = df["ts"].min()
        last_ts = df["ts"].max()
        total_rows = len(df)

        print("=" * 80)
        print(f"SYMBOL: {sym} — Total Records: {total_rows} | Span: {first_ts} -> {last_ts}")
        print("=" * 80)

        # Group by month and calculate NULL percentage
        grouped = df.groupby("month")
        monthly_counts = grouped.size()
        null_share = grouped[SCORED_FIELDS + GATE_FIELDS].mean() * 100.0
        null_share.insert(0, "bars", monthly_counts)

        pd.set_option("display.max_columns", 15)
        pd.set_option("display.width", 120)
        pd.set_option("display.float_format", "{:.1f}%".format)
        print("Monthly NULL Share per Field (%):")
        print(null_share)
        print("\n")
        results[sym] = null_share

    return results


def main():
    with SessionLocal() as db:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        audit_feature_table(db, symbols)


if __name__ == "__main__":
    main()
