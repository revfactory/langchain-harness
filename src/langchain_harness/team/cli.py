"""Typer subapp for team lifecycle operations.

Exposes create/spawn/run/send/inbox/task-create/task-list/status/delete.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from ..config import WORKSPACE_DIR
from . import mailbox as mailbox_mod
from . import registry, tasks
from .context import TeamContext, set_current_team_context

team_app = typer.Typer(add_completion=False, help="Multi-DeepAgent team runtime.")


@team_app.command("create")
def create_cmd(
    team_name: str = typer.Option(..., help="Team name (^[a-z][a-z0-9_-]{1,31}$)."),
    lead: str = typer.Option(..., help="Lead agent_name."),
    objective: str = typer.Option(..., help="Shared objective shown to every member."),
    workspace: Path = typer.Option(WORKSPACE_DIR, help="Workspace root."),
    soft: int = typer.Option(100, help="Mailbox soft limit."),
    hard: int = typer.Option(500, help="Mailbox hard limit."),
    force: bool = typer.Option(False, help="Overwrite existing team directory."),
) -> None:
    """Create a team directory and register the lead."""
    tf = registry.team_create(
        workspace,
        team_name=team_name,
        lead_name=lead,
        shared_objective=objective,
        mailbox_soft_limit=soft,
        mailbox_hard_limit=hard,
        force=force,
    )
    typer.echo(json.dumps({"team_name": tf.team_name, "lead": tf.lead, "version": tf.version}))


@team_app.command("spawn")
def spawn_cmd(
    team_name: str = typer.Option(..., help="Team name."),
    name: str = typer.Option(..., help="New member agent_name."),
    role: str = typer.Option("engineer", help="engineer|reviewer|researcher|custom"),
    tools: str = typer.Option("", help="Comma-separated tool whitelist."),
    system_prompt_fragment: str = typer.Option(""),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Register a teammate entry in config.json. Marks state=spawning."""
    from .types import TeamMember  # local to avoid top-level cycle
    import os
    from datetime import datetime, timezone

    tf = registry.load_team_file(workspace, team_name)
    if tf.find_member(name) is not None:
        raise typer.BadParameter(f"agent_name {name!r} already exists")
    now = datetime.now(timezone.utc).isoformat()
    member = TeamMember(
        agent_name=name,
        agent_id=f"{name}@{team_name}",
        role=role,
        model_id="claude-opus-4-7",
        tools=[t for t in tools.split(",") if t],
        state="spawning",
        spawned_at=now,
        last_heartbeat=now,
        pid=os.getpid(),
        thread_id=None,
        parent=tf.lead,
        current_task_id=None,
        metadata={"system_prompt_fragment": system_prompt_fragment},
    )
    tf.members.append(member)
    registry.save_team_file(workspace, tf, expected_version=tf.version)
    registry.mailbox_file(workspace, team_name, name).touch(exist_ok=True)
    mailbox_mod.append_log(
        workspace,
        team_name,
        {"kind": "spawn_requested", "agent_name": name, "role": role},
    )
    typer.echo(json.dumps({"ok": True, "agent_name": name, "role": role}))


@team_app.command("run")
def run_cmd(
    team_name: str = typer.Option(..., help="Team name."),
    lead: bool = typer.Option(True, help="Start the lead inline (sequential tick)."),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Sequential scaffold: print team status and perform a stale sweep.

    Actual LLM invocation is delegated to ``AgentTeamHarness.spawn`` in code.
    """
    from .runtime import AgentTeamHarness

    h = AgentTeamHarness(team_name=team_name, workspace=workspace, isolation="sequential")
    h.start()
    flagged = h.stale_sweep()
    typer.echo(
        json.dumps({"status": h.status(), "orphan_flagged": flagged, "lead_inline": lead})
    )


@team_app.command("send")
def send_cmd(
    team_name: str = typer.Option(...),
    sender: str = typer.Option(..., help="agent_name of sender."),
    recipient: str = typer.Option(..., help="agent_name of recipient, or '*' for broadcast."),
    body: str = typer.Option(..., help="Message body."),
    kind: str = typer.Option("plain"),
    requires_ack: bool = typer.Option(False),
    ttl_seconds: int = typer.Option(60),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Send a mailbox message (CLI-side; no LLM involvement)."""
    entry = mailbox_mod.append_entry(
        workspace,
        team_name,
        sender=sender,
        recipient=recipient,
        body=body,
        kind=kind,  # type: ignore[arg-type]
        requires_ack=requires_ack,
        ttl_seconds=ttl_seconds,
    )
    typer.echo(json.dumps({"ok": True, "message_id": entry.message_id}))


@team_app.command("inbox")
def inbox_cmd(
    team_name: str = typer.Option(...),
    agent: str = typer.Option(...),
    status: str = typer.Option("unread"),
    max_items: int = typer.Option(20),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Print inbox entries for an agent without mutating status."""
    entries = mailbox_mod.read_entries(workspace, team_name, agent)
    if status != "any":
        entries = [e for e in entries if e.status == status]
    out = [e.to_json() for e in entries[:max_items]]
    typer.echo(json.dumps({"count": len(out), "entries": out}))


@team_app.command("task-create")
def task_create_cmd(
    team_name: str = typer.Option(...),
    title: str = typer.Option(...),
    description: str = typer.Option(""),
    created_by: str = typer.Option(...),
    assignee: str = typer.Option(None),
    priority: str = typer.Option("P2"),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    task = tasks.create_task(
        workspace,
        team_name,
        title=title,
        description=description,
        created_by=created_by,
        assignee=assignee,
        priority=priority,  # type: ignore[arg-type]
    )
    typer.echo(json.dumps(task.to_json()))


@team_app.command("task-list")
def task_list_cmd(
    team_name: str = typer.Option(...),
    status: str = typer.Option("open,claimed,in_progress,blocked"),
    limit: int = typer.Option(50),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    items = tasks.list_tasks(
        workspace,
        team_name,
        status_filter=[s for s in status.split(",") if s],
        limit=limit,
    )
    typer.echo(json.dumps({"count": len(items), "tasks": [t.to_json() for t in items]}))


@team_app.command("status")
def status_cmd(
    team_name: str = typer.Option(...),
    include_stopped: bool = typer.Option(False),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Print team status via the team_status tool."""
    from .tools import team_status

    ctx = TeamContext.build(
        workspace=workspace,
        team_name=team_name,
        agent_name=registry.load_team_file(workspace, team_name).lead,
        role="lead",
        is_lead=True,
    )
    token = set_current_team_context(ctx)
    try:
        payload = team_status.invoke({"include_stopped": include_stopped})
    finally:
        from .context import reset_team_context

        reset_team_context(token)
    typer.echo(payload)


@team_app.command("delete")
def delete_cmd(
    team_name: str = typer.Option(...),
    cascade: bool = typer.Option(True),
    archive: bool = typer.Option(True),
    workspace: Path = typer.Option(WORKSPACE_DIR),
) -> None:
    """Delete a team via the team_delete tool (lead-only)."""
    from .tools import team_delete

    ctx = TeamContext.build(
        workspace=workspace,
        team_name=team_name,
        agent_name=registry.load_team_file(workspace, team_name).lead,
        role="lead",
        is_lead=True,
    )
    token = set_current_team_context(ctx)
    try:
        payload = team_delete.invoke(
            {"team_name": team_name, "cascade": cascade, "archive": archive}
        )
    finally:
        from .context import reset_team_context

        reset_team_context(token)
    typer.echo(payload)


__all__ = ["team_app"]
