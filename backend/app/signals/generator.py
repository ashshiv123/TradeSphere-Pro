"""
generator.py - Generates, scores, and persists signals and trade plans (Stage 14).
Runs automatically after 4h feature computation, or on demand via API / CLI.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Feature
from app.db.models_trading import Signal, TradePlan
from app.db.session import SessionLocal
from app.llm.explain import explain_signal
from app.risk.engine import check_and_create_trade_plan, load_risk_config
from app.schemas.feature_vector import FeatureVector
from app.scoring.engine import load_scoring_config, score_feature_vector

logger = logging.getLogger(__name__)


def compute_config_version() -> str:
    """Computes a deterministic hash of scoring_config.yaml + risk.yaml."""
    scoring_path = Path(__file__).parent.parent / "scoring" / "scoring_config.yaml"
    risk_path = Path(__file__).parent.parent / "risk" / "risk.yaml"

    hasher = hashlib.sha256()
    if scoring_path.exists():
        hasher.update(scoring_path.read_bytes())
    if risk_path.exists():
        hasher.update(risk_path.read_bytes())
    return hasher.hexdigest()[:12]


def process_features_into_signals(
    symbols: Optional[List[str]] = None,
    interval: str = "4h",
    session: Optional[Session] = None,
    auto_explain: bool = True,
) -> List[Signal]:
    """
    Reads the latest Feature for each symbol, scores it, writes a Signal row (idempotent),
    and if LONG/SHORT, checks risk to propose a TradePlan.
    """
    own_session = False
    if session is None:
        own_session = True
        session = SessionLocal()

    settings = get_settings()
    target_symbols = symbols or settings.symbol_list
    cfg_version = compute_config_version()
    signals_created: List[Signal] = []

    try:
        for sym in target_symbols:
            # Fetch latest Feature row
            stmt = (
                select(Feature)
                .where(Feature.symbol == sym, Feature.interval == interval)
                .order_by(desc(Feature.ts))
                .limit(1)
            )
            feat = session.scalars(stmt).first()
            if not feat:
                logger.warning("No feature row found for %s %s", sym, interval)
                continue

            # Convert to FeatureVector
            fv_dict = {
                "symbol": feat.symbol,
                "interval": feat.interval,
                "ts": feat.ts,
                "f01_momentum": feat.f01_momentum,
                "f02_ema_trend": feat.f02_ema_trend,
                "f03_rsi": feat.f03_rsi,
                "f04_macd": feat.f04_macd,
                "f05_funding": feat.f05_funding,
                "f06_open_interest": feat.f06_open_interest,
                "f07_long_short": feat.f07_long_short,
                "f08_basis": feat.f08_basis,
                "f10_volume_sr": feat.f10_volume_sr,
                "f11_news": feat.f11_news,
                "g09_liq_above_price": feat.g09_liq_above_price,
                "g09_liq_above_notional": feat.g09_liq_above_notional,
                "g09_liq_below_price": feat.g09_liq_below_price,
                "g09_liq_below_notional": feat.g09_liq_below_notional,
                "g09_source": feat.g09_source,
                "g12_regime_factor": feat.g12_regime_factor,
                "g13_btc_corr": feat.g13_btc_corr,
                "g13_btc_beta": feat.g13_btc_beta,
                "g13_btc_trend": feat.g13_btc_trend,
                "g13_btc_dominance": feat.g13_btc_dominance,
                "volume_ratio": feat.volume_ratio,
                "atr": feat.atr,
                "close": feat.close,
                "news_pause": feat.news_pause,
                "missing": feat.missing or [],
                "computed_at": feat.computed_at,
            }
            fv = FeatureVector(**fv_dict)

            # Score
            res = score_feature_vector(fv, mode="full")
            res["config_version"] = cfg_version

            # Check existing signal by unique constraint
            existing = session.scalars(
                select(Signal).where(
                    Signal.symbol == sym,
                    Signal.interval == interval,
                    Signal.ts == fv.ts,
                )
            ).first()

            if existing:
                # Update existing signal fields
                for k, v in res.items():
                    if hasattr(existing, k) and k not in ("id", "created_at"):
                        setattr(existing, k, v)
                sig = existing
            else:
                sig = Signal(**res)
                session.add(sig)

            session.commit()
            session.refresh(sig)
            signals_created.append(sig)

            # If actionable signal (LONG/SHORT), run Risk Layer to generate TradePlan
            if sig.direction in ("LONG", "SHORT"):
                plan = check_and_create_trade_plan(sig, session)
                if plan:
                    logger.info("TradePlan id=%s proposed for signal %s %s", plan.id, sig.symbol, sig.direction)

            # Generate LLM explanation if requested
            if auto_explain:
                try:
                    explain_signal(sig.id, session=session)
                except Exception as exc:
                    logger.warning("Auto explain failed for signal %s: %s", sig.id, exc)

        return signals_created

    finally:
        if own_session:
            session.expunge_all()
            session.close()
