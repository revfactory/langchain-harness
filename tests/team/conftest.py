"""Shared pytest fixtures for team runtime tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from langchain_harness.team import registry


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Isolated ``_workspace`` directory per test."""
    ws = tmp_path / "_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    yield ws
    # WHY: ensure the in-process team registry does not leak across tests.
    registry._LIVE_TEAMS.clear()
