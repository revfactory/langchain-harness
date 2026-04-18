# langchain-harness

> Runtime-configurable **deep-agent harness** on LangChain `deepagents` + Anthropic Claude Agent SDK, powered by **Claude Opus 4.7**.

_Agent = Model + Harness._ 이 프로젝트는 모델을 고정(Claude Opus 4.7)하고 **하네스 쪽 모든 레버**를 실험 가능한 형태로 제공한다. 사용자 과제에 맞춰 미들웨어·서브에이전트·스킬을 실시간 조립하고, 실행 trace를 기반으로 하네스 자체가 진화한다.

관련 자료:
- [The anatomy of an agent harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness)
- [Improving deep agents with harness engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- [deepagents harness reference](https://docs.langchain.com/oss/python/deepagents/harness)

---

## Highlights

- **Claude Opus 4.7** 기본, extended thinking + prompt caching 대응
- 플러그형 **5종 미들웨어** — `PreCompletionChecklist`, `LocalContext`, `LoopDetection`, `ReasoningBudget`, `TraceAnalysis`
- `deepagents.create_deep_agent` 위의 얇은 래퍼 — **버전 드리프트에 안전한 폴백** 포함
- JSONL **trace 자동 수집** → 실패 모드 분류 → 개선 카드 루프
- Claude Code용 **에이전트 팀(5) + 스킬(6)** 탑재: 하네스 자체를 Claude Code로 설계·구현·검증·고도화

---

## Architecture

```
               ┌──────────── CLAUDE CODE HARNESS (.claude/) ────────────┐
               │                                                        │
  User task ──▶│  harness-engineering (orchestrator skill)              │
               │   ├─ Phase 2 ─ design team                             │
               │   │    harness-architect ⇄ skill-curator               │
               │   ├─ Phase 3 ─ deepagent-engineer (sub)                │
               │   ├─ Phase 4 ─ integration-qa (sub)                    │
               │   └─ Phase 5 ─ harness-evaluator (trace → cards)       │
               │                                                        │
               └─────────────── emits ─────┬────────────────────────────┘
                                           ▼
                      ┌──── PYTHON HARNESS (src/) ────┐
                      │  HarnessConfig                 │
                      │    ↓                           │
                      │  create()                      │
                      │    ├─ ChatAnthropic(opus-4-7)  │
                      │    ├─ tools (read/write/bash)  │
                      │    ├─ subagents (optional)     │
                      │    └─ middleware stack x5      │
                      │                                │
                      └─── create_deep_agent(...) ─────┘
                                    ↓
                          _workspace/runs/*.jsonl   (trace)
```

두 하네스가 맞물려 돈다. Claude Code 하네스는 **당신이 이 프로젝트를 짓는 도구**이고, Python 하네스는 **이 프로젝트가 짓는 산출물**이다.

---

## Install

```bash
# 권장: uv
uv sync

# 또는 pip
pip install -e .
```

환경변수:

```bash
cp .env.example .env
# .env 열어 ANTHROPIC_API_KEY 입력
```

---

## Quick Start

### 1. 설정 확인

```bash
uv run python -m langchain_harness.cli info
# model_id        : claude-opus-4-7
# thinking_budget : 8000
# workspace       : _workspace
```

### 2. 단일 태스크 실행

```bash
uv run python -m langchain_harness.cli run "Summarize README.md in 3 bullets"
```

### 3. 스모크 예제

```bash
uv run python examples/hello.py
```

### 4. Python에서 직접 사용

```python
from pathlib import Path
from langchain_harness import HarnessConfig, create

agent = create(HarnessConfig(
    system_prompt="You are a senior Python engineer.",
    agents_md=Path("AGENTS.md"),
    checklist=[
        "테스트 통과",
        "타입 힌트 누락 없음",
    ],
))

result = agent.invoke({
    "messages": [{"role": "user", "content": "Refactor foo.py for readability."}]
})
print(result["messages"][-1].content)
```

---

## Middleware Stack

기본 스택 (`middleware.default_middleware_stack`):

| 미들웨어 | 훅 | 역할 |
|---------|----|----|
| `LocalContextMiddleware` | `before_model` (1회) | 작업 디렉토리 트리 + `AGENTS.md` + 코딩 표준 주입 |
| `LoopDetectionMiddleware` | `after_tool_call` | 동일 파일 N회 편집 감지 → 재설계 유도 메시지 |
| `ReasoningBudgetMiddleware` | `before_model` | plan(high) → impl(medium) → verify(high) 샌드위치 |
| `PreCompletionChecklistMiddleware` | `before_completion` | 체크리스트 미충족 시 종료 차단 |
| `TraceAnalysisMiddleware` | 전 훅 | `_workspace/runs/*.jsonl`로 실행 기록 |

개별 미들웨어를 토글하려면 `HarnessConfig`를 받지 말고 `create_deep_agent`에 직접 전달.

---

## Project Layout

```
langchain-harness/
├── .claude/
│   ├── agents/        # 5명 (Claude Code 하네스)
│   └── skills/        # 6개 (오케스트레이터 + 보조 스킬)
├── src/langchain_harness/
│   ├── agent.py       # create() 팩토리
│   ├── middleware.py  # 5종 미들웨어
│   ├── tools.py       # read_file / write_file / bash
│   ├── config.py      # MODEL_ID = "claude-opus-4-7"
│   └── cli.py         # typer 엔트리포인트
├── examples/hello.py
├── AGENTS.md          # deep-agent 장기 기억
├── CLAUDE.md          # Claude Code 하네스 포인터 + 변경 이력
├── pyproject.toml
└── .env.example
```

---

## Claude Code에서 하네스 진화시키기

이 저장소를 Claude Code로 연 뒤 아래처럼 요청하면 오케스트레이터 스킬이 자동 발동한다.

```
"SWE-Bench 스타일 버그 수정 하네스를 추가해줘. 
 테스트 실패 로그를 파싱해 root cause 후보를 3개 뽑는 단계를 포함하도록."
```

→ `harness-architect`가 스펙을, `skill-curator`가 필요한 스킬을, `deepagent-engineer`가 파이썬 코드를, `integration-qa`가 경계면 정합성을 병렬로 처리한다. 실행 후 trace가 쌓이면:

```
"지난 실행에서 같은 파일 5번 수정 루프가 자주 보여. 개선 카드 뽑아줘."
```

→ `harness-evaluator`가 `_workspace/runs/` trace를 분석해 개선 카드를 생성, 사용자 승인 후 부분 재실행으로 적용한다.

자세한 워크플로우: `.claude/skills/harness-engineering/SKILL.md`.

---

## Conventions

- **모델 ID는 상수 한 곳** (`src/langchain_harness/config.py`) — `claude-opus-4-7`만 허용
- **산출물은 `_workspace/`** 경유, 최종 코드만 `src/`에 둔다. `_workspace/`는 사후 감사용으로 보존
- **사일런트 폴백 금지** — 외부 호출 실패는 원인과 함께 raise
- **타입 힌트 필수**, `from __future__ import annotations` 기본
- **댓글은 WHY만**. WHAT은 코드가 말한다

---

## Known Caveats

- `deepagents` 버전에 따라 `create_deep_agent(middleware=...)` 시그니처가 다르다. `agent.py`는 `TypeError` 폴백으로 구버전도 지원한다
- Extended thinking + `temperature=0` 동시 설정은 Anthropic 제약상 불가. thinking만 쓸 때는 `temperature` 생략
- `LoopDetectionMiddleware`는 verify phase의 정상적 반복 편집도 차단할 수 있음 — 큰 리팩터 태스크에서는 `edit_threshold` 상향 검토

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
