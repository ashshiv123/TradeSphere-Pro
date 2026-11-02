"""
feature_vector.py — Pydantic schema contract for the feature engine.

The scoring engine, backtester, and API read through this contract (§9).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FeatureVector(BaseModel):
    symbol: str
    interval: str = "4h"
    ts: datetime

    # 10 Scored Fields (-1.0 to +1.0)
    f01_momentum: Optional[float] = None
    f02_ema_trend: Optional[float] = None
    f03_rsi: Optional[float] = None
    f04_macd: Optional[float] = None
    f05_funding: Optional[float] = None
    f06_open_interest: Optional[float] = None
    f07_long_short: Optional[float] = None
    f08_basis: Optional[float] = None
    f10_volume_sr: Optional[float] = None
    f11_news: Optional[float] = None

    # Gate Fields (multipliers and filters, not in weighted sum)
    g09_liq_above_price: Optional[float] = None
    g09_liq_above_notional: Optional[float] = None
    g09_liq_below_price: Optional[float] = None
    g09_liq_below_notional: Optional[float] = None
    g09_source: Optional[str] = None  # 'liquidation_clusters' | 'swing_proxy'

    g12_regime_factor: Optional[float] = None  # 0.2 to 1.0
    g13_btc_corr: Optional[float] = None
    g13_btc_beta: Optional[float] = None
    g13_btc_trend: Optional[int] = None  # +1 / -1 / 0
    g13_btc_dominance: Optional[float] = None

    # Context & Confirmation gates
    volume_ratio: Optional[float] = None  # >= 1.2 confirmation gate
    atr: Optional[float] = None
    close: Optional[float] = None
    news_pause: bool = False

    raw: Optional[Dict[str, Any]] = None
    missing: Optional[List[str]] = Field(default_factory=list)
    computed_at: Optional[datetime] = None

    def scored_fields(self) -> Dict[str, Optional[float]]:
        """Return dictionary of the 10 scored fields."""
        return {
            "f01_momentum": self.f01_momentum,
            "f02_ema_trend": self.f02_ema_trend,
            "f03_rsi": self.f03_rsi,
            "f04_macd": self.f04_macd,
            "f05_funding": self.f05_funding,
            "f06_open_interest": self.f06_open_interest,
            "f07_long_short": self.f07_long_short,
            "f08_basis": self.f08_basis,
            "f10_volume_sr": self.f10_volume_sr,
            "f11_news": self.f11_news,
        }

    def gates(self) -> Dict[str, Any]:
        """Return dictionary of gate fields and confirmation filters."""
        return {
            "g09_liq_above_price": self.g09_liq_above_price,
            "g09_liq_above_notional": self.g09_liq_above_notional,
            "g09_liq_below_price": self.g09_liq_below_price,
            "g09_liq_below_notional": self.g09_liq_below_notional,
            "g09_source": self.g09_source,
            "g12_regime_factor": self.g12_regime_factor,
            "g13_btc_corr": self.g13_btc_corr,
            "g13_btc_beta": self.g13_btc_beta,
            "g13_btc_trend": self.g13_btc_trend,
            "g13_btc_dominance": self.g13_btc_dominance,
            "volume_ratio": self.volume_ratio,
            "news_pause": self.news_pause,
        }
