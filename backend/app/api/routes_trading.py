"""
routes_trading.py - Trading and Decision Layer API routes for TradeSphere Pro (Stage 17).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Candle, Feature, FundingRate
from app.db.models_trading import (
    BacktestRun,
    BacktestTrade,
    EquitySnapshot,
    KillSwitchState,
    Order,
    Position,
    RiskEvent,
    Signal,
    SignalExplanation,
    TradePlan,
)
from app.db.session import SessionLocal, get_session
from app.llm.explain import explain_signal
from app.risk.engine import load_risk_config
from app.scoring.engine import load_scoring_config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trading"])

# Connected WebSocket clients for WS /stream
_active_ws_clients: List[WebSocket] = []


async def broadcast_ws(event_type: str, data: Any):
    """Broadcast JSON message to all connected WebSocket clients."""
    payload = json.dumps({"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}, default=str)
    for ws in list(_active_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            if ws in _active_ws_clients:
                _active_ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# Market Overview
# ---------------------------------------------------------------------------
@router.get("/market_overview")
def get_market_overview(db: Session = Depends(get_session)):
    """Aggregates latest prices, funding rates, 24h volumes, and latest signals for all symbols."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    overview = []

    for sym in symbols:
        # Latest 4h candle
        candle = db.scalars(
            select(Candle)
            .where(Candle.symbol == sym, Candle.interval == "4h", Candle.market == "futures")
            .order_by(desc(Candle.close_time))
            .limit(1)
        ).first()

        # Latest funding rate
        funding = db.scalars(
            select(FundingRate)
            .where(FundingRate.symbol == sym)
            .order_by(desc(FundingRate.funding_time))
            .limit(1)
        ).first()

        # Latest signal
        sig = db.scalars(
            select(Signal)
            .where(Signal.symbol == sym, Signal.interval == "4h")
            .order_by(desc(Signal.ts))
            .limit(1)
        ).first()

        # Latest feature vector
        feat = db.scalars(
            select(Feature)
            .where(Feature.symbol == sym, Feature.interval == "4h")
            .order_by(desc(Feature.ts))
            .limit(1)
        ).first()

        overview.append({
            "symbol": sym,
            "price": float(candle.close) if candle else None,
            "volume_24h": float(candle.volume) if candle else None,
            "funding_rate": float(funding.funding_rate) if funding else None,
            "latest_signal": {
                "id": sig.id if sig else None,
                "direction": sig.direction if sig else "HOLD",
                "composite_score": sig.composite_score if sig else None,
                "confidence": sig.confidence if sig else None,
                "hold_reason": sig.hold_reason if sig else None,
                "ts": sig.ts.isoformat() if sig else None,
            } if sig else None,
            "features_summary": {
                "f01_momentum": feat.f01_momentum if feat else None,
                "f02_ema_trend": feat.f02_ema_trend if feat else None,
                "f03_rsi": feat.f03_rsi if feat else None,
                "f04_macd": feat.f04_macd if feat else None,
                "g12_regime": feat.g12_regime_factor if feat else None,
                "g13_btc_corr": feat.g13_btc_corr if feat else None,
            } if feat else None,
        })

    return overview


# ---------------------------------------------------------------------------
# Signals & Explanations
# ---------------------------------------------------------------------------
@router.get("/signals")
def get_signals(
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
):
    """Returns recent signals."""
    query = select(Signal).order_by(desc(Signal.ts))
    if symbol:
        query = query.where(Signal.symbol == symbol)
    query = query.limit(limit)
    rows = db.scalars(query).all()
    return rows


@router.get("/signals/{signal_id}")
def get_signal_detail(signal_id: int, db: Session = Depends(get_session)):
    """Returns detailed signal object, including feature contributions and LLM explanation."""
    sig = db.scalars(select(Signal).where(Signal.id == signal_id)).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")

    expl = db.scalars(select(SignalExplanation).where(SignalExplanation.signal_id == signal_id)).first()
    if not expl:
        # Trigger explanation generation on demand
        try:
            expl = explain_signal(signal_id, session=db)
        except Exception as exc:
            logger.warning("Explanation generation failed: %s", exc)

    return {
        "signal": sig,
        "explanation": expl,
    }


# ---------------------------------------------------------------------------
# Trade Plans & Approvals
# ---------------------------------------------------------------------------
@router.get("/plans")
def get_trade_plans(status: Optional[str] = None, db: Session = Depends(get_session)):
    """Returns trade plans."""
    query = select(TradePlan).order_by(desc(TradePlan.created_at))
    if status:
        query = query.where(TradePlan.status == status)
    return db.scalars(query).all()


@router.post("/plans/{plan_id}/approve")
async def approve_trade_plan(plan_id: int, db: Session = Depends(get_session)):
    """Approves a proposed trade plan."""
    plan = db.scalars(select(TradePlan).where(TradePlan.id == plan_id)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Trade plan not found")
    if plan.status != "proposed":
        raise HTTPException(status_code=400, detail=f"Cannot approve plan with status '{plan.status}'")

    # Check kill switch before approving
    ks = db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    if ks and ks.active:
        raise HTTPException(status_code=400, detail="Cannot approve plan while Kill-Switch is ACTIVE")

    plan.status = "approved"
    plan.approved_by = "manual"
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)

    await broadcast_ws("plan_update", {
        "id": plan.id,
        "status": plan.status,
        "symbol": plan.symbol,
        "side": plan.side,
        "approved_by": plan.approved_by,
    })

    return {"status": "approved", "plan": plan}


