"""Meta-harness — pure LangChain/LangGraph implementation.

Runs the architect · engineer · curator · evaluator · qa · synthesizer team
through a Supervisor-routed StateGraph. No Claude Code CLI required.
"""

from __future__ import annotations

from .orchestrator import MetaHarness, run_meta_harness
from .schemas import ImprovementCard, RoleDef, TaskComplexity, TaskDomain, TaskSpec

__all__ = [
    "MetaHarness",
    "run_meta_harness",
    "TaskSpec",
    "TaskDomain",
    "TaskComplexity",
    "RoleDef",
    "ImprovementCard",
]
