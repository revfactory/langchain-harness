"""Runtime-configurable deep-agent harness on LangChain + Anthropic Claude Opus 4.7.

Two entrypoints:
- `create(HarnessConfig(...))` — single deep-agent (simple tasks).
- `MetaHarness().run(task)` — Supervisor-routed multi-role team (complex tasks).
"""

from __future__ import annotations

from .agent import HarnessConfig, create
from .config import MODEL_ID
from .meta import MetaHarness, run_meta_harness

__all__ = ["HarnessConfig", "create", "MODEL_ID", "MetaHarness", "run_meta_harness"]
__version__ = "0.2.0"
