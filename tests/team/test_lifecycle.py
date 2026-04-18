"""H7: spawn→alive→idle→stopped log ordering; H8: stale sweep orphan."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain_harness.team import registry
from langchain_harness.team.runtime import AgentTeamHarness
from langchain_harness.team.types import TeamMember


class _NullAgent:
    def invoke(self, state: dict) -> dict:  # noqa: D401
        return state


def _factory(ctx):
    return _NullAgent()


def _make_member(name: str, team_name: str) -> TeamMember:
    now = datetime.now(timezone.utc).isoformat()
    return TeamMember(
        agent_name=name,
        agent_id=f"{name}@{team_name}",
        role="engineer",
        model_id="claude-opus-4-7",
        tools=[],
        state="spawning",
        spawned_at=now,
        last_heartbeat=now,
    )


def _log_kinds(workspace: Path, team_name: str) -> list[str]:
    path = registry.logs_path(workspace, team_name)
    out: list[str] = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line).get("kind", ""))
        except json.JSONDecodeError:
            continue
    return out


def test_lifecycle_sequential_transitions(workspace: Path) -> None:
    registry.team_create(
        workspace, team_name="life", lead_name="lead", shared_objective=""
    )
    h = AgentTeamHarness(
        team_name="life", workspace=workspace, isolation="sequential"
    )
    h.start()
    member = _make_member("eng1", "life")
    h.spawn(member, _factory)
    # No unread inbox → tick should send the member into idle.
    h.tick()
    h.shutdown(cascade=True)
    kinds = _log_kinds(workspace, "life")
    # required order subset: spawn → alive → idle_enter → stopped
    def idx(k: str) -> int:
        return kinds.index(k)

    assert "spawn" in kinds
    assert "alive" in kinds
    assert "idle_enter" in kinds
    assert "stopped" in kinds
    assert idx("spawn") < idx("alive")
    assert idx("alive") < idx("idle_enter")
    assert idx("idle_enter") < idx("stopped")


def test_stale_sweep_marks_orphan(workspace: Path) -> None:
    registry.team_create(
        workspace, team_name="orph", lead_name="lead", shared_objective=""
    )
    h = AgentTeamHarness(
        team_name="orph",
        workspace=workspace,
        isolation="sequential",
        heartbeat_ttl_sec=1,
    )
    h.start()
    member = _make_member("eng1", "orph")
    h.spawn(member, _factory)
    # Manually backdate heartbeat past TTL.
    tf = registry.load_team_file(workspace, "orph")
    m = tf.find_member("eng1")
    assert m is not None
    m.last_heartbeat = (
        datetime.now(timezone.utc) - timedelta(seconds=3600)
    ).isoformat()
    registry.save_team_file(workspace, tf, expected_version=tf.version)
    flagged = h.stale_sweep()
    assert "eng1" in flagged
    tf = registry.load_team_file(workspace, "orph")
    m = tf.find_member("eng1")
    assert m is not None
    assert m.state == "orphan"
