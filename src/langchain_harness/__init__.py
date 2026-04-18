"""Runtime-configurable deep-agent harness on LangChain + Anthropic Claude Opus 4.7."""

from __future__ import annotations

from .agent import HarnessConfig, create
from .config import MODEL_ID

__all__ = ["HarnessConfig", "create", "MODEL_ID"]
__version__ = "0.1.0"
