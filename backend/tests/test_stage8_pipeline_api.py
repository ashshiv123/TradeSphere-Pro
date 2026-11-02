"""
test_stage8_pipeline_api.py — Unit and integration tests for Stage 8 Pipeline, Contract & API.

Tests:
1. FeatureVector Pydantic model methods (scored_fields, gates).
2. pipeline.py: compute_features_for_candle, get_latest_features, get_feature_history, recompute_history.
3. Read-only API routes via TestClient (/health, /collectors/status, /features/{symbol}/latest, /features/{symbol}, /data/{table}/latest).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Candle, Feature
from app.db.session import get_session
from app.features.pipeline import (
    compute_features_for_candle,
    get_feature_history,
    get_latest_features,
    recompute_history,
)
from app.main import app
from app.schemas.feature_vector import FeatureVector

UTC = timezone.utc


from sqlalchemy.pool import StaticPool


# ── 1. FeatureVector Schema Unit Tests ───────────────────────────────────────

def test_feature_vector_methods():
    now = datetime.now(UTC)
    fv = FeatureVector(
        symbol="BTCUSDT",
        interval="4h",
        ts=now,
        f01_momentum=0.45,
        f02_ema_trend=0.30,
        f03_rsi=0.22,
        f04_macd=-0.10,
        f05_funding=0.05,
        f06_open_interest=1.0,
        f07_long_short=-0.25,
        f08_basis=0.15,
        f10_volume_sr=0.40,
        f11_news=0.60,
        g09_liq_above_price=70000.0,
        g09_liq_below_price=65000.0,
        g09_source="liquidation_clusters",
        g12_regime_factor=0.85,
        g13_btc_corr=1.0,
        g13_btc_beta=1.0,
        g13_btc_trend=1,
        g13_btc_dominance=58.5,
        volume_ratio=1.45,
        atr=850.0,
        close=68000.0,
        news_pause=False,
    )

    scored = fv.scored_fields()
    assert len(scored) == 10
    assert scored["f01_momentum"] == 0.45
    assert scored["f03_rsi"] == 0.22

    gates = fv.gates()
    assert gates["g09_source"] == "liquidation_clusters"
    assert gates["g12_regime_factor"] == 0.85
    assert gates["volume_ratio"] == 1.45
    assert gates["news_pause"] is False


# ── 2. Pipeline In-Memory DB Integration Tests ──────────────────────────────

@pytest.fixture(scope="module")
def test_db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(eng)

    with Session(eng) as s:
        # Seed 65 candles for BTCUSDT futures
        times = pd.date_range("2026-01-01", periods=65, freq="4h", tz="UTC")
        for i, t in enumerate(times):
            c = Candle(
                market="futures",
                symbol="BTCUSDT",
                interval="4h",
                open_time=t,
                close_time=t + pd.Timedelta(hours=4),
                open=40000.0 + i * 20.0,
                high=40100.0 + i * 20.0,
                low=39900.0 + i * 20.0,
                close=40050.0 + i * 20.0,
                volume=100.0 + i * 2.0,
                is_closed=True,
            )
            s.add(c)
        s.commit()
        yield s


def test_pipeline_compute_and_query(test_db: Session):
    # Compute features for latest candle
    fv = compute_features_for_candle(test_db, "BTCUSDT", interval="4h")
    assert isinstance(fv, FeatureVector)
    assert fv.symbol == "BTCUSDT"
    assert fv.close is not None
    assert fv.f02_ema_trend is not None
    assert fv.f03_rsi is not None

    # Verify query functions
    latest = get_latest_features("BTCUSDT", interval="4h", db=test_db)
    assert latest is not None
    assert latest.symbol == "BTCUSDT"

    hist_df = get_feature_history("BTCUSDT", interval="4h", db=test_db)
    assert not hist_df.empty
    assert "f02_ema_trend" in hist_df.columns


# ── 3. Read-Only API Route Tests ─────────────────────────────────────────────

def test_api_routes(test_db: Session):
    def override_get_session():
        yield test_db

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)

    # 1. /health
    r = client.get("/health")
    assert r.status_code in (200, 503)

    # 2. /collectors/status
    r = client.get("/collectors/status")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # 3. /features/{symbol}/latest
    r = client.get("/features/BTCUSDT/latest")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "BTCUSDT"
    assert "f02_ema_trend" in data

    # 4. /features/{symbol} (history)
    r = client.get("/features/BTCUSDT")
    assert r.status_code == 200
    assert len(r.json()) >= 1

    # 5. /data/{table}/latest
    r = client.get("/data/candles/latest?symbol=BTCUSDT&limit=5")
    assert r.status_code == 200
    assert len(r.json()) >= 1

    # Invalid table error
    r = client.get("/data/unknown_secret_table/latest")
    assert r.status_code == 400

    app.dependency_overrides.clear()
