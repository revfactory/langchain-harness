"""REPL session — team bootstrap, user pseudo-member, runtime lifecycle."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import WORKSPACE_DIR
from ..team import mailbox as mailbox_mod
from ..team import registry
from ..team.runtime import AgentTeamHarness
from ..team.types import (
    MailboxPolicy,
    TeamDirectoryExistsError,
    TeamFile,
    TeamMember,
    VersionConflictError,
)
from .lead_factory import build_lead_factory

USER_AGENT_NAME = "user"
DEFAULT_TEAM_NAME = "default"
DEFAULT_LEAD_NAME = "lead"
LAST_TEAM_FILE = ".repl_last_team"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_last_team(workspace: Path) -> str | None:
    path = workspace / LAST_TEAM_FILE
    if not path.exists():
        return None
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def _write_last_team(workspace: Path, team_name: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / LAST_TEAM_FILE).write_text(team_name)


def _register_user_member(workspace: Path, team_name: str) -> None:
    """Add the REPL user as a member if not already present."""
    tf = registry.load_team_file(workspace, team_name)
    if tf.find_member(USER_AGENT_NAME) is not None:
        return
    now = _now_iso()
    member = TeamMember(
        agent_name=USER_AGENT_NAME,
        agent_id=f"{USER_AGENT_NAME}@{team_name}",
        role="user",
        model_id="human",
        tools=[],
        state="alive",
        spawned_at=now,
        last_heartbeat=now,
        pid=os.getpid(),
        thread_id=None,
        parent=None,
        current_task_id=None,
        metadata={"is_repl_user": True},
    )
    tf.members.append(member)
    try:
        registry.save_team_file(workspace, tf, expected_version=tf.version)
    except VersionConflictError:
        # Re-read and retry once; orphan sweep and CAS collisions are benign.
        tf = registry.load_team_file(workspace, team_name)
        if tf.find_member(USER_AGENT_NAME) is None:
            tf.members.append(member)
            registry.save_team_file(workspace, tf, expected_version=tf.version)
    registry.mailbox_file(workspace, team_name, USER_AGENT_NAME).touch(exist_ok=True)


@dataclass
class ReplSession:
    workspace: Path = field(default_factory=lambda: WORKSPACE_DIR)
    team_name: str = DEFAULT_TEAM_NAME
    lead_name: str = DEFAULT_LEAD_NAME
    shared_objective: str = "Assist the user via natural-language conversation."
    isolation: str = "thread"
    harness: AgentTeamHarness | None = field(default=None, init=False)
    _started: bool = field(default=False, init=False)
    _mailbox_cursor: int = field(default=0, init=False)
    _logs_cursor: int = field(default=0, init=False)

    # ------------------------------------------------------------------
    # bootstrap
    # ------------------------------------------------------------------

    def ensure_team(self, *, resume: bool = True) -> TeamFile:
        cfg = registry.config_path(self.workspace, self.team_name)
        if cfg.exists():
            if not resume:
                raise TeamDirectoryExistsError(
                    f"team {self.team_name!r} already exists; use --resume or delete first"
                )
            tf = registry.load_team_file(self.workspace, self.team_name)
            self.lead_name = tf.lead
        else:
            tf = registry.team_create(
                self.workspace,
                team_name=self.team_name,
                lead_name=self.lead_name,
                shared_objective=self.shared_objective,
            )
        _register_user_member(self.workspace, self.team_name)
        _write_last_team(self.workspace, self.team_name)
        return registry.load_team_file(self.workspace, self.team_name)

    def start(self) -> None:
        if self._started:
            return
        tf = self.ensure_team(resume=True)
        self.lead_name = tf.lead
        # Seed cursors past any pre-existing content so we only stream new events.
        user_mbox = registry.mailbox_file(self.workspace, self.team_name, USER_AGENT_NAME)
        if user_mbox.exists():
            self._mailbox_cursor = user_mbox.stat().st_size
        logs = registry.logs_path(self.workspace, self.team_name)
        if logs.exists():
            self._logs_cursor = logs.stat().st_size

        self.harness = AgentTeamHarness(
            team_name=self.team_name,
            workspace=self.workspace,
            isolation="thread" if self.isolation == "thread" else "sequential",
        )
        self.harness.start()
        lead_member = tf.find_member(self.lead_name)
        if lead_member is None:
            raise RuntimeError(
                f"lead {self.lead_name!r} missing from team {self.team_name!r}"
            )
        factory = build_lead_factory()
        self.harness.spawn(lead_member, factory, is_lead=True)
        self._started = True

    def shutdown(self) -> None:
        if self.harness is not None and self._started:
            self.harness.shutdown(cascade=True)
        self._started = False

    # ------------------------------------------------------------------
    # user <-> lead messaging
    # ------------------------------------------------------------------

    def send_to_lead(self, body: str) -> str:
        if not self._started:
            self.start()
        entry = mailbox_mod.append_entry(
            self.workspace,
            self.team_name,
            sender=USER_AGENT_NAME,
            recipient=self.lead_name,
            body=body,
            kind="plain",
            ttl_seconds=None,
        )
        return entry.message_id

    # ------------------------------------------------------------------
    # cursors / streaming helpers
    # ------------------------------------------------------------------

    def _tail_lines(self, path: Path, cursor_attr: str) -> list[dict[str, Any]]:
        cursor = getattr(self, cursor_attr)
        if not path.exists():
            return []
        size = path.stat().st_size
        if size <= cursor:
            return []
        with path.open("rb") as f:
            f.seek(cursor)
            raw = f.read()
        setattr(self, cursor_attr, size)
        out: list[dict[str, Any]] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def drain_user_inbox(self) -> list[dict[str, Any]]:
        path = registry.mailbox_file(self.workspace, self.team_name, USER_AGENT_NAME)
        return self._tail_lines(path, "_mailbox_cursor")

    def drain_team_logs(self) -> list[dict[str, Any]]:
        path = registry.logs_path(self.workspace, self.team_name)
        return self._tail_lines(path, "_logs_cursor")

    # ------------------------------------------------------------------
    # lead state inspection
    # ------------------------------------------------------------------

    def lead_state(self) -> str | None:
        try:
            tf = registry.load_team_file(self.workspace, self.team_name)
        except FileNotFoundError:
            return None
        m = tf.find_member(self.lead_name)
        return m.state if m else None


def resolve_team_name(workspace: Path, requested: str | None) -> str:
    if requested:
        return requested
    last = _read_last_team(workspace)
    return last or DEFAULT_TEAM_NAME


__all__ = [
    "ReplSession",
    "USER_AGENT_NAME",
    "DEFAULT_TEAM_NAME",
    "DEFAULT_LEAD_NAME",
    "resolve_team_name",
]
