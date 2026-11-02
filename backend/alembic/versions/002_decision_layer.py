"""Decision layer schema - tables from DECISION_LAYER_PLAN.md section 2.

Revision ID: 002_decision_layer
Revises: 001_initial_schema
Create Date: 2026-11-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "002_decision_layer"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── signals ──────────────────────────────────────────────────────────────
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("hold_reason", sa.Text(), nullable=True),
        sa.Column("composite_score", sa.REAL(), nullable=True),
        sa.Column("regime_factor", sa.REAL(), nullable=True),
        sa.Column("corr_factor", sa.REAL(), nullable=True),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(24, 8), nullable=True),
        sa.Column("take_profit", sa.Numeric(24, 8), nullable=True),
        sa.Column("sl_distance_atr", sa.REAL(), nullable=True),
        sa.Column("rr", sa.REAL(), nullable=True),
        sa.Column("size_multiplier", sa.REAL(), nullable=True),
        sa.Column("contributions", postgresql.JSONB(), nullable=True),
        sa.Column("features_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("config_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "interval", "ts", name="uq_signals_symbol_interval_ts"),
    )
    op.create_index("ix_signals_ts", "signals", ["ts"])

    # ── signal_explanations ──────────────────────────────────────────────────
    op.create_table(
        "signal_explanations",
        sa.Column("signal_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("text", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("signal_id"),
    )

    # ── trade_plans ──────────────────────────────────────────────────────────
    op.create_table(
        "trade_plans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(30, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(24, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(24, 8), nullable=False),
        sa.Column("leverage", sa.REAL(), nullable=False),
        sa.Column("risk_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── risk_events ──────────────────────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("signal_id", sa.BigInteger(), nullable=True),
        sa.Column("plan_id", sa.BigInteger(), nullable=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── kill_switch_state ────────────────────────────────────────────────────
    op.create_table(
        "kill_switch_state",
        sa.Column("id", sa.Integer(), nullable=False, default=1),
        sa.Column("active", sa.Boolean(), nullable=False, default=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── orders ───────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("client_order_id", sa.Text(), nullable=False),
        sa.Column("exchange_order_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(30, 8), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("filled_qty", sa.Numeric(30, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_fill_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("fee", sa.Numeric(24, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )

    # ── positions ────────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(30, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(24, 8), nullable=True),
        sa.Column("take_profit", sa.Numeric(24, 8), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("fees", sa.Numeric(24, 8), nullable=True),
        sa.Column("funding", sa.Numeric(24, 8), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── equity_snapshots ─────────────────────────────────────────────────────
    op.create_table(
        "equity_snapshots",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Numeric(24, 8), nullable=False),
        sa.Column("balance", sa.Numeric(24, 8), nullable=True),
        sa.Column("unrealised_pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="exchange"),
        sa.PrimaryKeyConstraint("ts"),
    )

    # ── backtest_runs ────────────────────────────────────────────────────────
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("symbols", postgresql.JSONB(), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── backtest_trades ──────────────────────────────────────────────────────
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("qty", sa.Numeric(30, 8), nullable=False),
        sa.Column("pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("fees", sa.Numeric(24, 8), nullable=True),
        sa.Column("funding", sa.Numeric(24, 8), nullable=True),
        sa.Column("r_multiple", sa.REAL(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
    op.drop_table("equity_snapshots")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("kill_switch_state")
    op.drop_table("risk_events")
    op.drop_table("trade_plans")
    op.drop_table("signal_explanations")
    op.drop_table("signals")

