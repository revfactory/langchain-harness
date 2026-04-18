"""Tool-level smoke tests — call each tool directly with a TeamContext."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from langchain_harness.team import registry, tools
from langchain_harness.team.context import (
    TeamContext,
    reset_team_context,
    set_current_team_context,
)
from langchain_harness.team.types import PermissionDeniedError


@pytest.fixture()
def lead_ctx(workspace: Path):
    registry.team_create(
        workspace, team_name="tt", lead_name="lead", shared_objective=""
    )
    ctx = TeamContext.build(
        workspace=workspace,
        team_name="tt",
        agent_name="lead",
        role="lead",
        is_lead=True,
    )
    token = set_current_team_context(ctx)
    try:
        yield ctx
    finally:
        reset_team_context(token)


@pytest.fixture()
def member_ctx(workspace: Path):
    registry.team_create(
        workspace, team_name="tt2", lead_name="lead", shared_objective=""
    )
    # register a non-lead member
    tf = registry.load_team_file(workspace, "tt2")
    from datetime import datetime, timezone

    from langchain_harness.team.types import TeamMember

    now = datetime.now(timezone.utc).isoformat()
    tf.members.append(
        TeamMember(
            agent_name="bob",
            agent_id="bob@tt2",
            role="engineer",
            model_id="claude-opus-4-7",
            tools=[],
            state="alive",
            spawned_at=now,
            last_heartbeat=now,
        )
    )
    registry.save_team_file(workspace, tf, expected_version=tf.version)
    registry.mailbox_file(workspace, "tt2", "bob").touch()
    ctx = TeamContext.build(
        workspace=workspace,
        team_name="tt2",
        agent_name="bob",
        role="engineer",
        is_lead=False,
    )
    token = set_current_team_context(ctx)
    try:
        yield ctx
    finally:
        reset_team_context(token)


def test_spawn_teammate_lead_ok(lead_ctx: TeamContext) -> None:
    out = tools.spawn_teammate.invoke(
        {"name": "alice", "role": "engineer", "tools": ["read_inbox"]}
    )
    data = json.loads(out)
    assert data["ok"] is True
    assert data["agent_name"] == "alice"


def test_spawn_teammate_requires_lead(member_ctx: TeamContext) -> None:
    with pytest.raises(PermissionDeniedError):
        tools.spawn_teammate.invoke(
            {"name": "carol", "role": "engineer"}
        )


def test_send_and_read_inbox(lead_ctx: TeamContext) -> None:
    tools.spawn_teammate.invoke({"name": "alice", "role": "engineer"})
    # Switch context to alice to read her mailbox.
    ctx2 = TeamContext.build(
        workspace=lead_ctx.workspace,
        team_name="tt",
        agent_name="alice",
        role="engineer",
        is_lead=False,
    )
    # lead sends a message
    send_out = tools.send_message.invoke(
        {"recipient": "alice", "body": "please research X", "kind": "plain"}
    )
    assert json.loads(send_out)["ok"] is True
    # now view alice's inbox
    token = set_current_team_context(ctx2)
    try:
        out = tools.read_inbox.invoke({"max_items": 10, "status_filter": "unread"})
    finally:
        reset_team_context(token)
    data = json.loads(out)
    assert data["count"] == 1
    assert data["entries"][0]["sender"] == "lead"


def test_task_lifecycle_via_tools(lead_ctx: TeamContext) -> None:
    created = tools.team_task_create.invoke(
        {"title": "implement foo", "description": "do foo"}
    )
    task_id = json.loads(created)["task_id"]
    claimed = tools.team_task_claim.invoke({"task_id": task_id})
    version = json.loads(claimed)["version"]
    updated = tools.team_task_update.invoke(
        {
            "task_id": task_id,
            "new_status": "done",
            "expected_version": version,
            "result_summary": "ok",
        }
    )
    assert json.loads(updated)["status"] == "done"
    listed = tools.team_task_list.invoke(
        {"status_filter": ["done"], "limit": 10}
    )
    assert json.loads(listed)["count"] == 1


def test_team_status_tool(lead_ctx: TeamContext) -> None:
    out = tools.team_status.invoke({"include_stopped": False})
    data = json.loads(out)
    assert data["team_name"] == "tt"
    assert data["lead"] == "lead"
    assert isinstance(data["members"], list)


def test_broadcast_message(lead_ctx: TeamContext) -> None:
    tools.spawn_teammate.invoke({"name": "alice", "role": "engineer"})
    tools.spawn_teammate.invoke({"name": "bob", "role": "reviewer"})
    out = tools.broadcast_message.invoke({"body": "standup in 5", "kind": "plain"})
    data = json.loads(out)
    # lead excluded, 2 recipients
    assert data["count"] == 2
