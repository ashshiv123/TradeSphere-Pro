"""Initial schema - all tables from DATA_PIPELINE_PLAN.md section 6.

Revision ID: 001_initial_schema
Revises: (none)
Create Date: 2026-11-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── candles ──────────────────────────────────────────────────────────────
    op.create_table(
        "candles",
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 8), nullable=False),
        sa.Column("quote_volume", sa.Numeric(30, 8), nullable=True),
        sa.Column("trades", sa.Integer(), nullable=True),
        sa.Column("taker_buy_base", sa.Numeric(30, 8), nullable=True),
        sa.Column("taker_buy_quote", sa.Numeric(30, 8), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("market", "symbol", "interval", "open_time"),
    )

    # ── funding_rates ─────────────────────────────────────────────────────────
    op.create_table(
        "funding_rates",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("funding_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.Numeric(18, 10), nullable=False),
        sa.Column("mark_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("rate_type", sa.Text(), nullable=True),   # DEV-002
        sa.PrimaryKeyConstraint("symbol", "funding_time"),
    )

    # ── open_interest ─────────────────────────────────────────────────────────
    op.create_table(
        "open_interest",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sum_open_interest", sa.Numeric(30, 8), nullable=True),
        sa.Column("sum_open_interest_value", sa.Numeric(30, 8), nullable=True),
        sa.Column("cmc_circulating_supply", sa.Numeric(30, 8), nullable=True),  # DEV-003
        sa.PrimaryKeyConstraint("symbol", "period", "ts"),
    )

    # ── long_short_ratio ──────────────────────────────────────────────────────
    op.create_table(
        "long_short_ratio",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ratio_type", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("long_share", sa.Numeric(10, 6), nullable=True),
        sa.Column("short_share", sa.Numeric(10, 6), nullable=True),
        sa.Column("long_short_ratio", sa.Numeric(14, 6), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "ratio_type", "period", "ts"),
    )

    # ── premium_snapshots ─────────────────────────────────────────────────────
    op.create_table(
        "premium_snapshots",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mark_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("index_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("funding_rate", sa.Numeric(18, 10), nullable=True),
        sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "ts"),
    )

    # ── liquidations ─────────────────────────────────────────────────────────
    op.create_table(
        "liquidations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("avg_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("quantity", sa.Numeric(30, 8), nullable=False),
        sa.Column("notional", sa.Numeric(30, 8), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "ts", "side", "price", "quantity",
                            name="uq_liquidations_event"),
    )
    op.create_index("ix_liquidations_symbol_ts", "liquidations", ["symbol", "ts"])

    # ── news_items ────────────────────────────────────────────────────────────
    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("votes_positive", sa.Integer(), nullable=True),
        sa.Column("votes_negative", sa.Integer(), nullable=True),
        sa.Column("votes_important", sa.Integer(), nullable=True),
        sa.Column("vader_compound", sa.REAL(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", "currency",
                            name="uq_news_items_source_id_currency"),
    )
    op.create_index("ix_news_items_currency_published",
                    "news_items", ["currency", "published_at"])

    # ── fear_greed ────────────────────────────────────────────────────────────
    op.create_table(
        "fear_greed",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ts"),
    )

    # ── btc_dominance ─────────────────────────────────────────────────────────
    op.create_table(
        "btc_dominance",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dominance_pct", sa.Numeric(8, 4), nullable=False),
        sa.PrimaryKeyConstraint("ts"),
    )

    # ── scheduled_events ─────────────────────────────────────────────────────
    op.create_table(
        "scheduled_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "event_time", name="uq_scheduled_events"),
    )

    # ── features ─────────────────────────────────────────────────────────────
    op.create_table(
        "features",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        # Scored fields
        sa.Column("f01_momentum", sa.REAL(), nullable=True),
        sa.Column("f02_ema_trend", sa.REAL(), nullable=True),
        sa.Column("f03_rsi", sa.REAL(), nullable=True),
        sa.Column("f04_macd", sa.REAL(), nullable=True),
        sa.Column("f05_funding", sa.REAL(), nullable=True),
        sa.Column("f06_open_interest", sa.REAL(), nullable=True),
        sa.Column("f07_long_short", sa.REAL(), nullable=True),
        sa.Column("f08_basis", sa.REAL(), nullable=True),
        sa.Column("f10_volume_sr", sa.REAL(), nullable=True),
        sa.Column("f11_news", sa.REAL(), nullable=True),
        # Gate fields
        sa.Column("g09_liq_above_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("g09_liq_above_notional", sa.Numeric(30, 8), nullable=True),
        sa.Column("g09_liq_below_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("g09_liq_below_notional", sa.Numeric(30, 8), nullable=True),
        sa.Column("g09_source", sa.Text(), nullable=True),
        sa.Column("g12_regime_factor", sa.REAL(), nullable=True),
        sa.Column("g13_btc_corr", sa.REAL(), nullable=True),
        sa.Column("g13_btc_beta", sa.REAL(), nullable=True),
        sa.Column("g13_btc_trend", sa.SmallInteger(), nullable=True),
        sa.Column("g13_btc_dominance", sa.REAL(), nullable=True),
        # Context
        sa.Column("volume_ratio", sa.REAL(), nullable=True),
        sa.Column("atr", sa.REAL(), nullable=True),
        sa.Column("close", sa.Numeric(24, 8), nullable=True),
        sa.Column("news_pause", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("missing", postgresql.JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("symbol", "interval", "ts"),
    )

    # ── collector_status ──────────────────────────────────────────────────────
    op.create_table(
        "collector_status",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("rows_written_total", sa.BigInteger(), nullable=False,
                  server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("collector_status")
    op.drop_table("features")
    op.drop_table("scheduled_events")
    op.drop_table("btc_dominance")
    op.drop_table("fear_greed")
    op.drop_index("ix_news_items_currency_published", table_name="news_items")
    op.drop_table("news_items")
    op.drop_index("ix_liquidations_symbol_ts", table_name="liquidations")
    op.drop_table("liquidations")
    op.drop_table("premium_snapshots")
    op.drop_table("long_short_ratio")
    op.drop_table("open_interest")
    op.drop_table("funding_rates")
    op.drop_table("candles")

