"""
ws_handler.py — Processes live Binance Futures WebSocket messages for markPrice and forceOrder.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy.orm import Session

from app.db.models import Liquidation, PremiumSnapshot
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)

# To prevent flooding premium_snapshots (1 per sec per symbol), downsample to at most 1 per minute per symbol in memory
_last_premium_ts: Dict[str, float] = {}


def handle_ws_message(db: Session, msg: Dict[str, Any]):
    """Route incoming Binance combined stream message to appropriate table."""
    data = msg.get("data")
    if not isinstance(data, dict):
        return

    event_type = data.get("e")

    # 1. Mark Price update
    if event_type == "markPriceUpdate":
        symbol = data.get("s")
        event_time_ms = data.get("E")
        if not symbol or not event_time_ms:
            return

        # Throttle to 1 snapshot every 60 seconds per symbol
        now_sec = event_time_ms / 1000.0
        if now_sec - _last_premium_ts.get(symbol, 0.0) < 55.0:
            return

        _last_premium_ts[symbol] = now_sec
        ts = datetime.fromtimestamp(now_sec, tz=timezone.utc)

        mark_p = float(data.get("p", 0))
        index_p = float(data.get("i", 0)) if data.get("i") else None
        funding_r = float(data.get("r", 0)) if data.get("r") else None
        next_ft_ms = data.get("T")
        next_ft = datetime.fromtimestamp(next_ft_ms / 1000.0, tz=timezone.utc) if next_ft_ms else None

        row = {
            "symbol": symbol.upper(),
            "ts": ts,
            "mark_price": mark_p,
            "index_price": index_p,
            "funding_rate": funding_r,
            "next_funding_time": next_ft,
        }
        try:
            upsert_rows(db, PremiumSnapshot, [row], conflict_cols=["symbol", "ts"])
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Error saving premium snapshot for %s: %s", symbol, exc)

    # 2. Forced liquidation order
    elif event_type == "forceOrder":
        order = data.get("o", {})
        symbol = order.get("s")
        side = order.get("S")
        ts_ms = order.get("T") or data.get("E")
        price = float(order.get("p", 0))
        qty = float(order.get("q", 0))
        avg_price = float(order.get("ap", price)) if order.get("ap") else price
        notional = price * qty

        if not symbol or not side or not ts_ms:
            return

        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        row = {
            "symbol": symbol.upper(),
            "ts": ts,
            "side": side.upper(),
            "price": price,
            "avg_price": avg_price,
            "quantity": qty,
            "notional": notional,
        }
        try:
            upsert_rows(
                db,
                Liquidation,
                [row],
                conflict_cols=["symbol", "ts", "side", "price", "quantity"],
            )
            db.commit()
            logger.info("Recorded %s liquidation for %s: %.4f @ %.2f", side, symbol, qty, price)
        except Exception as exc:
            db.rollback()
            logger.warning("Error saving liquidation for %s: %s", symbol, exc)
