"""
engine.py - Pure and DB-backed Risk Layer for TradeSphere Pro (Section 4).

Evaluates Long/Short signals against 7 safety rules, calculates position sizing,
handles leverage capping/resizing, enforces kill-switch and drawdown rules,
and logs RiskEvent rows for every veto, resize, or kill-switch activation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models_trading import KillSwitchState, Position, RiskEvent, Signal, TradePlan

CONFIG_PATH = Path(__file__).parent / "risk.yaml"


def load_risk_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "risk_per_trade_pct": 1.0,
            "max_leverage": 3.0,
            "max_open_positions": 3,
            "max_total_exposure_pct": 30.0,
            "max_positions_per_symbol": 1,
            "daily_drawdown_pct": 3.0,
            "weekly_drawdown_pct": 6.0,
            "min_stop_distance_pct": 0.3,
            "max_same_direction_correlated": 2,
            "cooldown_candles_after_loss": 3,
            "default_starting_equity": 10000.0,
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def evaluate_risk(
    signal_data: Dict[str, Any],
    portfolio_state: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Pure-function evaluation of a proposed trade against risk rules.
    Used by both the live worker and the backtester.

    Parameters
    ----------
    signal_data: dict containing direction, entry_price, stop_loss, take_profit,
                 size_multiplier, symbol.
    portfolio_state: dict containing:
        - equity: float
        - open_positions: list of dicts {symbol, side, notional, margin, entry_ts}
        - daily_loss_pct: float
        - weekly_loss_pct: float
        - kill_switch_active: bool
        - recent_losses: dict mapping symbol to candles_since_loss
        - correlation_matrix: optional dict mapping symbol pairs to correlation
    config: optional risk config dict

    Returns
    -------
    (plan_dict or None, list_of_risk_events)
    """
    cfg = config or load_risk_config()
    events: List[Dict[str, Any]] = []

    direction = signal_data.get("direction")
    if direction not in ("LONG", "SHORT"):
        return None, events

    symbol = signal_data.get("symbol", "UNKNOWN")
    entry = float(signal_data.get("entry_price") or 0.0)
    stop_loss = float(signal_data.get("stop_loss") or 0.0)
    take_profit = float(signal_data.get("take_profit") or 0.0)
    size_mult = float(signal_data.get("size_multiplier") or 1.0)

    # Rule 1: SL and TP validation
    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        events.append({
            "rule": "valid_prices",
            "action": "veto",
            "details": {"reason": "Non-positive entry, SL, or TP", "entry": entry, "sl": stop_loss, "tp": take_profit},
        })
        return None, events

    if direction == "LONG" and not (stop_loss < entry < take_profit):
        events.append({
            "rule": "sl_tp_orientation",
            "action": "veto",
            "details": {"reason": "LONG requires stop_loss < entry < take_profit", "entry": entry, "sl": stop_loss, "tp": take_profit},
        })
        return None, events

    if direction == "SHORT" and not (take_profit < entry < stop_loss):
        events.append({
            "rule": "sl_tp_orientation",
            "action": "veto",
            "details": {"reason": "SHORT requires take_profit < entry < stop_loss", "entry": entry, "sl": stop_loss, "tp": take_profit},
        })
        return None, events

    # Stop distance check
    stop_distance = abs(entry - stop_loss)
    stop_dist_pct = (stop_distance / entry) * 100.0
    min_stop_pct = cfg.get("min_stop_distance_pct", 0.3)
    if stop_dist_pct < min_stop_pct:
        events.append({
            "rule": "min_stop_distance",
            "action": "veto",
            "details": {"stop_dist_pct": round(stop_dist_pct, 4), "min_required": min_stop_pct},
        })
        return None, events

    # Rule 2: Kill-switch active
    if portfolio_state.get("kill_switch_active", False):
        events.append({
            "rule": "kill_switch",
            "action": "veto",
            "details": {"reason": "Kill switch is currently active"},
        })
        return None, events

    # Rule 3: Daily and weekly drawdown limits
    daily_dd = portfolio_state.get("daily_loss_pct", 0.0)
    max_daily_dd = cfg.get("daily_drawdown_pct", 3.0)
    if daily_dd >= max_daily_dd:
        events.append({
            "rule": "daily_drawdown",
            "action": "kill_switch",
            "details": {"current_daily_dd": daily_dd, "limit": max_daily_dd},
        })
        return None, events

    weekly_dd = portfolio_state.get("weekly_loss_pct", 0.0)
    max_weekly_dd = cfg.get("weekly_drawdown_pct", 6.0)
    if weekly_dd >= max_weekly_dd:
        events.append({
            "rule": "weekly_drawdown",
            "action": "kill_switch",
            "details": {"current_weekly_dd": weekly_dd, "limit": max_weekly_dd},
        })
        return None, events

    # Rule 4: Open positions & max positions per symbol
    open_positions = portfolio_state.get("open_positions", [])
    max_open = cfg.get("max_open_positions", 3)
    if len(open_positions) >= max_open:
        events.append({
            "rule": "max_positions",
            "action": "veto",
            "details": {"open_count": len(open_positions), "limit": max_open},
        })
        return None, events

    # One position per symbol
    if any(p.get("symbol") == symbol for p in open_positions):
        events.append({
            "rule": "max_positions_per_symbol",
            "action": "veto",
            "details": {"symbol": symbol, "limit": cfg.get("max_positions_per_symbol", 1)},
        })
        return None, events

    # Rule 5: Cooldown after loss on same symbol
    recent_losses = portfolio_state.get("recent_losses", {})
    cooldown_required = cfg.get("cooldown_candles_after_loss", 3)
    candles_since_loss = recent_losses.get(symbol)
    if candles_since_loss is not None and candles_since_loss < cooldown_required:
        events.append({
            "rule": "cooldown_after_loss",
            "action": "veto",
            "details": {"symbol": symbol, "candles_elapsed": candles_since_loss, "required": cooldown_required},
        })
        return None, events

    # Rule 6: Correlated same-direction limit
    max_corr_same = cfg.get("max_same_direction_correlated", 2)
    same_dir_count = sum(1 for p in open_positions if p.get("side") == direction)
    if same_dir_count >= max_corr_same:
        events.append({
            "rule": "max_same_direction_correlated",
            "action": "veto",
            "details": {"same_dir_count": same_dir_count, "limit": max_corr_same},
        })
        return None, events

    # Sizing Math
    equity = float(portfolio_state.get("equity") or cfg.get("default_starting_equity", 10000.0))
    risk_pct = min(cfg.get("risk_per_trade_pct", 1.0), 2.0)  # hard max 2.0%
    risk_amount = equity * (risk_pct / 100.0) * size_mult

    qty = risk_amount / stop_distance
    notional = qty * entry
    max_lev = float(cfg.get("max_leverage", 3.0))

    # Leverage Cap (resize)
    if (notional / equity) > max_lev:
        original_qty = qty
        qty = (equity * max_lev) / entry
        notional = qty * entry
        risk_amount = qty * stop_distance
        events.append({
            "rule": "leverage_cap",
            "action": "resize",
            "details": {
                "original_qty": round(original_qty, 6),
                "resized_qty": round(qty, 6),
                "max_leverage": max_lev,
            },
        })

    # Total exposure check:
    # Total margin used (notional / leverage) as % of equity <= max_total_exposure_pct
    max_exposure_pct = float(cfg.get("max_total_exposure_pct", 30.0))
    max_allowed_total_margin = (max_exposure_pct / 100.0) * equity
    existing_margin = sum(p.get("margin", (p.get("notional", 0.0) / max_lev)) for p in open_positions)
    available_margin = max(0.0, max_allowed_total_margin - existing_margin)

    margin_this_trade = notional / max_lev
    if margin_this_trade > available_margin:
        if available_margin <= 0:
            events.append({
                "rule": "max_total_exposure",
                "action": "veto",
                "details": {"available_margin": 0, "limit_pct": max_exposure_pct},
            })
            return None, events
        # Resize to fit available margin
        original_qty = qty
        qty = (available_margin * max_lev) / entry
        notional = qty * entry
        risk_amount = qty * stop_distance
        events.append({
            "rule": "max_total_exposure",
            "action": "resize",
            "details": {
                "original_qty": round(original_qty, 6),
                "resized_qty": round(qty, 6),
                "available_margin": round(available_margin, 2),
            },
        })

    plan_dict = {
        "symbol": symbol,
        "side": direction,
        "qty": round(qty, 8),
        "entry_price": round(entry, 4),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "leverage": max_lev,
        "risk_amount": round(risk_amount, 4),
        "status": "proposed",
    }
    return plan_dict, events


