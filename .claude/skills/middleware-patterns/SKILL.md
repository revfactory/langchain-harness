---
name: middleware-patterns
description: "deepagents 하네스에 적용 가능한 5가지 핵심 미들웨어 패턴(Self-Verification · LocalContext · LoopDetection · ReasoningBudget · TraceAnalysis)의 설계와 파이썬 구현 가이드. '미들웨어 추가', '루프 방지', 'self-verification', '컨텍스트 주입', '도메인 중단' 등 하네스의 행동 제어가 필요한 작업에 사용. 각 미들웨어는 독립 토글 가능."
---

# Middleware Patterns — 5 Core Levers for Harness Quality

하네스의 품질은 미들웨어가 만든다. LangChain blog "Improving deep agents with harness engineering"에서 +13.7점 개선을 가능케 한 5개 패턴의 실전 구현.

## 공통 인터페이스

모든 미들웨어는 `AgentMiddleware`를 상속한다고 가정한다. 실제 `deepagents` API가 다르면 `before_model` / `after_tool_call` / `before_completion` 훅을 동등한 위치에 직접 삽입.

```python
from __future__ import annotations
from typing import Any, Protocol


class AgentMiddleware(Protocol):
    def before_model(self, state: dict[str, Any]) -> dict[str, Any] | None: ...
    def after_tool_call(self, tool_name: str, args: dict, result: Any, state: dict) -> None: ...
    def before_completion(self, state: dict) -> dict | None: ...
```

호출 순서: `before_model` → model call → `after_tool_call`(각 tool) → `before_completion`(모델이 종료 의도 시)

---

## 1. PreCompletionChecklistMiddleware — 조기 종료 차단

### Why
모델은 첫 그럴듯한 답에서 멈추려 한다. 태스크 스펙 대비 검증 통과 여부를 **모델 종료 직전**에 가로채 확인시킨다.

### 구현

```python
from dataclasses import dataclass, field


@dataclass
class PreCompletionChecklistMiddleware:
    checklist: list[str] = field(default_factory=list)
    max_reminders: int = 2

    def before_completion(self, state: dict) -> dict | None:
        reminders = state.setdefault("_checklist_reminders", 0)
        if reminders >= self.max_reminders:
            return None  # 너무 많이 상기시키면 스팸. 포기하고 통과

        pending = "\n".join(f"- [ ] {item}" for item in self.checklist)
        state["_checklist_reminders"] = reminders + 1
        return {
            "messages": [{
                "role": "user",
                "content": (
                    "종료 전에 아래 체크리스트를 스스로 검증하고, "
                    "미통과 항목이 있으면 해결 후에만 종료하라:\n" + pending
                ),
            }]
        }
```

### 체크리스트 항목 작성 원칙
- 객관 검증 가능해야 함 ("테스트 통과", "파일 존재")
- 3~7개. 10개 넘으면 모델이 무시하기 시작한다

---

## 2. LocalContextMiddleware — 환경 자각 주입

### Why
에이전트는 자신의 환경을 모른다. 시작 시점에 디렉토리 구조, 사용 가능 도구, 코딩 표준을 주입해야 자율 실행이 가능하다.

### 구현

```python
from pathlib import Path


@dataclass
class LocalContextMiddleware:
    workspace: Path
    max_tree_lines: int = 80
    agents_md_path: Path | None = None
    coding_standards: str = ""

    def _tree(self) -> str:
        lines: list[str] = []
        for p in sorted(self.workspace.rglob("*")):
            if any(seg.startswith(".") for seg in p.relative_to(self.workspace).parts):
                continue
            if len(lines) >= self.max_tree_lines:
                lines.append(f"... (+{sum(1 for _ in self.workspace.rglob('*')) - len(lines)} more)")
                break
            lines.append(str(p.relative_to(self.workspace)))
        return "\n".join(lines)

    def before_model(self, state: dict) -> dict | None:
        if state.get("_local_context_injected"):
            return None
        parts = [f"## Workspace tree (top {self.max_tree_lines})\n{self._tree()}"]
        if self.agents_md_path and self.agents_md_path.exists():
            parts.append(f"## AGENTS.md\n{self.agents_md_path.read_text()}")
        if self.coding_standards:
            parts.append(f"## Coding standards\n{self.coding_standards}")
        state["_local_context_injected"] = True
        return {
            "messages": [{"role": "system", "content": "\n\n".join(parts)}]
        }
```

### 주의
- `before_model`은 매 턴 호출되지만, 가드(`_local_context_injected`)로 단 한 번만 주입
- tree가 거대하면 요약 전략 필요 — 여기선 max_tree_lines로 자르고 잔여 카운트만 노출

---

## 3. LoopDetectionMiddleware — Doom Loop 탈출

### Why
모델은 같은 파일을 5회, 10회 반복 수정하며 점점 나빠진다. 편집 횟수를 관찰하고 임계점에 도달하면 "멈추고 재설계"를 주입한다.

### 구현