@router.post("/plans/{plan_id}/reject")
async def reject_trade_plan(plan_id: int, db: Session = Depends(get_session)):
    """Rejects a proposed trade plan."""
    plan = db.scalars(select(TradePlan).where(TradePlan.id == plan_id)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Trade plan not found")

    plan.status = "rejected"
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)

    await broadcast_ws("plan_update", {
        "id": plan.id,
        "status": plan.status,
        "symbol": plan.symbol,
    })

    return {"status": "rejected", "plan": plan}


# ---------------------------------------------------------------------------
# Positions & Orders
# ---------------------------------------------------------------------------
@router.get("/positions")
def get_positions(status: Optional[str] = None, db: Session = Depends(get_session)):
    """Returns positions list."""
    query = select(Position).order_by(desc(Position.opened_at))
    if status:
        query = query.where(Position.status == status)
    return db.scalars(query).all()


@router.get("/orders")
def get_orders(limit: int = 50, db: Session = Depends(get_session)):
    """Returns orders list."""
    return db.scalars(select(Order).order_by(desc(Order.created_at)).limit(limit)).all()


# ---------------------------------------------------------------------------
# Risk Status & Kill-Switch
# ---------------------------------------------------------------------------
@router.get("/risk/status")
def get_risk_status(db: Session = Depends(get_session)):
    """Returns live risk status: kill switch, open positions count, exposure, config rules."""
    risk_cfg = load_risk_config()

    ks = db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    kill_switch_active = bool(ks.active) if ks else False

    open_pos = db.scalars(select(Position).where(Position.status == "open")).all()
    open_count = len(open_pos)

    # Estimate margin used
    equity = risk_cfg.get("default_starting_equity", 10000.0)
    total_notional = sum(float(p.qty) * float(p.entry_price) for p in open_pos)
    total_margin = total_notional / risk_cfg.get("max_leverage", 3.0)
    exposure_pct = (total_margin / equity) * 100.0

    recent_events = db.scalars(select(RiskEvent).order_by(desc(RiskEvent.ts)).limit(10)).all()

    return {
        "kill_switch": {
            "active": kill_switch_active,
            "reason": ks.reason if ks else None,
            "triggered_at": ks.triggered_at.isoformat() if (ks and ks.triggered_at) else None,
        },
        "portfolio": {
            "equity": equity,
            "open_positions_count": open_count,
            "max_open_positions": risk_cfg.get("max_open_positions", 3),
            "total_notional": round(total_notional, 2),
            "total_margin_used": round(total_margin, 2),
            "exposure_pct": round(exposure_pct, 2),
            "max_exposure_pct": risk_cfg.get("max_total_exposure_pct", 30.0),
        },
        "rules": risk_cfg,
        "recent_events": recent_events,
    }


@router.post("/killswitch/trigger")
async def trigger_kill_switch(reason: str = "Manual trigger via Dashboard", db: Session = Depends(get_session)):
    """Emergency trigger of Kill-Switch."""
    ks = db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    if not ks:
        ks = KillSwitchState(id=1, active=True, reason=reason, triggered_at=datetime.now(timezone.utc))
        db.add(ks)
    else:
        ks.active = True
        ks.reason = reason
        ks.triggered_at = datetime.now(timezone.utc)

    db.add(RiskEvent(rule="kill_switch", action="kill_switch", details={"reason": reason}))
    db.commit()

    await broadcast_ws("kill_switch", {"active": True, "reason": reason})
    return {"status": "kill_switch_active", "reason": reason}


@router.post("/killswitch/reset")
async def reset_kill_switch(db: Session = Depends(get_session)):
    """Reset Kill-Switch (manual authorization)."""
    ks = db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
    if ks:
        ks.active = False
        ks.reason = None
        ks.reset_at = datetime.now(timezone.utc)
        db.add(RiskEvent(rule="kill_switch", action="reset", details={"action": "manual_reset"}))
        db.commit()

    await broadcast_ws("kill_switch", {"active": False, "reason": None})
    return {"status": "kill_switch_reset"}


# ---------------------------------------------------------------------------
# Backtests & Equity
# ---------------------------------------------------------------------------
@router.get("/backtests")
def list_backtests(db: Session = Depends(get_session)):
    """Returns history of backtest runs."""
    return db.scalars(select(BacktestRun).order_by(desc(BacktestRun.created_at))).all()


@router.get("/backtests/{run_id}")
def get_backtest_detail(run_id: int, db: Session = Depends(get_session)):
    """Returns backtest run details and trades list."""
    run = db.scalars(select(BacktestRun).where(BacktestRun.id == run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades = db.scalars(select(BacktestTrade).where(BacktestTrade.run_id == run_id)).all()
    return {
        "run": run,
        "trades": trades,
    }


@router.get("/equity")
def get_equity_history(limit: int = 100, db: Session = Depends(get_session)):
    """Returns recent portfolio equity snapshot marks."""
    return db.scalars(select(EquitySnapshot).order_by(desc(EquitySnapshot.ts)).limit(limit)).all()


# ---------------------------------------------------------------------------
# WebSocket Stream (WS /stream)
# ---------------------------------------------------------------------------
@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    Real-time WebSocket feed for TradeSphere Pro dashboard.
    Pushes market updates, new signals, plan updates, and risk events.
    """
    await websocket.accept()
    _active_ws_clients.append(websocket)
    try:
        # Send initial connection greeting with status
        with SessionLocal() as db:
            ks = db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
            ks_active = bool(ks.active) if ks else False

        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kill_switch_active": ks_active,
        }))

        # Keep connection open and respond to ping
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}))

    except WebSocketDisconnect:
        if websocket in _active_ws_clients:
            _active_ws_clients.remove(websocket)
    except Exception as exc:
        logger.warning("WS client disconnected with error: %s", exc)
        if websocket in _active_ws_clients:
            _active_ws_clients.remove(websocket)

