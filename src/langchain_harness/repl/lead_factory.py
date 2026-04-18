"""Lead DeepAgent factory for the REPL.

The REPL user talks to the lead via mailbox. The lead is a DeepAgent with
TEAM_TOOLS so it can spawn teammates, assign tasks, and broadcast. It always
replies to the user by calling ``send_message(recipient='user', ...)``.
"""
from __future__ import annotations

import os
from typing import Literal

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver

from ..config import MODEL_ID
from ..team.context import TeamContext
from ..team.tools import TEAM_TOOLS

Effort = Literal["max", "xhigh", "high", "medium", "low"]
_VALID_EFFORT: set[str] = {"max", "xhigh", "high", "medium", "low"}

LEAD_SYSTEM_PROMPT = """\
You are the **team lead** of a Multi-DeepAgent Team running on LangChain + Claude Opus 4.7.
The end-user is registered in the team as agent_name=`user` and sends you messages through the shared mailbox.

# How to operate
- Every user turn arrives in your inbox as one or more messages from `user`.
- After reasoning and acting, you **must** reply to the user by calling the
  `send_message` tool with `recipient="user"` and a natural-language `body`.
- If the task is complex, you may spawn teammates (`spawn_teammate`), assign
  them work via `team_task_create`, and broadcast updates. Prefer lightweight
  in-process work for simple requests — don't over-engineer.
- Be concise and direct. The user sees your `send_message` body verbatim.
- Do not claim completion until you have sent a terminal message to `user`.

# Tooling
- `send_message(recipient="user", body=...)` is your *only* way to speak to the
  human. Internal notes, todos, and file writes do not reach the user.
- `team_status`, `team_task_list`, `read_inbox` are good for self-inspection.
- Filesystem/bash tools are available for reading/editing the project.

# Team identity
Your team_name and agent_name are injected by the runtime. Trust the ambient
TeamContext — you do not need to pass them as arguments.
"""


def _resolve_effort(explicit: str | None) -> Effort:
    # WHY: Opus 4.7 requires thinking.type='adaptive' with output_config.effort
    # (or the top-level `effort` param exposed by langchain-anthropic).
    candidate = explicit or os.getenv("LANGCHAIN_HARNESS_EFFORT", "medium")
    if candidate not in _VALID_EFFORT:
        candidate = "medium"
    return candidate  # type: ignore[return-value]


def build_lead_factory(
    *,
    extra_system_prompt: str = "",
    model_id: str | None = None,
    effort: str | None = None,
):
    """Return a ``Callable[[TeamContext], DeepAgent]`` for ``AgentTeamHarness.spawn``."""

    resolved_model = model_id or MODEL_ID
    resolved_effort = _resolve_effort(effort)

    def factory(ctx: TeamContext):
        model = ChatAnthropic(
            model=resolved_model,
            max_tokens=int(os.getenv("LANGCHAIN_HARNESS_MAX_TOKENS", "8192")),
            thinking={"type": "adaptive"},
            effort=resolved_effort,
        )
        prompt = LEAD_SYSTEM_PROMPT
        if extra_system_prompt:
            prompt = prompt.rstrip() + "\n\n" + extra_system_prompt.strip() + "\n"
        # WHY: the team runtime invokes the agent fresh on every tick. Without
        # a checkpointer the lead has amnesia between user turns. InMemorySaver
        # + thread_id=agent_id (passed by the runtime) keeps the conversation.
        agent = create_deep_agent(
            model=model,
            tools=list(TEAM_TOOLS),
            system_prompt=prompt,
            checkpointer=InMemorySaver(),
        )
        return agent

    return factory


__all__ = ["build_lead_factory", "LEAD_SYSTEM_PROMPT"]
