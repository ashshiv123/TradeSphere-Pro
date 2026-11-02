"""
test_stage0_health.py — Stage 0 structural smoke tests.

These tests verify the code *structure* is correct (routes exist, config
loads, etc.) without needing Docker or a real database.
"""
from __future__ import annotations

import importlib
import os


def test_config_loads():
    """Settings class can be instantiated with fallback defaults."""
    # Set a minimal DATABASE_URL so no error is thrown
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://u:p@localhost/test")
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    from app.config import Settings
    s = Settings()
    assert "BTCUSDT" in s.symbol_list
    assert "4h" in s.interval_list


def test_logging_setup_importable():
    """logging_setup module is importable and callable."""
    from app.logging_setup import configure_logging
    configure_logging("WARNING")  # should not raise


def _get_app_paths(app):
    paths = set()
    for r in app.routes:
        if hasattr(r, "original_router"):
            for sub in r.original_router.routes:
                if hasattr(sub, "path"):
                    paths.add(sub.path)
        elif hasattr(r, "path"):
            paths.add(r.path)
    return paths


def test_fastapi_app_importable():
    """FastAPI app can be imported (routes registered without a DB)."""
    from app.main import app
    paths = _get_app_paths(app)
    assert "/health" in paths


def test_routes_registered():
    """All expected routes are registered on the app."""
    from app.main import app
    paths = _get_app_paths(app)
    expected = {"/health", "/collectors/status", "/features/{symbol}/latest",
                "/features/{symbol}", "/data/{table}/latest"}
    missing = expected - paths
    assert not missing, f"Missing routes: {missing}"

