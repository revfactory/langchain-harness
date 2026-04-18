from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import MODEL_ID
from .schemas import TaskComplexity, TaskDomain, TaskSpec

_ANALYZER_SYSTEM = """You are the Task Analyzer of a meta-agent harness.

Classify the user's task and return a JSON TaskSpec with:
- domain: one of {code, research, data, writing, mixed}
- complexity: one of {trivial, moderate, complex, research}
- required_roles: subset of {architect, engineer, curator, evaluator, qa, synthesizer}
- success_criteria: 2-5 objective checks that define completion
- constraints: hard limits (tools, paths, time)
- max_turns: integer 5..40 (simple tasks 5, research-grade 30+)

Routing heuristics
- trivial  : answer is a single paragraph or single file edit → ["engineer"]
- moderate : multi-step code change, small research → ["architect","engineer","qa"] + "synthesizer"
- complex  : design + implement + review → ["architect","engineer","curator","qa","synthesizer"]
- research : long-horizon, needs improvement loop → add "evaluator"

Do not invent roles outside the allowed set. Be precise; return no prose.
"""


def _fallback_spec(task: str) -> TaskSpec:
    return TaskSpec(
        task=task,
        domain=TaskDomain.MIXED,
        complexity=TaskComplexity.MODERATE,
        required_roles=["architect", "engineer", "qa", "synthesizer"],
        success_criteria=["요구된 산출물이 생성되었는가"],
        constraints=[],
        max_turns=15,
    )


def analyze(task: str, *, model_id: str = MODEL_ID) -> TaskSpec:
    """Turn a free-form task into a structured TaskSpec.

    Uses structured output binding. On parse failure, returns a safe fallback
    spec instead of raising — the supervisor can still route a reasonable team.
    """
    llm = ChatAnthropic(model=model_id, max_tokens=2000).with_structured_output(
        TaskSpec, include_raw=False
    )
    try:
        spec = llm.invoke(
            [SystemMessage(content=_ANALYZER_SYSTEM), HumanMessage(content=task)]
        )
    except Exception:
        return _fallback_spec(task)

    if not spec.required_roles:
        return _fallback_spec(task)
    if "synthesizer" not in spec.required_roles:
        spec.required_roles.append("synthesizer")
    spec.task = task
    return spec
