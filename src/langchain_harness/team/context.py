"""TeamContext — thread/process-safe ambient context for team tools.

Spec §11 hybrid (ContextVar + env-var fallback).
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from . import registry


@dataclass(slots=True, frozen=True)
class TeamContext:
    team_name: str
    agent_name: str
    agent_id: str
    role: str
    workspace: Path
    workspace_team_dir: Path
    is_lead: bool

    @classmethod
    def build(
        cls,
        *,
        workspace: Path,
        team_name: str,
        agent_name: str,
        role: str,
        is_lead: bool,
    ) -> TeamContext:
        return cls(
            team_name=team_name,
            agent_name=agent_name,
            agent_id=f"{agent_name}@{team_name}",
            role=role,
            workspace=workspace,
            workspace_team_dir=registry.team_dir(workspace, team_name),
            is_lead=is_lead,
        )


_current_team_ctx: ContextVar[TeamContext | None] = ContextVar(
    "langchain_harness_team_ctx", default=None
)


def set_current_team_context(ctx: TeamContext | None) -> object:
    """Set ambient TeamContext for this thread/task. Returns a reset token."""
    return _current_team_ctx.set(ctx)


def reset_team_context(token: object) -> None:
    _current_team_ctx.reset(token)  # type: ignore[arg-type]


def current_team_context() -> TeamContext:
    """Return the active TeamContext, falling back to environment variables.

    Raises ``LookupError`` if no context is available. The env fallback path
    is used by the process-isolation mode (§10-C / §11-1).
    """
    ctx = _current_team_ctx.get()
    if ctx is not None:
        return ctx
    team = os.environ.get("CLAUDE_CODE_TEAM_NAME")
    name = os.environ.get("CLAUDE_CODE_AGENT_NAME")
    if not team or not name:
        raise LookupError(
            "No active TeamContext — call set_current_team_context or set "
            "CLAUDE_CODE_TEAM_NAME / CLAUDE_CODE_AGENT_NAME env vars."
        )
    workspace = Path(os.environ.get("CLAUDE_CODE_WORKSPACE", "_workspace"))
    team_file = registry.load_team_file(workspace, team)
    member = team_file.find_member(name)
    if member is None:
        raise LookupError(f"agent_name {name!r} not registered in team {team!r}")
    ctx = TeamContext.build(
        workspace=workspace,
        team_name=team,
        agent_name=name,
        role=member.role,
        is_lead=(team_file.lead == name),
    )
    _current_team_ctx.set(ctx)
    return ctx


__all__ = [
    "TeamContext",
    "current_team_context",
    "set_current_team_context",
    "reset_team_context",
]
