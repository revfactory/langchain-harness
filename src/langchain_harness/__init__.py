"""Multi-DeepAgent Team runtime on LangChain + Anthropic Claude Opus 4.7.

Single execution path:
- `AgentTeamHarness(team_name=...).start()` — multiple DeepAgent instances
  coordinating via file-backed mailbox and shared task queue.
"""

from __future__ import annotations

from .config import MODEL_ID
from .repl import ReplSession, run_repl
from .team import (
    AgentTeamHarness,
    TEAM_TOOLS,
    TeamContext,
    current_team_context,
    team_middleware_stack,
)

__all__ = [
    "AgentTeamHarness",
    "TEAM_TOOLS",
    "TeamContext",
    "current_team_context",
    "team_middleware_stack",
    "MODEL_ID",
    "ReplSession",
    "run_repl",
]
__version__ = "0.4.0"
