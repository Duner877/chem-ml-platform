"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def registry():
    """The fully populated global node registry."""
    from nodes.loader import get_registry

    return get_registry()


@pytest.fixture(scope="session")
def workflow_files():
    """Every stored demo workflow."""
    return sorted((ROOT / "workflows").glob("*.json"))
