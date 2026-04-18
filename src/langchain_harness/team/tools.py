"""Team tool suite — 11 LangChain tools exposed to team members.

Spec §9 signatures. Each tool reads ambient ``TeamContext`` so the LLM never
has to pass team/agent identifiers explicitly. Authorization per §9 permission
table: elevated tools raise ``PermissionDeniedError`` when invoked by non-lead.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from . import mailbox as mailbox_mod
from . import registry, tasks
from .context import current_team_context
from .types import (
    MailboxPolicy,
    NameConflictError,
    PermissionDeniedError,
    TeamMember,
    VersionConflictError,
)

_NAME_PATTERN = r"^[a-z][a-z0-9_-]{1,31}$"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_lead(action: str) -> None:
    ctx = current_team_context()
    if not ctx.is_lead:
        raise PermissionDeniedError(
            f"{action} requires lead role (current={ctx.agent_name}@{ctx.team_name})"
        )


def _touch_heartbeat(workspace: Path, team_name: str, agent_name: str) -> None:
    """O3: heartbeat is refreshed on every tool call. No separate ping."""
    try:
        tf = registry.load_team_file(workspace, team_name)
    except FileNotFoundError:
        return
    member = tf.find_member(agent_name)
    if member is None:
        return
    member.last_heartbeat = _now_iso()
    try:
        registry.save_team_file(workspace, tf, expected_version=tf.version)
    except VersionConflictError:
        # WHY: heartbeat is best-effort — stale CAS is safe to drop, another
        # writer already refreshed the file.
        pass


# ---------- 9.1 team_create ----------------------------------------------


class TeamCreateArgs(BaseModel):
    team_name: str = Field(pattern=_NAME_PATTERN)
    lead_name: str = Field(pattern=_NAME_PATTERN)
    shared_objective: str
    mailbox_soft_limit: int = 100
    mailbox_hard_limit: int = 500
    force: bool = False


@tool(args_schema=TeamCreateArgs)
def team_create(
    team_name: str,
    lead_name: str,
    shared_objective: str,
    mailbox_soft_limit: int = 100,
    mailbox_hard_limit: int = 500,
    force: bool = False,
) -> str:
    """Create a new team directory and register the lead member.

    Elevated — typically invoked by host process, not by running members.
    """
    ctx = current_team_context()
    tf = registry.team_create(
        ctx.workspace,
        team_name=team_name,
        lead_name=lead_name,
        shared_objective=shared_objective,
        mailbox_soft_limit=mailbox_soft_limit,
        mailbox_hard_limit=mailbox_hard_limit,
        force=force,
    )
    return json.dumps({"team_name": tf.team_name, "lead": tf.lead, "version": tf.version})


# ---------- 9.2 team_delete ----------------------------------------------


class TeamDeleteArgs(BaseModel):
    team_name: str = Field(pattern=_NAME_PATTERN)
    cascade: bool = True
    archive: bool = True


@tool(args_schema=TeamDeleteArgs)
def team_delete(team_name: str, cascade: bool = True, archive: bool = True) -> str:
    """Delete a team. Elevated; lead only."""
    _require_lead("team_delete")
    ctx = current_team_context()
    tdir = registry.team_dir(ctx.workspace, team_name)
    if not tdir.exists():
        return json.dumps({"ok": False, "reason": "not_found"})
    if cascade:
        tf = registry.load_team_file(ctx.workspace, team_name)
        for m in tf.members:
            if m.state not in {"stopped", "orphan"}:
                m.state = "stopped"
        registry.save_team_file(ctx.workspace, tf, expected_version=tf.version)
    archive_path: str | None = None
    if archive:
        import tarfile

        archive_path = str(tdir.parent / f"{team_name}.tar.gz")
        with tarfile.open(archive_path, "w:gz") as tf_out:
            tf_out.add(tdir, arcname=team_name)
    # WHY: we keep directory by default when archive=True; else remove.
    if not archive:
        import shutil

        shutil.rmtree(tdir)
    registry.team_forget(team_name)
    return json.dumps({"ok": True, "archive": archive_path})


# ---------- 9.3 spawn_teammate -------------------------------------------


class SpawnTeammateArgs(BaseModel):
    name: str = Field(pattern=_NAME_PATTERN)
    role: Literal["engineer", "reviewer", "researcher", "custom"]
    tools: list[str] = Field(default_factory=list)
    system_prompt_fragment: str = ""
    model_id: str = "claude-opus-4-7"


@tool(args_schema=SpawnTeammateArgs)
def spawn_teammate(
    name: str,
    role: Literal["engineer", "reviewer", "researcher", "custom"],
    tools: list[str] | None = None,
    system_prompt_fragment: str = "",
    model_id: str = "claude-opus-4-7",
) -> str:
    """Register a new team member entry. Lead only.

    This records the member in config.json and creates an empty mailbox.
    Actual agent loop attach happens via ``AgentTeamHarness.spawn``.
    """
    _require_lead("spawn_teammate")
    ctx = current_team_context()
    tf = registry.load_team_file(ctx.workspace, ctx.team_name)
    if tf.find_member(name) is not None:
        raise NameConflictError(f"agent_name {name!r} already exists in {ctx.team_name}")
    member = TeamMember(
        agent_name=name,
        agent_id=f"{name}@{ctx.team_name}",
        role=role,
        model_id=model_id,
        tools=list(tools or []),
        state="spawning",
        spawned_at=_now_iso(),
        last_heartbeat=_now_iso(),
        pid=os.getpid(),
        thread_id=None,
        parent=ctx.agent_name,
        current_task_id=None,
        metadata={"system_prompt_fragment": system_prompt_fragment},
    )
    tf.members.append(member)
    registry.save_team_file(ctx.workspace, tf, expected_version=tf.version)
    registry.mailbox_file(ctx.workspace, ctx.team_name, name).touch(exist_ok=True)
    mailbox_mod.append_log(
        ctx.workspace,
        ctx.team_name,
        {"kind": "spawn_requested", "agent_name": name, "role": role, "parent": ctx.agent_name},
    )
    return json.dumps({"ok": True, "agent_name": name, "role": role})


# ---------- 9.4 send_message ---------------------------------------------


class SendMessageArgs(BaseModel):
    recipient: str = Field(pattern=_NAME_PATTERN)
    body: str
    kind: Literal[
        "plain",
        "task_assigned",
        "plan_approval_request",
        "shutdown_request",
        "plan_approval_response",
        "shutdown_response",
        "task_completed",
    ] = "plain"
    reply_to: str | None = None
    requires_ack: bool = False
    ttl_seconds: int | None = 60


@tool(args_schema=SendMessageArgs)
def send_message(
    recipient: str,
    body: str,
    kind: str = "plain",
    reply_to: str | None = None,
    requires_ack: bool = False,
    ttl_seconds: int | None = 60,
) -> str:
    """Send a p2p message to another team member."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    entry = mailbox_mod.append_entry(
        ctx.workspace,
        ctx.team_name,
        sender=ctx.agent_name,
        recipient=recipient,
        body=body,
        kind=kind,  # type: ignore[arg-type]
        reply_to=reply_to,
        requires_ack=requires_ack,
        ttl_seconds=ttl_seconds,
    )
    return json.dumps({"ok": True, "message_id": entry.message_id})


# ---------- 9.5 broadcast_message ----------------------------------------


class BroadcastMessageArgs(BaseModel):
    body: str
    kind: Literal["plain", "task_completed", "idle_escalation"] = "plain"
    exclude: list[str] = Field(default_factory=list)


@tool(args_schema=BroadcastMessageArgs)
def broadcast_message(
    body: str,
    kind: str = "plain",
    exclude: list[str] | None = None,
) -> str:
    """Broadcast a message to every teammate (except sender and excludes)."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    exclude_set = set(exclude or [])
    exclude_set.add(ctx.agent_name)
    # We fanout manually rather than using recipient="*" so we can apply `exclude`.
    tf = registry.load_team_file(ctx.workspace, ctx.team_name)
    sent: list[str] = []
    for m in tf.members:
        if m.agent_name in exclude_set:
            continue
        if m.state == "stopped":
            continue
        entry = mailbox_mod.append_entry(
            ctx.workspace,
            ctx.team_name,
            sender=ctx.agent_name,
            recipient=m.agent_name,
            body=body,
            kind=kind,  # type: ignore[arg-type]
            requires_ack=False,
            ttl_seconds=None,
        )
        sent.append(entry.message_id)
    mailbox_mod.append_log(
        ctx.workspace,
        ctx.team_name,
        {"kind": "broadcast", "sender": ctx.agent_name, "message_ids": sent},
    )
    return json.dumps({"ok": True, "count": len(sent), "message_ids": sent})


# ---------- 9.6 read_inbox -----------------------------------------------


class ReadInboxArgs(BaseModel):
    max_items: int = 20
    status_filter: Literal["unread", "read", "acked", "expired", "any"] = "unread"
    kind_filter: str | None = None
    mark_read: bool = True


@tool(args_schema=ReadInboxArgs)
def read_inbox(
    max_items: int = 20,
    status_filter: str = "unread",
    kind_filter: str | None = None,
    mark_read: bool = True,
) -> str:
    """Read messages from the caller's inbox."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    entries = mailbox_mod.read_entries(ctx.workspace, ctx.team_name, ctx.agent_name)
    out: list[dict[str, Any]] = []
    to_mark: list[str] = []
    for e in entries:
        if status_filter != "any" and e.status != status_filter:
            continue
        if kind_filter and e.kind != kind_filter:
            continue
        out.append(e.to_json())
        if mark_read and e.status == "unread":
            to_mark.append(e.message_id)
        if len(out) >= max_items:
            break
    if to_mark:
        mailbox_mod.mark_status(ctx.workspace, ctx.team_name, ctx.agent_name, to_mark, "read")
    return json.dumps({"count": len(out), "entries": out})