def check_and_create_trade_plan(
    signal: Signal,
    session: Session,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[TradePlan]:
    """
    Evaluates a stored Signal against DB portfolio state, inserts any RiskEvents,
    and returns a persisted TradePlan if approved.
    """
    cfg = config or load_risk_config()

    # Check kill switch state from DB
    ks = session.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    kill_switch_active = bool(ks.active) if ks else False

    # Get active positions from DB
    active_pos = session.scalars(select(Position).where(Position.status == "open")).all()
    open_positions = [
        {
            "symbol": p.symbol,
            "side": p.side,
            "notional": float(p.qty) * float(p.entry_price),
            "margin": (float(p.qty) * float(p.entry_price)) / cfg.get("max_leverage", 3.0),
        }
        for p in active_pos
    ]

    # Portfolio equity placeholder or latest snapshot
    equity = cfg.get("default_starting_equity", 10000.0)

    portfolio_state = {
        "equity": equity,
        "open_positions": open_positions,
        "daily_loss_pct": 0.0,
        "weekly_loss_pct": 0.0,
        "kill_switch_active": kill_switch_active,
        "recent_losses": {},
    }

    signal_data = {
        "symbol": signal.symbol,
        "direction": signal.direction,
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "size_multiplier": signal.size_multiplier,
    }

    plan_dict, events = evaluate_risk(signal_data, portfolio_state, cfg)

    # Persist risk events
    for ev in events:
        re = RiskEvent(
            symbol=signal.symbol,
            signal_id=signal.id,
            rule=ev["rule"],
            action=ev["action"],
            details=ev.get("details"),
        )
        session.add(re)
        if ev["action"] == "kill_switch":
            if not ks:
                ks = KillSwitchState(id=1, active=True, reason=ev["rule"], triggered_at=datetime.now(timezone.utc))
                session.add(ks)
            else:
                ks.active = True
                ks.reason = ev["rule"]
                ks.triggered_at = datetime.now(timezone.utc)

    if not plan_dict:
        session.commit()
        return None

    # Persist TradePlan
    plan = TradePlan(
        signal_id=signal.id,
        symbol=plan_dict["symbol"],
        side=plan_dict["side"],
        qty=plan_dict["qty"],
        entry_price=plan_dict["entry_price"],
        stop_loss=plan_dict["stop_loss"],
        take_profit=plan_dict["take_profit"],
        leverage=plan_dict["leverage"],
        risk_amount=plan_dict["risk_amount"],
        status="proposed",
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan
