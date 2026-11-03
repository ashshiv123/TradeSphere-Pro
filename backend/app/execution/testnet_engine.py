"""
testnet_engine.py - Testnet Execution Engine for TradeSphere Pro (Section 9).
TESTNET ONLY: Strictly refuses to start or place orders in any other mode.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_trading import EquitySnapshot, KillSwitchState, Order, Position, RiskEvent, TradePlan

logger = logging.getLogger(__name__)

# HARD CODE SAFETY CAPS (Section 9: Hard caps in code, not in config)
HARD_CAP_MAX_LEVERAGE: float = 5.0
HARD_CAP_MAX_NOTIONAL: float = 1000.0  # Max $1,000 per order on testnet


class ExecutionModeError(RuntimeError):
    pass


class StopLossPlacementError(RuntimeError):
    pass


def verify_testnet_mode_or_die() -> None:
    """Enforces that EXECUTION_MODE is strictly TESTNET."""
    mode = os.getenv("EXECUTION_MODE", "TESTNET").strip().upper()
    if mode != "TESTNET":
        msg = f"FATAL: Execution engine aborted! EXECUTION_MODE is '{mode}', but ONLY 'TESTNET' is permitted."
        logger.critical(msg)
        raise ExecutionModeError(msg)


class BinanceTestnetClient:
    """
    Direct REST API client for Binance Futures Testnet.
    Base URL: https://testnet.binancefuture.com
    Authenticates requests via HMAC-SHA256 signature.
    """
    BASE_URL = "https://testnet.binancefuture.com"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key or os.getenv("BINANCE_TESTNET_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_TESTNET_SECRET", "")

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    def get_account(self) -> Dict[str, Any]:
        """Fetch account balance and positions."""
        verify_testnet_mode_or_die()
        url = f"{self.BASE_URL}/fapi/v2/account"
        params = self._sign_params({})
        headers = {"X-MBX-APIKEY": self.api_key}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        verify_testnet_mode_or_die()
        url = f"{self.BASE_URL}/fapi/v1/openOrders"
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        params = self._sign_params(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        verify_testnet_mode_or_die()
        url = f"{self.BASE_URL}/fapi/v1/order"
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.6f}".rstrip("0").rstrip("."),
        }
        if price:
            params["price"] = f"{price:.2f}"
            params["timeInForce"] = "GTC"
        if stop_price:
            params["stopPrice"] = f"{stop_price:.2f}"
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        params = self._sign_params(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def cancel_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        verify_testnet_mode_or_die()
        url = f"{self.BASE_URL}/fapi/v1/order"
        params = self._sign_params({"symbol": symbol, "origClientOrderId": client_order_id})
        headers = {"X-MBX-APIKEY": self.api_key}
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()


class TestnetExecutionEngine:
    """
    Testnet Order Lifecycle and Safety Controller.
    """
    def __init__(self, db: Session, exchange_client: Optional[Any] = None):
        verify_testnet_mode_or_die()
        self.db = db
        self.client = exchange_client or BinanceTestnetClient()

    def execute_plan(self, plan: TradePlan) -> Dict[str, Any]:
        """
        Executes an approved TradePlan:
        1. Hard checks (leverage <= 5, notional <= 1000, valid stop-loss).
        2. Idempotent check (never send duplicate order for client_order_id).
        3. Market entry order.
        4. When filled, places Reduce-Only Stop-Loss and Take-Profit.
        5. PROTECTION RULE: If stop placement fails, immediately closes position at market,
           logs critical risk event, and activates kill-switch.
        """
        verify_testnet_mode_or_die()

        # Deterministic client order ID for entry
        entry_cid = f"tsp-{plan.id}-{plan.symbol.lower()}-entry"

        # Idempotency check: see if order already exists in DB or plan already filled
        existing_order = self.db.scalars(select(Order).where(Order.client_order_id == entry_cid)).first()
        if existing_order or plan.status in ("filled", "closed"):
            logger.warning("Order with client_order_id=%s or plan %s already filled. Skipping duplicate entry.", entry_cid, plan.id)
            return {"status": "skipped", "reason": "duplicate_client_order_id", "order_id": existing_order.id if existing_order else None}

        # Hard Check 1: Must be approved
        if plan.status != "approved":
            raise ValueError(f"Plan id={plan.id} is '{plan.status}', cannot execute unless 'approved'.")

        # Hard Check 2: Leverage cap
        if plan.leverage > HARD_CAP_MAX_LEVERAGE:
            raise ValueError(f"Plan leverage {plan.leverage} exceeds HARD CAP {HARD_CAP_MAX_LEVERAGE}")

        # Hard Check 3: Max notional cap
        notional = float(plan.qty) * float(plan.entry_price)
        if notional > HARD_CAP_MAX_NOTIONAL:
            raise ValueError(f"Plan notional ${notional:.2f} exceeds HARD CAP ${HARD_CAP_MAX_NOTIONAL:.2f}")

        # Hard Check 4: No order without stop-loss
        if not plan.stop_loss or float(plan.stop_loss) <= 0:
            raise ValueError("HARD SAFETY VIOLATION: Refusing order execution without a valid stop-loss!")

        entry_side = "BUY" if plan.side == "LONG" else "SELL"
        exit_side = "SELL" if plan.side == "LONG" else "BUY"

        # 1. Place Entry Order
        try:
            entry_resp = self.client.place_order(
                symbol=plan.symbol,
                side=entry_side,
                order_type="MARKET",
                quantity=float(plan.qty),
                client_order_id=entry_cid,
            )
        except Exception as exc:
            logger.error("Entry order failed for plan %s: %s", plan.id, exc)
            plan.status = "failed"
            self.db.commit()
            raise

        fill_price = float(entry_resp.get("avgPrice") or entry_resp.get("price") or plan.entry_price)
        filled_qty = float(entry_resp.get("executedQty") or plan.qty)
        exchange_oid = str(entry_resp.get("orderId", ""))

        order_row = Order(
            plan_id=plan.id,
            client_order_id=entry_cid,
            exchange_order_id=exchange_oid,
            type="entry",
            side=entry_side,
            qty=filled_qty,
            price=fill_price,
            status="filled",
            filled_qty=filled_qty,
            avg_fill_price=fill_price,
            raw=entry_resp,
        )
        self.db.add(order_row)

        # Create Position row
        pos = Position(
            plan_id=plan.id,
            symbol=plan.symbol,
            side=plan.side,
            qty=filled_qty,
            entry_price=fill_price,
            stop_loss=float(plan.stop_loss),
            take_profit=float(plan.take_profit),
            opened_at=datetime.now(timezone.utc),
            status="open",
        )
        self.db.add(pos)
        plan.status = "filled"
        self.db.commit()

        # 2. Place Reduce-Only Stop-Loss Order
        sl_cid = f"tsp-{plan.id}-{plan.symbol.lower()}-sl"
        try:
            sl_resp = self.client.place_order(
                symbol=plan.symbol,
                side=exit_side,
                order_type="STOP_MARKET",
                quantity=filled_qty,
                stop_price=float(plan.stop_loss),
                reduce_only=True,
                client_order_id=sl_cid,
            )
            self.db.add(Order(
                plan_id=plan.id,
                client_order_id=sl_cid,
                exchange_order_id=str(sl_resp.get("orderId", "")),
                type="stop",
                side=exit_side,
                qty=filled_qty,
                price=float(plan.stop_loss),
                status="new",
                raw=sl_resp,
            ))
            self.db.commit()
        except Exception as exc:
            # CRITICAL PROTECTION RULE:
            # If the stop-loss order cannot be placed, immediately close position at market,
            # log critical risk event, and activate kill-switch!
            logger.critical("PROTECTION RULE ACTIVATED: Stop-loss placement failed for plan %s! Error: %s", plan.id, exc)

            # Close position at market
            emergency_cid = f"tsp-{plan.id}-emergency-close"
            try:
                self.client.place_order(
                    symbol=plan.symbol,
                    side=exit_side,
                    order_type="MARKET",
                    quantity=filled_qty,
                    reduce_only=True,
                    client_order_id=emergency_cid,
                )
            except Exception as close_exc:
                logger.critical("Emergency position close failed: %s", close_exc)

            pos.status = "closed"
            pos.closed_at = datetime.now(timezone.utc)
            pos.exit_reason = "emergency_sl_failed"

            # Activate Kill-Switch
            ks = self.db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
            reason = f"Emergency: Stop-loss placement failed on {plan.symbol} ({exc})"
            if not ks:
                self.db.add(KillSwitchState(id=1, active=True, reason=reason, triggered_at=datetime.now(timezone.utc)))
            else:
                ks.active = True
                ks.reason = reason
                ks.triggered_at = datetime.now(timezone.utc)

            self.db.add(RiskEvent(
                symbol=plan.symbol,
                signal_id=plan.signal_id,
                plan_id=plan.id,
                rule="protection_stop_placement_failure",
                action="critical",
                details={"error": str(exc), "action": "emergency_closed_and_kill_switch_triggered"},
            ))
            self.db.commit()
            raise StopLossPlacementError(f"Stop loss placement failed: {exc}. Emergency close triggered.")

        # 3. Place Take-Profit Order
        tp_cid = f"tsp-{plan.id}-{plan.symbol.lower()}-tp"
        try:
            tp_resp = self.client.place_order(
                symbol=plan.symbol,
                side=exit_side,
                order_type="TAKE_PROFIT_MARKET",
                quantity=filled_qty,
                stop_price=float(plan.take_profit),
                reduce_only=True,
                client_order_id=tp_cid,
            )
            self.db.add(Order(
                plan_id=plan.id,
                client_order_id=tp_cid,
                exchange_order_id=str(tp_resp.get("orderId", "")),
                type="take_profit",
                side=exit_side,
                qty=filled_qty,
                price=float(plan.take_profit),
                status="new",
                raw=tp_resp,
            ))
            self.db.commit()
        except Exception as exc:
            logger.warning("Take-profit placement failed for plan %s: %s", plan.id, exc)

        return {
            "status": "executed",
            "plan_id": plan.id,
            "entry_order_id": entry_cid,
            "stop_order_id": sl_cid,
            "fill_price": fill_price,
            "filled_qty": filled_qty,
        }

    def reconcile_portfolio(self) -> Dict[str, Any]:
        """
        60-Second Reconciliation:
        - Exchange is the source of truth.
        - Compares exchange open positions & orders with DB.
        - Unknown exchange position triggers Kill-Switch.
        - Updates closed positions and captures EquitySnapshot.
        """
        verify_testnet_mode_or_die()
        account = self.client.get_account()

        # Extract balance
        wallet_balance = float(account.get("totalWalletBalance") or 0.0)
        unrealized_pnl = float(account.get("totalUnrealizedProfit") or 0.0)
        total_equity = wallet_balance + unrealized_pnl

        # Record EquitySnapshot
        now = datetime.now(timezone.utc)
        self.db.add(EquitySnapshot(
            ts=now,
            equity=total_equity,
            balance=wallet_balance,
            unrealised_pnl=unrealized_pnl,
            source="exchange",
        ))
        self.db.commit()

        # Parse exchange positions
        exchange_positions: Dict[str, float] = {}
        for p in account.get("positions", []):
            amt = float(p.get("positionAmt", 0.0))
            if abs(amt) > 1e-6:
                exchange_positions[p["symbol"]] = amt

        # Compare with DB open positions
        db_positions = self.db.scalars(select(Position).where(Position.status == "open")).all()
        db_pos_symbols = {p.symbol for p in db_positions}

        # Check for unknown exchange positions (ghost / stray positions)
        for ex_sym, ex_amt in exchange_positions.items():
            if ex_sym not in db_pos_symbols:
                logger.critical("RECONCILIATION MISMATCH: Unknown position on exchange for %s (amt=%.4f)!", ex_sym, ex_amt)
                ks = self.db.scalars(select(KillSwitchState).where(KillSwitchState.id == 1)).first()
                if not ks:
                    self.db.add(KillSwitchState(id=1, active=True, reason=f"Unknown position on exchange: {ex_sym}", triggered_at=now))
                else:
                    ks.active = True
                    ks.reason = f"Unknown position on exchange: {ex_sym}"
                    ks.triggered_at = now
                self.db.add(RiskEvent(
                    rule="reconciliation_unknown_position",
                    action="kill_switch",
                    details={"symbol": ex_sym, "amount": ex_amt},
                ))
                self.db.commit()

        # Check if DB positions closed on exchange
        for p in db_positions:
            if p.symbol not in exchange_positions:
                logger.info("Position %s for plan %s has closed on exchange.", p.symbol, p.plan_id)
                p.status = "closed"
                p.closed_at = now
                self.db.commit()

        return {
            "status": "reconciled",
            "total_equity": total_equity,
            "exchange_positions_count": len(exchange_positions),
            "db_open_positions_count": len(db_positions),
            "timestamp": now.isoformat(),
        }

    def recover_on_restart(self) -> None:
        """Runs reconciliation immediately on startup to recover state before processing orders."""
        verify_testnet_mode_or_die()
        logger.info("Testnet Execution Engine recovering state from exchange...")
        self.reconcile_portfolio()
        logger.info("Recovery complete.")