# ---------- 9.7 team_task_create -----------------------------------------


class TeamTaskCreateArgs(BaseModel):
    title: str
    description: str
    assignee: str | None = None
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    depends_on: list[str] = Field(default_factory=list)


@tool(args_schema=TeamTaskCreateArgs)
def team_task_create(
    title: str,
    description: str,
    assignee: str | None = None,
    priority: str = "P2",
    depends_on: list[str] | None = None,
) -> str:
    """Create a shared task on the team backlog."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    task = tasks.create_task(
        ctx.workspace,
        ctx.team_name,
        title=title,
        description=description,
        created_by=ctx.agent_name,
        assignee=assignee,
        priority=priority,  # type: ignore[arg-type]
        depends_on=depends_on,
    )
    return json.dumps({"ok": True, "task_id": task.task_id, "status": task.status})


# ---------- 9.8 team_task_claim ------------------------------------------


class TeamTaskClaimArgs(BaseModel):
    task_id: str
    expected_status: Literal["open"] = "open"


@tool(args_schema=TeamTaskClaimArgs)
def team_task_claim(task_id: str, expected_status: str = "open") -> str:
    """Atomically claim a task. Fails with VersionConflictError otherwise."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    task = tasks.claim_task(
        ctx.workspace,
        ctx.team_name,
        task_id,
        claimed_by=ctx.agent_name,
        expected_status=expected_status,  # type: ignore[arg-type]
    )
    return json.dumps({"ok": True, "task_id": task.task_id, "version": task.version})


# ---------- 9.9 team_task_update -----------------------------------------


class TeamTaskUpdateArgs(BaseModel):
    task_id: str
    new_status: Literal["in_progress", "blocked", "done", "cancelled"]
    expected_version: int
    result_summary: str | None = None
    artifacts: list[str] = Field(default_factory=list)


@tool(args_schema=TeamTaskUpdateArgs)
def team_task_update(
    task_id: str,
    new_status: str,
    expected_version: int,
    result_summary: str | None = None,
    artifacts: list[str] | None = None,
) -> str:
    """Update a task with CAS. Only the claimer can update."""
    ctx = current_team_context()
    _touch_heartbeat(ctx.workspace, ctx.team_name, ctx.agent_name)
    existing = tasks.get_task(ctx.workspace, ctx.team_name, task_id)
    if existing.claimed_by and existing.claimed_by != ctx.agent_name:
        raise PermissionDeniedError(
            f"task {task_id} claimed by {existing.claimed_by}, not {ctx.agent_name}"
        )
    task = tasks.update_task(
        ctx.workspace,
        ctx.team_name,
        task_id,
        new_status=new_status,  # type: ignore[arg-type]
        expected_version=expected_version,
        result_summary=result_summary,
        artifacts=artifacts,
        updated_by=ctx.agent_name,
    )
    return json.dumps(
        {"ok": True, "task_id": task.task_id, "status": task.status, "version": task.version}
    )


