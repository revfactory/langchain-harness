"""Sequential-mode runtime smoke: 2 members × 1 round with mocked agents."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from langchain_harness.team import mailbox, registry
from langchain_harness.team.runtime import AgentTeamHarness
from langchain_harness.team.types import TeamMember


class _RecordingAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, state: dict) -> dict:
        self.calls.append(state)
        return state


def _make_member(name: str, team: str) -> TeamMember:
    now = datetime.now(timezone.utc).isoformat()
    return TeamMember(
        agent_name=name,
        agent_id=f"{name}@{team}",
        role="engineer",
        model_id="claude-opus-4-7",
        tools=[],
        state="spawning",
        spawned_at=now,
        last_heartbeat=now,
    )


def test_sequential_two_members_one_round(workspace: Path) -> None:
    registry.team_create(
        workspace, team_name="rt", lead_name="lead", shared_objective="test"
    )
    h = AgentTeamHarness(
        team_name="rt", workspace=workspace, isolation="sequential"
    )
    h.start()
    agents: dict[str, _RecordingAgent] = {}

    def factory(ctx):
        a = _RecordingAgent()
        agents[ctx.agent_name] = a
        return a

    h.spawn(_make_member("alice", "rt"), factory)
    h.spawn(_make_member("bob", "rt"), factory)

    # send one message to each before ticking
    mailbox.append_entry(
        workspace, "rt", sender="lead", recipient="alice", body="hi alice"
    )
    mailbox.append_entry(
        workspace, "rt", sender="lead", recipient="bob", body="hi bob"
    )

    h.tick()

    assert len(agents["alice"].calls) == 1
    assert len(agents["bob"].calls) == 1

    # After tick, the single unread message should be marked read.
    alice_entries = mailbox.read_entries(workspace, "rt", "alice")
    assert alice_entries[0].status == "read"

    h.shutdown(cascade=True)


def test_process_isolation_not_implemented(workspace: Path) -> None:
    registry.team_create(
        workspace, team_name="pi", lead_name="lead", shared_objective=""
    )
    h = AgentTeamHarness(
        team_name="pi", workspace=workspace, isolation="process"
    )
    h.start()
    import pytest

    with pytest.raises(NotImplementedError):
        h.spawn(_make_member("alice", "pi"), lambda ctx: object())
