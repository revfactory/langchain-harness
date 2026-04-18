"""H1: idempotency / TeamAlreadyExistsError + version CAS."""
from __future__ import annotations

from pathlib import Path

import pytest

from langchain_harness.team import registry
from langchain_harness.team.types import (
    TeamAlreadyExistsError,
    TeamDirectoryExistsError,
    VersionConflictError,
)


def test_team_create_idempotency_raises(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="alpha",
        lead_name="lead",
        shared_objective="ship v1",
    )
    with pytest.raises(TeamAlreadyExistsError):
        registry.team_create(
            workspace,
            team_name="alpha",
            lead_name="lead",
            shared_objective="ship v1",
        )


def test_team_create_directory_collision(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="beta",
        lead_name="lead",
        shared_objective="",
    )
    # simulate another host process by forgetting the in-proc registry
    registry.team_forget("beta")
    with pytest.raises(TeamDirectoryExistsError):
        registry.team_create(
            workspace,
            team_name="beta",
            lead_name="lead",
            shared_objective="",
        )


def test_version_cas_conflict(workspace: Path) -> None:
    tf = registry.team_create(
        workspace,
        team_name="gamma",
        lead_name="lead",
        shared_objective="",
    )
    # first save with correct version
    registry.save_team_file(workspace, tf, expected_version=tf.version)
    # stale expected_version should fail
    with pytest.raises(VersionConflictError):
        registry.save_team_file(workspace, tf, expected_version=999)


def test_ensure_team_dirs_creates_layout(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="delta",
        lead_name="lead",
        shared_objective="",
    )
    base = registry.team_dir(workspace, "delta")
    assert (base / "config.json").exists()
    assert (base / "mailbox").is_dir()
    assert (base / "tasks").is_dir()
    assert (base / "locks").is_dir()
