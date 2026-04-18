"""Multi-DeepAgent team runtime — public API.

See ``_workspace/01_team_architect_spec.md`` v1.0 for the full contract.
"""
from __future__ import annotations

from .context import (
    TeamContext,
    current_team_context,
    reset_team_context,
    set_current_team_context,
)
from .middleware import (
    InboxPollMiddleware,
    TeamContextMiddleware,
    team_middleware_stack,
)
from .registry import (
    atomic_write_json,
    ensure_team_dirs,
    load_team_file,
    save_team_file,
    team_dir,
)
from .runtime import AgentTeamHarness
from .tools import TEAM_TOOLS, team_extras_tools
from .types import (
    CycleError,
    MailboxEntry,
    MailboxPolicy,
    MemberState,
    MessageKind,
    NameConflictError,
    PermissionDeniedError,
    TaskStatus,
    TeamAlreadyExistsError,
    TeamDirectoryExistsError,
    TeamFile,
    TeamMember,
    TeamTask,
    VersionConflictError,
)

__all__ = [
    # runtime / ctx
    "AgentTeamHarness",
    "TeamContext",
    "current_team_context",
    "set_current_team_context",
    "reset_team_context",
    # middleware
    "TeamContextMiddleware",
    "InboxPollMiddleware",
    "team_middleware_stack",
    # tools
    "TEAM_TOOLS",
    "team_extras_tools",
    # registry helpers
    "atomic_write_json",
    "ensure_team_dirs",
    "team_dir",
    "load_team_file",
    "save_team_file",
    # types
    "MailboxEntry",
    "MailboxPolicy",
    "MemberState",
    "MessageKind",
    "TaskStatus",
    "TeamFile",
    "TeamMember",
    "TeamTask",
    # errors
    "CycleError",
    "NameConflictError",
    "PermissionDeniedError",
    "TeamAlreadyExistsError",
    "TeamDirectoryExistsError",
    "VersionConflictError",
]
