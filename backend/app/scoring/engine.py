"""
engine.py - Pure-function Scoring Engine for TradeSphere Pro (Section 3).

Computes directional signal (LONG / SHORT / HOLD), composite score,
confidence, contributions breakdown, SL/TP levels, and sizing multiplier.
Supports both 'full' mode (live/recent) and 'reduced' mode (backtesting long history).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml

from app.schemas.feature_vector import FeatureVector

CONFIG_PATH = Path(__file__).parent / "scoring_config.yaml"


def load_scoring_config() -> Dict[str, Any]:
    """Load scoring config YAML."""
    if not CONFIG_PATH.exists():
        # Fallback defaults
        return {
            "config_version": "v1.0",
            "weights": {
                "f01_momentum": 12,
                "f02_ema_trend": 12,
                "f03_rsi": 10,
                "f04_macd": 10,
                "f05_funding": 9,
                "f06_open_interest": 9,
                "f07_long_short": 8,
                "f08_basis": 8,
                "f10_volume_sr": 12,
                "f11_news": 10,
            },
            "thresholds": {
                "long_threshold": 0.35,
                "short_threshold": -0.35,
                "min_confidence": 0.40,
                "max_missing_full_mode": 2,
                "volume_ratio_gate": 1.2,
                "volume_gate_enabled": True,
                "sl_atr_multiplier": 1.5,
                "sl_cluster_buffer_atr": 0.25,
                "max_sl_atr_multiplier": 3.0,
                "reward_to_risk": 2.0,
                "time_stop_candles": 12,
            },
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clip(val: float, low: float, high: float) -> float:
    return max(low, min(val, high))


def score_feature_vector(
    fv: FeatureVector,
    mode: str = "full",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Score a single FeatureVector. Pure function without database calls.

    Returns dict matching Signal attributes:
      direction: 'LONG' | 'SHORT' | 'HOLD'
      hold_reason: str or None
      composite_score: float
      regime_factor: float
      corr_factor: float
      confidence: float
      entry_price: float
      stop_loss: float
      take_profit: float
      sl_distance_atr: float
      rr: float
      size_multiplier: float
      contributions: dict
      features_snapshot: dict
      config_version: str
    """
    cfg = config or load_scoring_config()
    weights: Dict[str, float] = cfg.get("weights", {})
    thresholds: Dict[str, Any] = cfg.get("thresholds", {})
    config_ver: str = cfg.get("config_version", "v1.0")

    scored = fv.scored_fields()
    null_fields = [k for k, v in scored.items() if v is None]

    # Mode Handling:
    # In full mode, if more than max_missing_full_mode (2) fields are NULL -> HOLD
    if mode == "full" and len(null_fields) > thresholds.get("max_missing_full_mode", 2):
        return {
            "symbol": fv.symbol,
            "interval": fv.interval,
            "ts": fv.ts,
            "direction": "HOLD",
            "hold_reason": "missing_fields",
            "composite_score": 0.0,
            "regime_factor": fv.g12_regime_factor or 1.0,
            "corr_factor": 1.0,
            "confidence": 0.0,
            "entry_price": fv.close,
            "stop_loss": None,
            "take_profit": None,
            "sl_distance_atr": None,
            "rr": None,
            "size_multiplier": 0.0,
            "contributions": {},
            "features_snapshot": fv.model_dump(mode="json"),
            "config_version": config_ver,
        }

    # Weight Calculation
    active_weights: Dict[str, float] = {}
    if mode == "reduced":
        # Renormalize remaining non-null weights to 100%
        avail = {k: weights[k] for k, v in scored.items() if v is not None and k in weights}
        total_w = sum(avail.values())
        if total_w > 0:
            active_weights = {k: (w / total_w) * 100.0 for k, w in avail.items()}
    else:
        active_weights = {k: float(w) for k, w in weights.items()}

    contributions: Dict[str, Any] = {}
    cs = 0.0
    for field, wt in active_weights.items():
        val = scored.get(field)
        sc = float(val) if val is not None else 0.0
        weighted_contrib = (wt / 100.0) * sc
        cs += weighted_contrib
        contributions[field] = {
            "weight": round(wt, 4),
            "score": round(sc, 4) if val is not None else None,
            "contribution": round(weighted_contrib, 4),
        }

    cs = round(clip(cs, -1.0, 1.0), 4)

    # Gate 2: news pause
    if fv.news_pause:
        return _make_hold(fv, cs, "news_pause", contributions, config_ver)

    # Gate 3: Direction threshold
    long_thresh = thresholds.get("long_threshold", 0.35)
    short_thresh = thresholds.get("short_threshold", -0.35)

    tentative_direction = "HOLD"
    if cs >= long_thresh:
        tentative_direction = "LONG"
    elif cs <= short_thresh:
        tentative_direction = "SHORT"
    else:
        return _make_hold(fv, cs, "below_threshold", contributions, config_ver)

    # Regime & Correlation factors
    regime_factor = clip(float(fv.g12_regime_factor or 1.0), 0.2, 1.0)

    # Correlation factor:
    # corr_factor = 1.0 - 0.5 * clip((corr - 0.7) / 0.3, 0, 1) if corr >= 0.7 and opposing btc trend
    corr_factor = 1.0
    if fv.symbol != "BTCUSDT":
        corr = fv.g13_btc_corr or 0.0
        btc_trend = fv.g13_btc_trend or 0
        opposes_btc = (tentative_direction == "LONG" and btc_trend < 0) or (
            tentative_direction == "SHORT" and btc_trend > 0
        )
        if corr >= 0.7 and opposes_btc:
            scaled = clip((corr - 0.7) / 0.3, 0.0, 1.0)
            corr_factor = round(1.0 - 0.5 * scaled, 4)

    # Gate 4: Confidence
    confidence = round(abs(cs) * regime_factor * corr_factor, 4)
    min_conf = thresholds.get("min_confidence", 0.40)
    if confidence < min_conf:
        return _make_hold(fv, cs, "low_confidence", contributions, config_ver, regime_factor, corr_factor, confidence)

    # Gate 5: Volume confirmation gate
    vol_gate_on = thresholds.get("volume_gate_enabled", True)
    min_vol_ratio = thresholds.get("volume_ratio_gate", 1.2)
    if vol_gate_on and (fv.volume_ratio is not None and fv.volume_ratio < min_vol_ratio):
        return _make_hold(fv, cs, "volume_gate", contributions, config_ver, regime_factor, corr_factor, confidence)

    # Gate 6: Entry, Stop Loss, Take Profit
    entry = fv.close or 0.0
    atr = fv.atr or (entry * 0.02)  # fallback 2% if ATR missing
    if atr <= 0:
        atr = entry * 0.02

    sl_dist = thresholds.get("sl_atr_multiplier", 1.5) * atr

    # Liquidation cluster check
    cluster_buffer = thresholds.get("sl_cluster_buffer_atr", 0.25) * atr
    max_sl_mult = thresholds.get("max_sl_atr_multiplier", 3.0)

    if tentative_direction == "LONG":
        nominal_sl = entry - sl_dist
        liq_below = fv.g09_liq_below_price
        # If liquidation cluster lies between entry and stop on adverse side
        if liq_below and (nominal_sl < liq_below < entry):
            nominal_sl = liq_below - cluster_buffer
            sl_dist = entry - nominal_sl

        if sl_dist > max_sl_mult * atr:
            return _make_hold(fv, cs, "sl_too_wide", contributions, config_ver, regime_factor, corr_factor, confidence)

        stop_loss = round(nominal_sl, 4)
        tp_dist = sl_dist * thresholds.get("reward_to_risk", 2.0)
        take_profit = round(entry + tp_dist, 4)

    else:  # SHORT
        nominal_sl = entry + sl_dist
        liq_above = fv.g09_liq_above_price
        if liq_above and (entry < liq_above < nominal_sl):
            nominal_sl = liq_above + cluster_buffer
            sl_dist = nominal_sl - entry

        if sl_dist > max_sl_mult * atr:
            return _make_hold(fv, cs, "sl_too_wide", contributions, config_ver, regime_factor, corr_factor, confidence)

        stop_loss = round(nominal_sl, 4)
        tp_dist = sl_dist * thresholds.get("reward_to_risk", 2.0)
        take_profit = round(entry - tp_dist, 4)

    sl_dist_atr = round(sl_dist / atr, 4)
    size_multiplier = round(clip(confidence / 0.6, 0.4, 1.0), 4)

    return {
        "symbol": fv.symbol,
        "interval": fv.interval,
        "ts": fv.ts,
        "direction": tentative_direction,
        "hold_reason": None,
        "composite_score": cs,
        "regime_factor": regime_factor,
        "corr_factor": corr_factor,
        "confidence": confidence,
        "entry_price": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sl_distance_atr": sl_dist_atr,
        "rr": thresholds.get("reward_to_risk", 2.0),
        "size_multiplier": size_multiplier,
        "contributions": contributions,
        "features_snapshot": fv.model_dump(mode="json"),
        "config_version": config_ver,
    }


def _make_hold(
    fv: FeatureVector,
    cs: float,
    reason: str,
    contributions: Dict[str, Any],
    config_ver: str,
    regime_factor: float = 1.0,
    corr_factor: float = 1.0,
    confidence: float = 0.0,
) -> Dict[str, Any]:
    return {
        "symbol": fv.symbol,
        "interval": fv.interval,
        "ts": fv.ts,
        "direction": "HOLD",
        "hold_reason": reason,
        "composite_score": cs,
        "regime_factor": regime_factor,
        "corr_factor": corr_factor,
        "confidence": confidence,
        "entry_price": fv.close,
        "stop_loss": None,
        "take_profit": None,
        "sl_distance_atr": None,
        "rr": None,
        "size_multiplier": 0.0,
        "contributions": contributions,
        "features_snapshot": fv.model_dump(mode="json"),
        "config_version": config_ver,
    }
