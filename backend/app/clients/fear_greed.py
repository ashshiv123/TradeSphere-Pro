"""
fear_greed.py — Alternative.me Fear & Greed Index client and parser.

DATA_PIPELINE_PLAN.md §5:
GET https://api.alternative.me/fng/?limit=0
DEV-007: value and timestamp are strings, parsed to int.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from app.clients.http import ResilientHttpClient


class ParsedFearGreed(BaseModel):
    ts: datetime
    value: int
    classification: Optional[str] = None


def parse_fear_greed(raw_data: Dict[str, Any]) -> List[ParsedFearGreed]:
    """Parse Alternative.me Fear & Greed JSON payload."""
    results = []
    items = raw_data.get("data", [])
    for item in items:
        # DEV-007: timestamp and value are strings
        ts_sec = int(item["timestamp"])
        val = int(item["value"])
        dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
        results.append(
            ParsedFearGreed(
                ts=dt,
                value=val,
                classification=item.get("value_classification"),
            )
        )
    return results


class FearGreedClient:
    URL = "https://api.alternative.me/fng/"

    def __init__(self):
        self.http = ResilientHttpClient()

    def close(self):
        self.http.close()

    def get_latest(self, limit: int = 10) -> List[ParsedFearGreed]:
        resp = self.http.get(self.URL, params={"limit": limit})
        return parse_fear_greed(resp.json())
