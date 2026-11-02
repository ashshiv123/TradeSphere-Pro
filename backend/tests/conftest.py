"""
conftest.py — shared pytest fixtures and configuration.

Fixtures added here are available to all test files without importing.
"""
from __future__ import annotations

import sys
import os

# Make sure `app` is importable from tests
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

