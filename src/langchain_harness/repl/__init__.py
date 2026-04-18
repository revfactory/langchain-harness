"""Natural-language REPL for the Multi-DeepAgent Team runtime.

`langchain-harness` (no subcommand) drops into an interactive shell where the
user types natural language and talks to the team lead via the mailbox, much
like Claude Code. Slash commands (`/help`, `/team`, `/spawn`, ...) handle team
lifecycle and inspection.
"""
from __future__ import annotations

from .app import run_repl
from .session import ReplSession

__all__ = ["run_repl", "ReplSession"]
