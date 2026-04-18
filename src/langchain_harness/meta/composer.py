from __future__ import annotations

from langchain_core.tools import BaseTool

from .roles import ROLES
from .schemas import TaskComplexity, TaskSpec

_COMPLEXITY_DEFAULTS: dict[TaskComplexity, list[str]] = {
    TaskComplexity.TRIVIAL: ["engineer", "synthesizer"],
    TaskComplexity.MODERATE: ["architect", "engineer", "qa", "synthesizer"],
    TaskComplexity.COMPLEX: ["architect", "engineer", "curator", "qa", "synthesizer"],
    TaskComplexity.RESEARCH_LVL: [
        "architect", "engineer", "curator", "evaluator", "qa", "synthesizer"
    ],
}


def resolve_roles(spec: TaskSpec) -> list[str]:
    """Pick roles to include. User-requested roles win; else use complexity default."""
    selected: list[str] = list(dict.fromkeys(spec.required_roles))
    if not selected:
        selected = list(_COMPLEXITY_DEFAULTS[spec.complexity])
    # enforce synthesizer as terminal aggregator
    if "synthesizer" not in selected:
        selected.append("synthesizer")
    # only keep known roles
    return [r for r in selected if r in ROLES]


def filter_tools(tools: list[BaseTool], role_name: str) -> list[BaseTool]:
    allowed = set(ROLES[role_name].tools)
    if not allowed:
        return []
    return [t for t in tools if t.name in allowed]
