from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PreCompletionChecklistMiddleware:
    """Block premature completion by injecting a verification checklist."""

    checklist: list[str] = field(default_factory=list)
    max_reminders: int = 2

    def before_completion(self, state: dict[str, Any]) -> dict[str, Any] | None:
        reminders = state.get("_checklist_reminders", 0)
        if reminders >= self.max_reminders or not self.checklist:
            return None
        pending = "\n".join(f"- [ ] {item}" for item in self.checklist)
        state["_checklist_reminders"] = reminders + 1
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "종료 전에 아래 체크리스트를 스스로 검증하고, "
                        "미통과 항목이 있으면 해결 후에만 종료하라:\n" + pending
                    ),
                }
            ]
        }


@dataclass
class LocalContextMiddleware:
    """Inject workspace tree + AGENTS.md + coding standards once at startup."""

    workspace: Path
    max_tree_lines: int = 80
    agents_md_path: Path | None = None
    coding_standards: str = ""

    def _tree(self) -> str:
        lines: list[str] = []
        total = 0
        for p in sorted(self.workspace.rglob("*")):
            rel_parts = p.relative_to(self.workspace).parts
            if any(seg.startswith(".") or seg == "__pycache__" for seg in rel_parts):
                continue
            total += 1
            if len(lines) >= self.max_tree_lines:
                continue
            lines.append(str(p.relative_to(self.workspace)))
        if total > self.max_tree_lines:
            lines.append(f"... (+{total - self.max_tree_lines} more)")
        return "\n".join(lines)

    def before_model(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("_local_context_injected"):
            return None
        parts = [f"## Workspace tree (top {self.max_tree_lines})\n{self._tree()}"]
        if self.agents_md_path and self.agents_md_path.exists():
            parts.append(f"## AGENTS.md\n{self.agents_md_path.read_text()}")
        if self.coding_standards:
            parts.append(f"## Coding standards\n{self.coding_standards}")
        state["_local_context_injected"] = True
        return {"messages": [{"role": "system", "content": "\n\n".join(parts)}]}


@dataclass
class LoopDetectionMiddleware:
    """Alert when the same file is edited too many times in a row."""

    edit_threshold: int = 3
    edit_tools: tuple[str, ...] = ("edit_file", "write_file")
    _counts: Counter = field(default_factory=Counter)
    _alerted: set[str] = field(default_factory=set)

    def after_tool_call(
        self, tool_name: str, args: dict[str, Any], result: Any, state: dict[str, Any]
    ) -> None:
        if tool_name not in self.edit_tools:
            return
        path = args.get("path") or args.get("file_path")
        if not path:
            return
        self._counts[path] += 1
        if self._counts[path] >= self.edit_threshold and path not in self._alerted:
            self._alerted.add(path)
            state.setdefault("messages", []).append(
                {
                    "role": "user",
                    "content": (
                        f"⚠️ `{path}`를 {self._counts[path]}회 수정했다. "
                        "같은 접근이 작동하지 않을 가능성이 높다. "
                        "진행 전에 (1) 근본 원인 재분석, (2) 다른 파일을 고쳐야 하는지 검토, "
                        "(3) 테스트 실패 메시지를 정확히 읽어라."
                    ),
                }
            )


@dataclass
class ReasoningBudgetMiddleware:
    """Reasoning sandwich: high -> medium -> high across a run."""

    plan_budget: int = 12000
    impl_budget: int = 4000
    verify_budget: int = 10000
    plan_turns: int = 1
    verify_trigger: str = "verify"

    def before_model(self, state: dict[str, Any]) -> dict[str, Any] | None:
        turn = state.get("_turn", 0)
        messages = state.get("messages", [])
        last_content = messages[-1].get("content", "") if messages else ""
        last_lower = last_content.lower() if isinstance(last_content, str) else ""

        if turn < self.plan_turns:
            budget = self.plan_budget
        elif self.verify_trigger in last_lower or state.get("_verification_phase"):
            budget = self.verify_budget
        else:
            budget = self.impl_budget

        state["_turn"] = turn + 1
        state["_next_thinking_budget"] = budget
        return None


@dataclass
class TraceAnalysisMiddleware:
    """Append every tool call and completion attempt to a JSONL run log."""

    log_dir: Path
    run_id: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )

    def after_tool_call(
        self, tool_name: str, args: dict[str, Any], result: Any, state: dict[str, Any]
    ) -> None:
        self._append(
            {
                "kind": "tool",
                "name": tool_name,
                "args": self._safe(args),
                "turn": state.get("_turn", 0),
            }
        )

    def before_completion(self, state: dict[str, Any]) -> dict[str, Any] | None:
        self._append({"kind": "completion_attempt", "turn": state.get("_turn", 0)})
        return None

    def _append(self, event: dict[str, Any]) -> None:
        path = self.log_dir / f"{self.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event["ts"] = datetime.now(timezone.utc).isoformat()
        with path.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _safe(obj: Any) -> Any:
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return {k: str(v) for k, v in (obj or {}).items()}


def default_middleware_stack(
    workspace: Path,
    *,
    checklist: list[str] | None = None,
    agents_md: Path | None = None,
    coding_standards: str = "",
) -> list[Any]:
    checklist = checklist or [
        "요구사항의 모든 성공 지표를 충족했는가",
        "테스트 또는 등가 검증을 실행했는가",
        "남은 TODO가 없는가",
    ]
    return [
        LocalContextMiddleware(
            workspace=workspace,
            agents_md_path=agents_md,
            coding_standards=coding_standards,
        ),
        LoopDetectionMiddleware(edit_threshold=3),
        ReasoningBudgetMiddleware(),
        PreCompletionChecklistMiddleware(checklist=checklist),
        TraceAnalysisMiddleware(log_dir=workspace / "runs"),
    ]
