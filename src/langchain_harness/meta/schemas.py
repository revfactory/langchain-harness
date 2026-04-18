from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TaskDomain(str, Enum):
    CODE = "code"
    RESEARCH = "research"
    DATA = "data"
    WRITING = "writing"
    MIXED = "mixed"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"      # 1 role, no supervisor
    MODERATE = "moderate"    # 2-3 roles
    COMPLEX = "complex"      # 4-5 roles
    RESEARCH_LVL = "research"  # full team + evolution loop


class TaskSpec(BaseModel):
    """Structured output of the Analyzer. Drives graph composition."""

    task: str = Field(description="Original user task verbatim.")
    domain: TaskDomain = Field(description="Top-level domain of the task.")
    complexity: TaskComplexity = Field(description="Routing complexity tier.")
    required_roles: list[str] = Field(
        default_factory=list,
        description="Subset of [architect, engineer, curator, evaluator, qa, synthesizer].",
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        description="2-5 objective checks that define completion.",
    )
    constraints: list[str] = Field(
        default_factory=list, description="Hard limits: tool bans, time budget, paths."
    )
    max_turns: int = Field(default=20, description="Maximum supervisor-routed turns.")


class RoleDef(BaseModel):
    """Definition of a specialist role within the meta-harness."""

    name: str
    description: str
    system_prompt: str
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names this role may invoke (filtered from the registry).",
    )


class ImprovementCard(BaseModel):
    """A single actionable proposal produced by the Evaluator."""

    hypothesis: str = Field(description="What we believe is causing the failure mode.")
    target_component: str = Field(
        description="File/module to change, e.g. 'meta/orchestrator.py:_supervisor_node'."
    )
    change: str = Field(description="Concrete change, as minimal diff.")
    expected_metric: str = Field(
        description="What measurable should move, and by how much."
    )
    risk: str = Field(description="Regression risk or side-effect to monitor.")
    rollback_condition: str = Field(
        description="Signal under which this card must be reverted."
    )
