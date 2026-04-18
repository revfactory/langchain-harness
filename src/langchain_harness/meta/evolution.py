from __future__ import annotations

from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import MODEL_ID
from .memory import MemoryStore
from .schemas import ImprovementCard


class CardList(BaseModel):
    cards: list[ImprovementCard] = Field(default_factory=list)


_EVOLUTION_SYSTEM = """You are the Meta-Harness Evaluator.

Read the concatenated run traces (JSONL) and propose 1 to 3 improvement cards.

Failure-mode taxonomy
F1 Loop  F2 Premature Completion  F3 Context Overflow  F4 Tool Misuse
F5 Prompt Drift  F6 Silent Success  F7 API Error  F8 Permission Escape

Rules
- One card = one change targeting one metric. Do NOT bundle.
- If evidence is insufficient, return an empty list — do not fabricate cards.
- target_component must reference an actual module path or file name.
- Keep each field ≤ 200 chars.

Return JSON: {"cards": [ImprovementCard, ...]}.
"""


def _load_trace_text(paths: list[Path], max_lines: int = 600) -> str:
    lines: list[str] = []
    for p in paths:
        lines.append(f"--- TRACE {p.name} ---")
        try:
            with p.open() as f:
                for line in f:
                    lines.append(line.rstrip())
                    if len(lines) >= max_lines:
                        break
        except OSError:
            continue
        if len(lines) >= max_lines:
            break
    return "\n".join(lines[-max_lines:])


def analyze_runs(
    store: MemoryStore,
    *,
    limit: int = 10,
    model_id: str = MODEL_ID,
    persist: bool = True,
) -> list[ImprovementCard]:
    traces = store.recent_runs(limit=limit)
    if not traces:
        return []

    body = _load_trace_text(traces)
    llm = ChatAnthropic(model=model_id, max_tokens=3000).with_structured_output(
        CardList, include_raw=False
    )
    try:
        out: CardList = llm.invoke(
            [SystemMessage(content=_EVOLUTION_SYSTEM), HumanMessage(content=body)]
        )
    except Exception:
        return []

    if persist:
        for card in out.cards:
            store.append_card(card.model_dump(mode="json"))
    return out.cards
