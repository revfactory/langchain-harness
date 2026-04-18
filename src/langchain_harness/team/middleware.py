"""Team-only middleware — TeamContext injection + inbox poll.

Spec §13 middleware interactions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import middleware as base_middleware
from . import mailbox as mailbox_mod
from .context import current_team_context


@dataclass
class TeamContextMiddleware:
    """Inject ``[YOU ARE agent@team]`` identity into the system prompt once."""

    _injected: bool = False

    def before_model(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if self._injected:
            return None
        try:
            ctx = current_team_context()
        except LookupError:
            return None
        self._injected = True
        header = (
            f"[YOU ARE {ctx.agent_id}] team={ctx.team_name} role={ctx.role} "
            f"is_lead={ctx.is_lead} workspace={ctx.workspace_team_dir}"
        )
        return {"messages": [{"role": "system", "content": header}]}


@dataclass
class InboxPollMiddleware:
    """Pre-model hook: drain unread inbox + surface as a system message."""

    poll_every_n_turns: int = 1
    inbox_soft_limit: int = 100
    max_items: int = 5

    def before_model(self, state: dict[str, Any]) -> dict[str, Any] | None:
        turn = state.get("_inbox_turn", 0)
        state["_inbox_turn"] = turn + 1
        if self.poll_every_n_turns > 0 and turn % self.poll_every_n_turns != 0:
            return None
        try:
            ctx = current_team_context()
        except LookupError:
            return None
        entries = mailbox_mod.read_entries(ctx.workspace, ctx.team_name, ctx.agent_name)
        unread = [e for e in entries if e.status == "unread"]
        if not unread:
            return None
        # F5 flood — log a flood_block event when over soft limit.
        if len(unread) > self.inbox_soft_limit:
            mailbox_mod.append_log(
                ctx.workspace,
                ctx.team_name,
                {
                    "kind": "flood_block",
                    "recipient": ctx.agent_name,
                    "pending": len(unread),
                },
            )
        subset = unread[: self.max_items]
        lines = [f"## Inbox ({len(unread)} unread, showing {len(subset)})"]
        for e in subset:
            lines.append(
                f"- [{e.kind}] from {e.sender} at {e.created_at} "
                f"(ack={e.requires_ack}): {e.body[:200]}"
            )
        mailbox_mod.mark_status(
            ctx.workspace,
            ctx.team_name,
            ctx.agent_name,
            [e.message_id for e in subset],
            "read",
        )
        return {"messages": [{"role": "system", "content": "\n".join(lines)}]}


def team_middleware_stack(
    workspace: Path,
    team_name: str,
    *,
    is_lead: bool = False,
    checklist: list[str] | None = None,
    coding_standards: str = "",
) -> list[Any]:
    """Build a middleware stack tuned for team execution.

    Reuses ``default_middleware_stack`` (single-agent), then inserts
    team-specific layers per §13.
    """
    team_agents_md = workspace / "teams" / team_name / "AGENTS.md"
    resolved_agents_md = team_agents_md if team_agents_md.exists() else None
    stack = base_middleware.default_middleware_stack(
        workspace=workspace,
        checklist=checklist,
        agents_md=resolved_agents_md,
        coding_standards=coding_standards,
    )
    # Extend LoopDetection coverage with message tools (§13).
    for mw in stack:
        if isinstance(mw, base_middleware.LoopDetectionMiddleware):
            mw.edit_tools = mw.edit_tools + ("send_message", "broadcast_message")
        if isinstance(mw, base_middleware.ReasoningBudgetMiddleware):
            # §13: plan_turns=2 in team mode — early alignment matters.
            mw.plan_turns = 2
        if isinstance(mw, base_middleware.TraceAnalysisMiddleware):
            mw.log_dir = workspace / "teams" / team_name / "runs"
    # Insert team context + inbox poll right after LocalContext (index 0).
    stack.insert(1, TeamContextMiddleware())
    stack.insert(2, InboxPollMiddleware())
    if is_lead:
        for mw in stack:
            if isinstance(mw, base_middleware.PreCompletionChecklistMiddleware):
                mw.checklist = list(mw.checklist) + [
                    "모든 멤버가 stopped 상태인가",
                    "보류된 task가 없는가",
                    "ack 미수신 메시지가 없는가",
                ]
    return stack


__all__ = [
    "TeamContextMiddleware",
    "InboxPollMiddleware",
    "team_middleware_stack",
]