# ---------- 9.10 team_task_list ------------------------------------------


class TeamTaskListArgs(BaseModel):
    status_filter: list[str] = Field(
        default_factory=lambda: ["open", "claimed", "in_progress", "blocked"]
    )
    assignee_filter: str | None = None
    limit: int = 50


@tool(args_schema=TeamTaskListArgs)
def team_task_list(
    status_filter: list[str] | None = None,
    assignee_filter: str | None = None,
    limit: int = 50,
) -> str:
    """List tasks matching the filter."""
    ctx = current_team_context()
    if status_filter is None:
        status_filter = ["open", "claimed", "in_progress", "blocked"]
    items = tasks.list_tasks(
        ctx.workspace,
        ctx.team_name,
        status_filter=status_filter,
        assignee_filter=assignee_filter,
        limit=limit,
    )
    return json.dumps({"count": len(items), "tasks": [t.to_json() for t in items]})


# ---------- 9.11 team_status ---------------------------------------------


class TeamStatusArgs(BaseModel):
    include_stopped: bool = False
    include_logs_tail: int = 20
    heartbeat_ttl_sec: int = 120


@tool(args_schema=TeamStatusArgs)
def team_status(
    include_stopped: bool = False,
    include_logs_tail: int = 20,
    heartbeat_ttl_sec: int = 120,
) -> str:
    """Return a snapshot of team state (members, recent log events).

    heartbeat_ttl_sec should match AgentTeamHarness.heartbeat_ttl_sec to keep
    a single source of truth for orphan detection (spec §10, §14 H8).
    """
    ctx = current_team_context()
    tf = registry.load_team_file(ctx.workspace, ctx.team_name)
    now = datetime.now(timezone.utc)
    members_out: list[dict[str, Any]] = []
    for m in tf.members:
        if not include_stopped and m.state in {"stopped", "orphan"}:
            pass  # still may need orphan marking below before filtering
        try:
            hb = datetime.fromisoformat(m.last_heartbeat)
            stale = (now - hb).total_seconds() > heartbeat_ttl_sec
        except ValueError:
            stale = False
        if stale and m.state not in {"stopped", "orphan"}:
            m.state = "orphan"
            mailbox_mod.append_log(
                ctx.workspace,
                ctx.team_name,
                {"kind": "orphan_detected", "agent_name": m.agent_name},
            )
        if not include_stopped and m.state in {"stopped", "orphan"}:
            continue
        members_out.append(m.to_json())
    # persist any orphan state change; best-effort CAS
    try:
        registry.save_team_file(ctx.workspace, tf, expected_version=tf.version)
    except VersionConflictError:
        pass
    logs_tail: list[dict[str, Any]] = []
    logs_path = registry.logs_path(ctx.workspace, ctx.team_name)
    if logs_path.exists() and include_logs_tail > 0:
        lines = logs_path.read_text().splitlines()[-include_logs_tail:]
        for line in lines:
            try:
                logs_tail.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return json.dumps(
        {
            "team_name": tf.team_name,
            "lead": tf.lead,
            "version": tf.version,
            "members": members_out,
            "logs_tail": logs_tail,
        }
    )


TEAM_TOOLS = [
    team_create,
    team_delete,
    spawn_teammate,
    send_message,
    broadcast_message,
    read_inbox,
    team_task_create,
    team_task_claim,
    team_task_update,
    team_task_list,
    team_status,
]


def team_extras_tools() -> list[Any]:
    """WHY §12: exported only for team path so single-agent path stays lean."""
    return list(TEAM_TOOLS)


__all__ = [
    "TEAM_TOOLS",
    "team_extras_tools",
    "team_create",
    "team_delete",
    "spawn_teammate",
    "send_message",
    "broadcast_message",
    "read_inbox",
    "team_task_create",
    "team_task_claim",
    "team_task_update",
    "team_task_list",
    "team_status",
]
