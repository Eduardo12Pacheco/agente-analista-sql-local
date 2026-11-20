"""Shared fixtures for warehouse adapter tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlagent.adapters.warehouse.etl import build_warehouse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ocds_mini"


@pytest.fixture(scope="session")
def mini_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the synthetic OCDS mini warehouse once per test session."""

    out = tmp_path_factory.mktemp("mini-bundle")
    build_warehouse(FIXTURES, out, allow_drift=True)
    return out