```python
from collections import Counter


@dataclass
class LoopDetectionMiddleware:
    edit_threshold: int = 3
    edit_tools: tuple[str, ...] = ("edit_file", "write_file")
    _counts: Counter[str] = field(default_factory=Counter)
    _alerted: set[str] = field(default_factory=set)

    def after_tool_call(self, tool_name: str, args: dict, result: Any, state: dict) -> None:
        if tool_name not in self.edit_tools:
            return
        path = args.get("path") or args.get("file_path")
        if not path:
            return
        self._counts[path] += 1
        if self._counts[path] >= self.edit_threshold and path not in self._alerted:
            self._alerted.add(path)
            state.setdefault("messages", []).append({
                "role": "user",
                "content": (
                    f"⚠️ `{path}`를 {self._counts[path]}회 수정했다. 같은 접근이 작동하지 않을 가능성이 높다. "
                    "진행 전에 (1) 근본 원인 재분석, (2) 다른 파일을 고쳐야 하는지 검토, "
                    "(3) 테스트 실패 메시지를 정확히 읽어라. 답변은 분석으로 시작한다."
                ),
            })
```

### 임계값 선택
- 파일 편집: 3회 권장 (3회에서 멈춰 재고)
- 동일 커맨드 실행: 5회 (테스트 재실행 등은 더 흔함)

---

## 4. ReasoningBudgetMiddleware — "Reasoning Sandwich"

### Why
모든 턴에 최대 reasoning을 쓰면 토큰이 폭발하고, 모두 줄이면 계획과 검증이 부실해진다. **계획(high) → 구현(medium) → 검증(high)** 샌드위치 구조가 최적.

### 구현

```python
@dataclass
class ReasoningBudgetMiddleware:
    plan_budget: int = 12000
    impl_budget: int = 4000
    verify_budget: int = 10000
    plan_turns: int = 1
    verify_trigger: str = "verify"  # 사용자/시스템 신호

    def before_model(self, state: dict) -> dict | None:
        turn = state.get("_turn", 0)
        last_msg = state.get("messages", [{}])[-1].get("content", "").lower() if state.get("messages") else ""

        if turn < self.plan_turns:
            budget = self.plan_budget
        elif self.verify_trigger in last_msg or state.get("_verification_phase"):
            budget = self.verify_budget
        else:
            budget = self.impl_budget

        state["_turn"] = turn + 1
        state["_next_thinking_budget"] = budget
        return None
```

### 호출부 연동
`build_model`에서 `thinking={"type": "enabled", "budget_tokens": state.get("_next_thinking_budget", default)}`로 연결. 모델 재생성이 비싸면, ChatAnthropic 대신 raw Anthropic SDK로 per-call 예산 주입하는 것이 실용적.

---

## 5. TraceAnalysisMiddleware — 자기 진화 루프

### Why
실행이 끝난 뒤 trace를 분석하면 하네스의 다음 버전이 보인다. 이 미들웨어는 실행 중이 아니라 **배치 분석 파이프라인의 후처리 컴포넌트**로 동작한다.

### 구현

```python
from datetime import datetime
import json
from pathlib import Path


@dataclass
class TraceAnalysisMiddleware:
    log_dir: Path
    run_id: str = field(default_factory=lambda: datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"))

    def after_tool_call(self, tool_name: str, args: dict, result: Any, state: dict) -> None:
        self._append({"kind": "tool", "name": tool_name, "args": args, "turn": state.get("_turn", 0)})

    def before_completion(self, state: dict) -> dict | None:
        self._append({"kind": "completion_attempt", "turn": state.get("_turn", 0)})
        return None

    def _append(self, event: dict) -> None:
        path = self.log_dir / f"{self.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(event) + "\n")
```

### 분석 파이프라인
실행 후 `_workspace/runs/{run_id}.jsonl`을 `harness-evaluator` 에이전트가 읽고 실패 모드 분류 + 개선 카드 생성. `trace-eval-loop` 스킬 참조.

---

## 기본 스택 조립

```python
def default_middleware_stack(workspace: Path, checklist: list[str] | None = None) -> list:
    return [
        LocalContextMiddleware(workspace=workspace),
        LoopDetectionMiddleware(edit_threshold=3),
        ReasoningBudgetMiddleware(),
        PreCompletionChecklistMiddleware(checklist=checklist or [
            "요구사항의 모든 성공 지표를 충족했는가",
            "테스트 또는 등가 검증을 실행했는가",
            "남은 TODO가 없는가",
        ]),
        TraceAnalysisMiddleware(log_dir=workspace / "runs"),
    ]
```

## 조합 팁

- 모든 하네스에 필수 추천: `LocalContext` + `PreCompletionChecklist` + `TraceAnalysis`
- 코딩 에이전트에 특히 유효: `LoopDetection` + `ReasoningBudget`
- 짧은 1턴 태스크: `LoopDetection` 생략 가능 (오버헤드 대비 이득 낮음)

## 측정 지표 (회귀 방지용)

| 미들웨어 | 지표 | 목표 |
|---------|------|------|
| PreCompletion | 조기 종료 회피율 | ≥ 80% |
| LocalContext | 환경 질문 턴 수 | 0 |
| LoopDetection | 동일 파일 N회 이상 편집률 | < 5% |
| ReasoningBudget | 토큰 소비 | baseline 대비 -20% |
| TraceAnalysis | 분석 가능한 trace 비율 | 100% |
