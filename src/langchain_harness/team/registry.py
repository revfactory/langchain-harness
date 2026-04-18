"""Team filesystem layout + atomic writes for config.json / tasks/*.json.

Spec §4 file layout and §5 concurrency strategy. All rewrite paths use
``fcntl.flock`` + tmp-rename + version CAS. JSONL append paths rely on
``O_APPEND`` for line atomicity (kept in mailbox.py / log helpers below).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import (
    MailboxPolicy,
    TeamAlreadyExistsError,
    TeamDirectoryExistsError,
    TeamFile,
    TeamMember,
    VersionConflictError,
)

# WHY: spec §8 — identifier regexes. 파일 경로에 직접 들어가므로 ReDoS 걱정 없이 str 단정.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_name(name: str, kind: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid {kind}={name!r}: must match ^[a-z][a-z0-9_-]{{1,31}}$"
        )


# ---------- layout --------------------------------------------------------


def teams_root(workspace: Path) -> Path:
    return workspace / "teams"


def team_dir(workspace: Path, team_name: str) -> Path:
    validate_name(team_name, "team_name")
    return teams_root(workspace) / team_name


def config_path(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "config.json"


def mailbox_dir(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "mailbox"


def mailbox_file(workspace: Path, team_name: str, agent_name: str) -> Path:
    validate_name(agent_name, "agent_name")
    return mailbox_dir(workspace, team_name) / f"{agent_name}.jsonl"


def broadcast_log(workspace: Path, team_name: str) -> Path:
    return mailbox_dir(workspace, team_name) / "_broadcast.jsonl"


def payloads_dir(workspace: Path, team_name: str) -> Path:
    return mailbox_dir(workspace, team_name) / "payloads"


def tasks_dir(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "tasks"


def tasks_index(workspace: Path, team_name: str) -> Path:
    return tasks_dir(workspace, team_name) / "_index.jsonl"


def task_path(workspace: Path, team_name: str, task_id: str) -> Path:
    return tasks_dir(workspace, team_name) / f"{task_id}.json"


def locks_dir(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "locks"


def logs_path(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "logs.jsonl"


def runs_dir(workspace: Path, team_name: str) -> Path:
    return team_dir(workspace, team_name) / "runs"


def ensure_team_dirs(workspace: Path, team_name: str) -> None:
    """Create all subdirectories used by the team. Idempotent."""
    for p in (
        team_dir(workspace, team_name),
        mailbox_dir(workspace, team_name),
        payloads_dir(workspace, team_name),
        tasks_dir(workspace, team_name),
        locks_dir(workspace, team_name),
        runs_dir(workspace, team_name),
    ):
        p.mkdir(parents=True, exist_ok=True)


# ---------- atomic json rewrite ------------------------------------------


def _lock_path_for(workspace: Path, team_name: str, stem: str) -> Path:
    return locks_dir(workspace, team_name) / f"{stem}.lock"


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    lock_path: Path,
    expected_version: int | None,
) -> int:
    """Rewrite ``path`` with ``payload`` under flock + tmp-rename + version CAS.

    Returns the new version. Raises ``VersionConflictError`` if
    ``expected_version`` does not match the on-disk value.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "r+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            current: dict[str, Any] | None = None
            if path.exists():
                try:
                    current = json.loads(path.read_text())
                except json.JSONDecodeError:
                    current = None
            current_version = int(current.get("version", 0)) if current else 0
            if expected_version is not None:
                if current is None:
                    # expected_version only meaningful when file exists
                    if expected_version != 0:
                        raise VersionConflictError(path, expected_version, None)
                elif current_version != expected_version:
                    raise VersionConflictError(path, expected_version, current_version)
            payload["version"] = current_version + 1
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            os.replace(tmp, path)
            return payload["version"]
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


# ---------- team file helpers --------------------------------------------


def load_team_file(workspace: Path, team_name: str) -> TeamFile:
    path = config_path(workspace, team_name)
    if not path.exists():
        raise FileNotFoundError(f"team config missing: {path}")
    data = json.loads(path.read_text())
    return TeamFile.from_json(data)


def save_team_file(
    workspace: Path,
    team_file: TeamFile,
    *,
    expected_version: int | None,
) -> int:
    path = config_path(workspace, team_file.team_name)
    lock = _lock_path_for(workspace, team_file.team_name, "config")
    return atomic_write_json(
        path,
        team_file.to_json(),
        lock_path=lock,
        expected_version=expected_version,
    )


# ---------- team lifecycle (create/delete) -------------------------------


_LIVE_TEAMS: set[str] = set()  # WHY: §8 — same host process uniqueness check.


def team_create(
    workspace: Path,
    *,
    team_name: str,
    lead_name: str,
    shared_objective: str,
    mailbox_soft_limit: int = 100,
    mailbox_hard_limit: int = 500,
    force: bool = False,
) -> TeamFile:
    validate_name(team_name, "team_name")
    validate_name(lead_name, "agent_name")
    if team_name in _LIVE_TEAMS and not force:
        raise TeamAlreadyExistsError(
            f"team {team_name!r} already registered in this process"
        )
    cfg = config_path(workspace, team_name)
    if cfg.exists() and not force:
        raise TeamDirectoryExistsError(f"team directory already exists: {cfg.parent}")
    ensure_team_dirs(workspace, team_name)
    lead = TeamMember(
        agent_name=lead_name,
        agent_id=f"{lead_name}@{team_name}",
        role="lead",
        model_id="claude-opus-4-7",
        tools=[],
        state="spawning",
        spawned_at=_now_iso(),
        last_heartbeat=_now_iso(),
        pid=os.getpid(),
        thread_id=None,
        parent=None,
        current_task_id=None,
        metadata={},
    )
    tf = TeamFile(
        team_name=team_name,
        created_at=_now_iso(),
        lead=lead_name,
        members=[lead],
        shared_objective=shared_objective,
        mailbox_policy=MailboxPolicy(
            soft_limit=mailbox_soft_limit,
            hard_limit=mailbox_hard_limit,
        ),
        version=0,
    )
    save_team_file(workspace, tf, expected_version=None)
    # WHY: create empty mailbox for lead so read_inbox never sees ENOENT.
    mailbox_file(workspace, team_name, lead_name).touch(exist_ok=True)
    _LIVE_TEAMS.add(team_name)
    return load_team_file(workspace, team_name)


def team_forget(team_name: str) -> None:
    """Remove team from the in-process registry (used by tests / delete)."""
    _LIVE_TEAMS.discard(team_name)


__all__ = [
    "validate_name",
    "teams_root",
    "team_dir",
    "config_path",
    "mailbox_dir",
    "mailbox_file",
    "broadcast_log",
    "payloads_dir",
    "tasks_dir",
    "tasks_index",
    "task_path",
    "locks_dir",
    "logs_path",
    "runs_dir",
    "ensure_team_dirs",
    "atomic_write_json",
    "load_team_file",
    "save_team_file",
    "team_create",
    "team_forget",
]
