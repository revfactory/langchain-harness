# langchain-harness

> **Multi-DeepAgent Team runtime** on LangChain `deepagents` + Anthropic Claude Agent SDK, powered by **Claude Opus 4.7**.

_Agent = Model + Harness._ 이 프로젝트는 모델을 고정(Claude Opus 4.7)하고 **하네스 쪽 모든 레버**를 실험 가능한 형태로 제공한다. 다수의 독립 DeepAgent 인스턴스가 **파일 기반 메일박스와 공유 태스크 큐**로 자율 조율하는 팀 런타임이 유일한 실행 경로다.

관련 자료:
- [The anatomy of an agent harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness)
- [Improving deep agents with harness engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- [deepagents harness reference](https://docs.langchain.com/oss/python/deepagents/harness)

---

## Highlights

- **Claude Opus 4.7** 기본, extended thinking + prompt caching 대응
- **Multi-DeepAgent Team 런타임** — `AgentTeamHarness` 위에서 여러 DeepAgent가 동시 실행
- **11종 팀 도구** — `team_create` / `spawn_teammate` / `send_message` / `broadcast_message` / `read_inbox` / `team_task_{create,claim,update,list}` / `team_status` / `team_delete`
- **3가지 빌드 레시피** — Supervisor · 자율 협업(Swarm) · 생성-검증(Maker-Checker)
- **5+2 미들웨어** — 공통 5종(`PreCompletionChecklist` · `LocalContext` · `LoopDetection` · `ReasoningBudget` · `TraceAnalysis`) + 팀 전용 2종(`TeamContext` · `InboxPoll`)
- **파일 기반 영속성** — `_workspace/teams/{team}/` 하위에 팀 상태 전체 저장. 세션·프로세스 경계를 넘어 조회 가능
- **동시성** — POSIX `O_APPEND`(JSONL 메일박스/로그) + `fcntl.LOCK_EX` + atomic rename + version CAS (JSON rewrite)
- **세 모드 isolation** — thread(기본) · sequential(테스트/결정성) · process(스켈레톤)
- Claude Code용 **에이전트 팀(7) + 스킬(7)** (`.claude/`)이 런타임 진화를 보조

---

## Architecture

```
            ┌──────────── MULTI-DEEPAGENT TEAM RUNTIME ────────────┐
            │                                                      │
 task ────▶ │  AgentTeamHarness(team_name, isolation=...)          │
            │     ├─ team_create  → teams/{team}/config.json       │
            │     ├─ spawn_teammate → teammate DeepAgent (opus)    │
            │     │    ├─ TeamContextMiddleware                    │
            │     │    ├─ InboxPollMiddleware                      │
            │     │    └─ (공통 5종 미들웨어)                        │
            │     ├─ TEAM_TOOLS (11)                               │
            │     │    send_message · broadcast_message ·          │
            │     │    read_inbox · team_task_{create,claim,       │
            │     │    update,list} · team_status · team_delete    │
            │     └─ 상태                                            │
            │          ├─ mailbox/{agent}.jsonl  (O_APPEND)        │
            │          ├─ tasks/{id}.json       (flock + CAS)     │
            │          ├─ locks/                                   │
            │          └─ logs.jsonl · runs/*.jsonl                │
            └──────────────────────────────────────────────────────┘
```

팀 프리미티브는 전적으로 파일 시스템에 영속되며, 러닝 팀원들은 `SendMessage` / `TaskCreate` 대응 도구로 **자체 조율**한다. lead는 오직 팀 구조 변경(spawn/shutdown)과 태스크 발행만 담당.

---

## Install

Python ≥ 3.11 필요.

```bash
# 권장: uv
uv sync

# 또는 pip (editable)
pip install -e .
```

설치 후 `langchain-harness` entry script가 등록된다 (pyproject `[project.scripts]`).

환경변수:

```bash
cp .env.example .env
# .env 열어 ANTHROPIC_API_KEY 입력
```

**지원 플랫폼:** darwin / linux (fcntl 기반). Windows는 v1.0 비목표.

### 테스트 실행

```bash
uv run pytest tests/team/ -q
# 21 passed — ANTHROPIC_API_KEY 없이도 통과 (LLM 호출 없는 런타임 검증만)
```

---

## Quick Start

설치 시 entry script `langchain-harness` 가 등록되므로 아래 `python -m langchain_harness.cli …` 는 `langchain-harness …` 로 대체 가능.

### 1. CLI 탐색

```bash
uv run python -m langchain_harness.cli team --help
```

서브커맨드 9종: `create` · `spawn` · `run` · `send` · `inbox` · `task-create` · `task-list` · `status` · `delete`.

### 2. 팀 생성과 조회

```bash
# 팀 스캐폴드 — config.json · mailbox · tasks 디렉토리 준비
uv run python -m langchain_harness.cli team create \
    --team-name demo --lead alice \
    --objective "Ship a hello-world runtime"

# 팀원 스폰 (팀 파일에 member entry 추가, agent는 run 시 연결)
uv run python -m langchain_harness.cli team spawn \
    --team-name demo --name bob --role engineer

# 메시지·태스크 생성
uv run python -m langchain_harness.cli team send \
    --team-name demo --sender alice --recipient bob --body "please review #1"
uv run python -m langchain_harness.cli team task-create \
    --team-name demo --title "Review PR" --description "..." --created-by alice

# 상태 스냅샷 (orphan 감지 + 최근 로그 tail)
uv run python -m langchain_harness.cli team status --team-name demo
```

### 3. 스모크 예제 (LLM 없이)

```bash
uv run python examples/team_hello.py
```

`_workspace/teams/hello_team/` 아래 `config.json` · `mailbox/alice.jsonl` · `tasks/{id}.json` 이 생성되고, 메시지 1개·태스크 1개가 append 된다.

### 4. Python에서 직접 사용

```python
from datetime import datetime, timezone
from pathlib import Path

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic

from langchain_harness import (
    AgentTeamHarness,
    MODEL_ID,
    TEAM_TOOLS,
    team_middleware_stack,
)
from langchain_harness.team import registry
from langchain_harness.team.types import MailboxPolicy, TeamFile, TeamMember


def make_agent_factory(is_lead: bool):
    """팀 멤버용 DeepAgent를 조립하는 factory. spawn()이 TeamContext를 주입한다."""
    def factory(ctx):
        return create_deep_agent(
            model=ChatAnthropic(model=MODEL_ID, max_tokens=8192),
            tools=list(TEAM_TOOLS),
            middleware=team_middleware_stack(
                workspace=ctx.workspace,
                team_name=ctx.team_name,
                is_lead=is_lead,
            ),
            system_prompt=f"You are {ctx.agent_id}, role={ctx.role}.",
        )
    return factory


workspace = Path("_workspace")
team_name = "maker_checker"
now = datetime.now(timezone.utc).isoformat()

# 팀 파일 스캐폴드 (CLI `team create` 와 동일 효과)
registry.ensure_team_dirs(workspace, team_name)
lead = TeamMember(
    agent_name="alice", agent_id=f"alice@{team_name}", role="lead",
    model_id=MODEL_ID, tools=[t.name for t in TEAM_TOOLS],
    state="spawning", spawned_at=now, last_heartbeat=now,
)
registry.save_team_file(
    workspace,
    TeamFile(
        team_name=team_name, created_at=now, lead="alice",
        members=[lead], shared_objective="Maker-Checker demo",
        mailbox_policy=MailboxPolicy(),
    ),
    expected_version=None,
)

harness = AgentTeamHarness(team_name=team_name, workspace=workspace, isolation="thread")
harness.start()
harness.spawn(lead, make_agent_factory(is_lead=True), is_lead=True)
# harness.spawn(checker_member, make_agent_factory(is_lead=False))

print(harness.status())
harness.shutdown(cascade=True)
```

팀 도구 11종은 각자의 `TeamContext`를 통해 **발신자/팀을 자동 식별**하므로, 도구 호출 인자에서 `sender`·`team_name`을 따로 넘기지 않는다.

---

## Build Recipes

세부 코드는 `.claude/skills/multi-deepagent-team/references/recipes.md` 참조.

### (a) Supervisor — 중앙 lead가 teammate에 지시
- lead 1 + runner N. 과제가 명확히 분할 가능하지만 품질 편차가 클 때.

### (b) 자율 협업(Swarm) — 태스크 큐에서 self-pickup
- 동질적 다수 단위 작업. 모든 멤버가 `team_task_claim`으로 자가 할당.

### (c) 생성-검증(Maker-Checker) — 고정 짝
- 같은 모델의 자가 검증보다 프롬프트 분리된 두 에이전트가 실패를 더 잘 잡는다.

---

## Middleware Stack

기본 팀 스택 (`team_middleware_stack`):

| 미들웨어 | 훅 | 역할 |
|---------|----|----|
| `LocalContextMiddleware` | `before_model` (1회) | 팀 workspace 트리 + 팀별 AGENTS.md + 코딩 표준 주입 |
| `TeamContextMiddleware` | `before_model` (1회) | `[YOU ARE {agent_id}] team={team} role={role}` 시스템 메시지 주입 |
| `InboxPollMiddleware` | `before_model` (매 턴) | unread 메시지를 user 메시지로 변환 |
| `LoopDetectionMiddleware` | `after_tool_call` | 동일 파일·메일 반복 감지 (send_message도 edit_tools에 포함) |
| `ReasoningBudgetMiddleware` | `before_model` | plan(high) → impl(medium) → verify(high) 샌드위치. 팀 모드는 plan_turns 기본 2 |
| `PreCompletionChecklistMiddleware` | `before_completion` | lead는 "모든 멤버 stopped / 보류 task 없음 / ack 미수신 없음" 3항 추가 |
| `TraceAnalysisMiddleware` | 전 훅 | `_workspace/teams/{team}/runs/*.jsonl` 로 실행 기록 |

---

## Project Layout

```
langchain-harness/
├── .claude/                       # Claude Code 개발 보조 (런타임 의존 없음)
│   ├── agents/                    # 7명 (harness-architect, team-runtime-architect,
│   │                              # deepagent-engineer, team-messaging-engineer,
│   │                              # skill-curator, harness-evaluator, integration-qa)
│   └── skills/                    # 7개 (harness-engineering, multi-deepagent-team,
│                                  # deepagents-bootstrap, middleware-patterns,
│                                  # langchain-opus, trace-eval-loop, skill-bundling)
├── src/langchain_harness/
│   ├── __init__.py                # AgentTeamHarness / TEAM_TOOLS / TeamContext export
│   ├── config.py                  # MODEL_ID = "claude-opus-4-7"
│   ├── middleware.py              # 5종 공통 미들웨어
│   ├── tools.py                   # read_file / write_file / bash (공통 도구)
│   ├── cli.py                     # `python -m langchain_harness.cli team ...`
│   └── team/                      # ── Multi-DeepAgent Team 런타임 ──
│       ├── types.py               # TeamFile · TeamMember · MailboxEntry · TeamTask · 예외
│       ├── registry.py            # fcntl + atomic rename + version CAS
│       ├── mailbox.py             # O_APPEND JSONL + body_ref 분리
│       ├── tasks.py               # CAS claim/update + DAG cycle 탐지
│       ├── context.py             # TeamContext + contextvars + env fallback
│       ├── tools.py               # LangChain @tool 11종 (TEAM_TOOLS)
│       ├── middleware.py          # TeamContext / InboxPoll + team_middleware_stack
│       ├── runtime.py             # AgentTeamHarness (thread/sequential/process)
│       └── cli.py                 # typer 9개 서브커맨드
├── tests/team/                    # 21 cases across 6 files — registry/mailbox/tasks/
│                                  # lifecycle/tools/runtime. H1~H14 경계 체크포인트 커버
├── examples/
│   └── team_hello.py              # LLM 없이 파일 프리미티브 스모크
├── AGENTS.md · CLAUDE.md
├── LICENSE                        # Apache-2.0
├── pyproject.toml                 # entry: `langchain-harness` → cli:app
└── .env.example
```

---

## Data Model 요약

| 개념 | 저장 위치 | 쓰기 모드 |
|------|----------|----------|
| `TeamFile` | `config.json` | rewrite + flock + version CAS |
| `TeamMember` | `config.json` 내 members[] | rewrite + flock + version CAS |
| `MailboxEntry` | `mailbox/{agent}.jsonl` | O_APPEND (≤4KB 원자성) |
| `TeamTask` | `tasks/{id}.json` | rewrite + flock + version CAS |
| 감사 로그 | `logs.jsonl` | O_APPEND |
| 실행 trace | `runs/*.jsonl` | O_APPEND |

세부 프로토콜은 `.claude/skills/multi-deepagent-team/references/protocol.md`에 고정된다.

---

## Claude Code에서 하네스 진화시키기 (선택)

저장소를 Claude Code로 연 뒤 요청하면 오케스트레이터 스킬이 자동 발동한다.

```
"Multi-DeepAgent Team에 평가자 추가해서 trace 기반 자동 개선 루프 넣어줘."
```

→ `team-runtime-architect`가 토폴로지를, `skill-curator`가 프로토콜 문서를, `team-messaging-engineer`가 Python 구현을, `integration-qa`가 경계면 정합성을 병렬 처리한다. 실행 후 trace가 쌓이면:

```
"지난 실행에서 동일 수신자에게 메시지 반복 루프가 자주 보여. 개선 카드 뽑아줘."
```

→ `harness-evaluator`가 `_workspace/teams/{team}/runs/` trace를 분석해 개선 카드를 생성, 사용자 승인 후 부분 재실행으로 적용한다.

자세한 워크플로우: `.claude/skills/harness-engineering/SKILL.md`.

---

## Conventions

- **모델 ID는 상수 한 곳** (`src/langchain_harness/config.py`) — `claude-opus-4-7`만 허용
- **산출물은 `_workspace/`** 경유. 팀 상태는 `_workspace/teams/{team}/` 아래만 사용
- **사일런트 폴백 금지** — 외부 호출 실패는 원인과 함께 raise
- **타입 힌트 필수**, `from __future__ import annotations` 기본
- **댓글은 WHY만**. WHAT은 코드가 말한다
- **1 세션 1 팀** — v1.0 규약. 두 팀 동시 운영 금지

---

## Known Caveats

- `deepagents` 버전에 따라 `create_deep_agent(middleware=...)` 시그니처가 다를 수 있음. 팀 멤버 스폰 중 TypeError 발생 시 호환 경로 래퍼로 교체
- Extended thinking + `temperature=0` 동시 설정은 Anthropic 제약상 불가. thinking만 쓸 때는 `temperature` 생략
- `LoopDetectionMiddleware`는 verify phase의 정상적 반복 편집도 차단할 수 있음 — 큰 리팩터에서는 `edit_threshold` 상향 검토
- process isolation은 v1.0에서 스켈레톤. 크래시 복구 정책(Open Question O8) 확정 전에는 `thread` 사용 권장
- 4KB 초과 메시지 body는 `payloads/{message_id}.txt` 로 분리 저장되고 entry에 `body_ref`만 기록 (O1 해석)

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
