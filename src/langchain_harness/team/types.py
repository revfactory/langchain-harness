"""Team runtime data model — dataclasses + exceptions.

Mirrors spec §3 (TeamFile, TeamMember, MailboxEntry, TeamTask, MailboxPolicy)
and §8 identifier contracts. All dataclasses use ``slots=True`` and expose
``to_json``/``from_json`` helpers so that rewrite paths stay explicit and we
avoid pickling random attributes into team artifacts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# WHY Literal aliases: reuse across dataclass + tool args_schema to avoid typos.
MessageKind = Literal[
    "plain",
    "shutdown_request",
    "shutdown_response",
    "task_assigned",
    "task_completed",
    "plan_approval_request",
    "plan_approval_response",
    "idle_escalation",
    "heartbeat_ping",
]

MessageStatus = Literal["unread", "read", "acked", "expired"]

MemberState = Literal[
    "spawning",
    "alive",
    "idle",
    "paused",
    "stopping",
    "stopped",
    "orphan",
]

TaskStatus = Literal[
    "open",
    "claimed",
    "in_progress",
    "blocked",
    "done",
    "cancelled",
]

TaskPriority = Literal["P0", "P1", "P2", "P3"]


# ---------- exceptions ----------------------------------------------------


class TeamError(Exception):
    """Base class for all team runtime errors."""


class VersionConflictError(TeamError):
    """Raised when an expected version does not match the on-disk value."""

    def __init__(self, path: Any, expected: int | None, actual: int | None) -> None:
        super().__init__(
            f"version conflict at {path}: expected={expected}, actual={actual}"
        )
        self.path = path
        self.expected = expected
        self.actual = actual


class NameConflictError(TeamError):
    """Raised when an agent_name is already present in the team registry."""


class TeamAlreadyExistsError(TeamError):
    """Raised when creating a team that already exists in this host process."""


class TeamDirectoryExistsError(TeamError):
    """Raised when an on-disk team directory already exists (foreign host)."""


class PermissionDeniedError(TeamError):
    """Raised when a non-lead attempts a lead-only tool."""


class CycleError(TeamError):
    """Raised when task dependency graph contains a cycle."""

    def __init__(self, path: list[str]) -> None:
        super().__init__(f"cycle via {' -> '.join(path)}")
        self.path = path


# ---------- dataclasses ---------------------------------------------------


@dataclass(slots=True)
class MailboxPolicy:
    soft_limit: int = 100
    hard_limit: int = 500
    default_ttl_seconds: int = 60

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MailboxPolicy:
        return cls(
            soft_limit=int(data.get("soft_limit", 100)),
            hard_limit=int(data.get("hard_limit", 500)),
            default_ttl_seconds=int(data.get("default_ttl_seconds", 60)),
        )


@dataclass(slots=True)
class TeamMember:
    agent_name: str
    agent_id: str
    role: str
    model_id: str
    tools: list[str]
    state: MemberState
    spawned_at: str
    last_heartbeat: str
    pid: int | None = None
    thread_id: str | None = None
    parent: str | None = None
    current_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TeamMember:
        return cls(
            agent_name=data["agent_name"],
            agent_id=data["agent_id"],
            role=data["role"],
            model_id=data["model_id"],
            tools=list(data.get("tools", [])),
            state=data["state"],
            spawned_at=data["spawned_at"],
            last_heartbeat=data["last_heartbeat"],
            pid=data.get("pid"),
            thread_id=data.get("thread_id"),
            parent=data.get("parent"),
            current_task_id=data.get("current_task_id"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class TeamFile:
    team_name: str
    created_at: str
    lead: str
    members: list[TeamMember]
    shared_objective: str
    mailbox_policy: MailboxPolicy
    version: int = 0
    schema_version: str = "1.0"

    def to_json(self) -> dict[str, Any]:
        return {
            "team_name": self.team_name,
            "created_at": self.created_at,
            "lead": self.lead,
            "members": [m.to_json() for m in self.members],
            "shared_objective": self.shared_objective,
            "mailbox_policy": self.mailbox_policy.to_json(),
            "version": self.version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TeamFile:
        return cls(
            team_name=data["team_name"],
            created_at=data["created_at"],
            lead=data["lead"],
            members=[TeamMember.from_json(m) for m in data.get("members", [])],
            shared_objective=data.get("shared_objective", ""),
            mailbox_policy=MailboxPolicy.from_json(data.get("mailbox_policy", {})),
            version=int(data.get("version", 0)),
            schema_version=data.get("schema_version", "1.0"),
        )

    def find_member(self, agent_name: str) -> TeamMember | None:
        for m in self.members:
            if m.agent_name == agent_name:
                return m
        return None


@dataclass(slots=True)
class MailboxEntry:
    message_id: str
    sender: str
    recipient: str
    kind: MessageKind
    body: str
    created_at: str
    reply_to: str | None = None
    requires_ack: bool = False
    status: MessageStatus = "unread"
    ttl_seconds: int | None = None
    body_ref: str | None = None  # O1: overflow payload path when body>4KB

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MailboxEntry:
        return cls(
            message_id=data["message_id"],
            sender=data["sender"],
            recipient=data["recipient"],
            kind=data["kind"],
            body=data.get("body", ""),
            created_at=data["created_at"],
            reply_to=data.get("reply_to"),
            requires_ack=bool(data.get("requires_ack", False)),
            status=data.get("status", "unread"),
            ttl_seconds=data.get("ttl_seconds"),
            body_ref=data.get("body_ref"),
        )


@dataclass(slots=True)
class TeamTask:
    task_id: str
    title: str
    description: str
    created_by: str
    assignee: str | None
    status: TaskStatus
    priority: TaskPriority = "P2"
    depends_on: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    claimed_by: str | None = None
    claimed_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    version: int = 0
    result_summary: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TeamTask:
        return cls(
            task_id=data["task_id"],
            title=data["title"],
            description=data.get("description", ""),
            created_by=data["created_by"],
            assignee=data.get("assignee"),
            status=data["status"],
            priority=data.get("priority", "P2"),
            depends_on=list(data.get("depends_on", [])),
            artifacts=list(data.get("artifacts", [])),
            claimed_by=data.get("claimed_by"),
            claimed_at=data.get("claimed_at"),
            updated_at=data.get("updated_at"),
            completed_at=data.get("completed_at"),
            version=int(data.get("version", 0)),
            result_summary=data.get("result_summary"),
        )


__all__ = [
    "MessageKind",
    "MessageStatus",
    "MemberState",
    "TaskStatus",
    "TaskPriority",
    "MailboxPolicy",
    "TeamMember",
    "TeamFile",
    "MailboxEntry",
    "TeamTask",
    "TeamError",
    "VersionConflictError",
    "NameConflictError",
    "TeamAlreadyExistsError",
    "TeamDirectoryExistsError",
    "PermissionDeniedError",
    "CycleError",
]
