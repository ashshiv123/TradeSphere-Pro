"""
messari.py — Messari news API client and sentiment parser.

DEV-001 (DATA_PIPELINE_PLAN.md):
CryptoPanic was replaced by Messari API due to CryptoPanic dropping free API access.
Messari /v1/news provides professional, coin-tagged headlines.
We score headlines using VADER sentiment on the title text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.clients.http import ResilientHttpClient
from app.config import get_settings

_vader_analyzer = SentimentIntensityAnalyzer()


class ParsedNewsItem(BaseModel):
    source: str = "messari"
    external_id: str
    currency: Optional[str] = None
    title: str
    url: Optional[str] = None
    published_at: datetime
    votes_positive: Optional[int] = None
    votes_negative: Optional[int] = None
    votes_important: Optional[int] = None
    vader_compound: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


def parse_messari_news(raw_data: Dict[str, Any], coin_ticker: Optional[str] = None) -> List[ParsedNewsItem]:
    """Parse Messari /v1/news items, computing VADER compound sentiment on each title."""
    items = raw_data.get("data", [])
    results = []

    for item in items:
        ext_id = str(item.get("id") or item.get("slug") or "")
        title = item.get("title") or ""
        if not title or not ext_id:
            continue

        pub_str = item.get("published_at")
        if pub_str:
            try:
                # ISO timestamp: 2026-03-15T12:00:00Z
                dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        # Calculate VADER compound score [-1.0, 1.0]
        vader_res = _vader_analyzer.polarity_scores(title)
        compound = float(vader_res.get("compound", 0.0))

        # Extract coin currency tag if available
        tags = item.get("tags") or []
        currency = coin_ticker.upper() if coin_ticker else None
        if not currency and tags:
            currency = tags[0].upper()

        rec = ParsedNewsItem(
            source="messari",
            external_id=ext_id,
            currency=currency,
            title=title,
            url=item.get("url"),
            published_at=dt,
            votes_positive=None,
            votes_negative=None,
            votes_important=None,
            vader_compound=compound,
            raw=item,
        )
        results.append(rec)

    return results


class MessariClient:
    URL = "https://data.messari.io/api/v1/news"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.messari_api_key
        self.http = ResilientHttpClient()

    def close(self):
        self.http.close()

    def get_news(self, coin_slug: Optional[str] = None, coin_ticker: Optional[str] = None, limit: int = 20) -> List[ParsedNewsItem]:
        headers = {}
        if self.api_key:
            headers["x-messari-api-key"] = self.api_key

        url = f"{self.URL}/{coin_slug}" if coin_slug else self.URL
        resp = self.http.get(url, params={"limit": limit}, headers=headers)
        return parse_messari_news(resp.json(), coin_ticker=coin_ticker)

