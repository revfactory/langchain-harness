"""Team task queue — create / claim / update / list with CAS + DAG check.

Spec §3.4 TeamTask, §4 task layout, §5 CAS strategy, §6 task_assigned
protocol hooks, F4 cycle detection.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import mailbox, registry
from .types import (
    CycleError,
    TaskPriority,
    TaskStatus,
    TeamTask,
    VersionConflictError,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_for_task(workspace: Path, team_name: str, task_id: str) -> Path:
    return registry.locks_dir(workspace, team_name) / f"task_{task_id}.lock"


def _load(workspace: Path, team_name: str, task_id: str) -> TeamTask:
    path = registry.task_path(workspace, team_name, task_id)
    if not path.exists():
        raise FileNotFoundError(f"task not found: {task_id}")
    return TeamTask.from_json(json.loads(path.read_text()))


def get_task(workspace: Path, team_name: str, task_id: str) -> TeamTask:
    return _load(workspace, team_name, task_id)


def _append_index(workspace: Path, team_name: str, event: dict[str, Any]) -> None:
    event.setdefault("ts", _now_iso())
    mailbox._append_line(
        registry.tasks_index(workspace, team_name),
        json.dumps(event, ensure_ascii=False),
    )


def _would_cycle(
    workspace: Path,
    team_name: str,
    candidate_id: str,
    depends_on: list[str],
) -> list[str] | None:
    """Return the cycle path if adding ``candidate_id`` with ``depends_on``
    would produce a cycle, else None.

    Two cases are detected:
      (a) the candidate itself appears in the transitive closure of
          ``depends_on`` (standard self-inclusion cycle), and
      (b) the existing graph already contains a cycle within
          ``depends_on``'s transitive closure. Per spec §F4 the second case
          must also be refused so downstream planners never see a broken DAG.
    """
    def _walk(start: str) -> list[str] | None:
        stack: list[tuple[str, list[str], set[str]]] = [
            (start, [candidate_id, start], {candidate_id, start})
        ]
        while stack:
            cur, path, on_path = stack.pop()
            try:
                t = _load(workspace, team_name, cur)
            except FileNotFoundError:
                continue
            for nxt in t.depends_on:
                if nxt == candidate_id:
                    return path + [nxt]
                if nxt in on_path:
                    return path + [nxt]
                stack.append((nxt, path + [nxt], on_path | {nxt}))
        return None

    for d in depends_on:
        if d == candidate_id:
            return [candidate_id, d]
        found = _walk(d)
        if found is not None:
            return found
    return None


def create_task(
    workspace: Path,
    team_name: str,
    *,
    title: str,
    description: str,
    created_by: str,
    assignee: str | None = None,
    priority: TaskPriority = "P2",
    depends_on: list[str] | None = None,
) -> TeamTask:
    registry.ensure_team_dirs(workspace, team_name)
    deps = list(depends_on or [])
    task_id = uuid.uuid4().hex[:12]
    cycle = _would_cycle(workspace, team_name, task_id, deps)
    if cycle is not None:
        raise CycleError(cycle)
    task = TeamTask(
        task_id=task_id,
        title=title,
        description=description,
        created_by=created_by,
        assignee=assignee,
        status="open",
        priority=priority,
        depends_on=deps,
        version=0,
    )
    path = registry.task_path(workspace, team_name, task_id)
    lock = _lock_for_task(workspace, team_name, task_id)
    registry.atomic_write_json(
        path,
        task.to_json(),
        lock_path=lock,
        expected_version=None,
    )
    _append_index(
        workspace,
        team_name,
        {"kind": "task_created", "task_id": task_id, "created_by": created_by},
    )
    mailbox.append_log(
        workspace,
        team_name,
        {"kind": "task_created", "task_id": task_id, "created_by": created_by},
    )
    return _load(workspace, team_name, task_id)


def claim_task(
    workspace: Path,
    team_name: str,
    task_id: str,
    *,
    claimed_by: str,
    expected_status: TaskStatus = "open",
) -> TeamTask:
    """CAS claim. Raises ``VersionConflictError`` if state diverged."""
    task = _load(workspace, team_name, task_id)
    if task.status != expected_status:
        raise VersionConflictError(
            registry.task_path(workspace, team_name, task_id),
            expected=task.version,
            actual=task.version,
        )
    task.status = "claimed"
    task.claimed_by = claimed_by
    task.claimed_at = _now_iso()
    task.updated_at = _now_iso()
    path = registry.task_path(workspace, team_name, task_id)
    lock = _lock_for_task(workspace, team_name, task_id)
    try:
        registry.atomic_write_json(
            path,
            task.to_json(),
            lock_path=lock,
            expected_version=task.version,
        )
    except VersionConflictError:
        raise
    mailbox.append_log(
        workspace,
        team_name,
        {"kind": "task_claimed", "task_id": task_id, "claimed_by": claimed_by},
    )
    return _load(workspace, team_name, task_id)


def update_task(
    workspace: Path,
    team_name: str,
    task_id: str,
    *,
    new_status: TaskStatus,
    expected_version: int,
    result_summary: str | None = None,
    artifacts: list[str] | None = None,
    updated_by: str | None = None,
) -> TeamTask:
    task = _load(workspace, team_name, task_id)
    if task.version != expected_version:
        raise VersionConflictError(
            registry.task_path(workspace, team_name, task_id),
            expected=expected_version,
            actual=task.version,
        )
    task.status = new_status
    task.updated_at = _now_iso()
    if result_summary is not None:
        task.result_summary = result_summary
    if artifacts:
        task.artifacts = list(artifacts)
    if new_status == "done":
        task.completed_at = _now_iso()
    path = registry.task_path(workspace, team_name, task_id)
    lock = _lock_for_task(workspace, team_name, task_id)
    registry.atomic_write_json(
        path,
        task.to_json(),
        lock_path=lock,
        expected_version=expected_version,
    )
    mailbox.append_log(
        workspace,
        team_name,
        {
            "kind": "task_updated",
            "task_id": task_id,
            "new_status": new_status,
            "updated_by": updated_by,
        },
    )
    return _load(workspace, team_name, task_id)


def list_tasks(
    workspace: Path,
    team_name: str,
    *,
    status_filter: list[str] | None = None,
    assignee_filter: str | None = None,
    limit: int = 50,
) -> list[TeamTask]:
    tdir = registry.tasks_dir(workspace, team_name)
    if not tdir.exists():
        return []
    items: list[TeamTask] = []
    for p in sorted(tdir.glob("*.json")):
        try:
            t = TeamTask.from_json(json.loads(p.read_text()))
        except (json.JSONDecodeError, KeyError):
            continue
        if status_filter and t.status not in status_filter:
            continue
        if assignee_filter and t.assignee != assignee_filter:
            continue
        items.append(t)
        if len(items) >= limit:
            break
    return items


__all__ = [
    "create_task",
    "claim_task",
    "update_task",
    "list_tasks",
    "get_task",
]
