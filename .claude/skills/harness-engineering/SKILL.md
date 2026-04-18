---
name: harness-engineering
description: "LangChain deepagents + Anthropic ADK + Claude Opus 4.7 기반 Multi-DeepAgent Team 런타임을 설계·구현·평가·진화시키는 오케스트레이터. 새 팀 하네스 구축, 기존 하네스 고도화, 실패 trace 기반 개선, 미들웨어·스킬·teammate 추가, '하네스 만들어줘', '하네스 개선', '딥에이전트 구성', '팀 빌드', '팀 런타임 확장', 'teammate 추가/재구성', '고난이도 과제 자동화', '에이전트 시스템', 'LangChain 프로젝트', 'harness engineering', '재실행', '다시 실행', '업데이트', '수정', '보완', '이전 결과 개선' 등 하네스 관련 모든 요청에 반드시 이 스킬을 사용. 팀 런타임 세부(메일박스/공유 태스크/spawn_teammate 등 프로토콜·파일 레이아웃)는 multi-deepagent-team 스킬로 drill-down. 단순 Python 문법 질문 등은 제외."
---

# Harness Engineering Orchestrator

LangChain `deepagents` + Anthropic Claude Agent SDK(ADK) + Claude Opus 4.7 기반 **Multi-DeepAgent Team 런타임**을 구축·고도화하는 통합 워크플로우. 팀 런타임이 유일한 실행 경로다.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| Phase 2 (설계) | 에이전트 팀 | harness-architect + team-runtime-architect + skill-curator 합의 필요. 상위 전략과 내부 프로토콜이 동시 확정돼야 함 |
| Phase 3 (구현) | 서브 에이전트 | team-messaging-engineer + deepagent-engineer 병렬 호출. 팀 통신 오버헤드 불필요 |
| Phase 4 (검증) | 서브 에이전트 | integration-qa 독립 검증 |
| Phase 5 (진화) | 서브 에이전트 또는 팀 | 단일 trace 분석은 서브, 대규모 개선 토론은 팀 |

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 관련 스킬 | 주 산출물 |
|---------|--------------|------|----------|----------|
| harness-architect | harness-architect | 상위 전략 (목표·실패모드·빌드 레시피·미들웨어·권한) | middleware-patterns, langchain-opus | `_workspace/01_architect_spec.md` |
| team-runtime-architect | team-runtime-architect | 팀 런타임 내부 설계 (토폴로지·프로토콜·lifecycle·동시성) | multi-deepagent-team, middleware-patterns | `_workspace/01_team_architect_spec.md` |
| skill-curator | skill-curator | 스킬 카탈로그 | skill-bundling | `_workspace/02_skill_catalog.md`, `skills/` |
| team-messaging-engineer | team-messaging-engineer | 팀 프리미티브 구현 (mailbox·tasks·registry·tools·runtime) | multi-deepagent-team, langchain-opus | `src/langchain_harness/team/*` |
| deepagent-engineer | deepagent-engineer | 팀 멤버용 agent factory + 공통 기반 (middleware·tools·cli) | deepagents-bootstrap, langchain-opus | `src/langchain_harness/{middleware,tools,config,cli}.py`, agent_factories |
| integration-qa | integration-qa | 경계면 검증 | — | `_workspace/05_qa_report.md` |
| harness-evaluator | harness-evaluator | Trace 기반 개선 | trace-eval-loop | `_workspace/04_*` |

> 모든 Agent 호출에 `model: "opus"` 명시. 모든 커스텀 서브에이전트는 내부적으로 `claude-opus-4-7`를 사용.

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

1. `_workspace/` 디렉토리 존재 여부 확인
2. `src/langchain_harness/team/` 존재 여부 확인
3. 실행 모드 결정:
   - **둘 다 미존재** → 초기 구축. Phase 1부터 전체 실행
   - **`_workspace/` 존재 + 사용자가 "다시/재실행/업데이트/수정" 언급** → **부분 재실행**. 영향받는 에이전트만 재호출, 기존 산출물은 해당 파일만 덮어쓰기
   - **둘 다 존재 + 사용자가 새 요구사항 제공** → **확장 모드**. 기존 스펙을 baseline으로 두고 delta만 반영
   - **`src/langchain_harness/team/` 존재 + trace 분석 요청** → **진화 모드**. Phase 5만 실행
4. 부분 재실행 시: 이전 파일 경로를 해당 에이전트 prompt에 명시 포함

### Phase 1: 입력 파싱

1. 사용자 요청에서 추출:
   - 과제 도메인 (예: 코드 마이그레이션, 리서치 자동화, 데이터 파이프라인 구축)
   - 성공 지표 (무엇이 "완료"인가)
   - 제약 (시간 예산, 도구 허용 범위, 외부 API)
   - 우선순위 (속도 vs 정확도 vs 비용)
2. `_workspace/` 생성 (초기 구축 시)
3. 사용자 요구사항 원본을 `_workspace/00_request.md`에 저장

### Phase 2: 설계 (에이전트 팀)

1. 팀 생성 — 상위 전략(architect) + 런타임 내부(arch_team) + 스킬 카탈로그(curator):
   ```
   TeamCreate(
     team_name: "harness-design-team",
     members: [
       { name: "architect", agent_type: "harness-architect", model: "opus",
         prompt: "_workspace/00_request.md를 읽고 Behavior Goals, Failure Modes, Build Recipe(Supervisor/Swarm/Maker-Checker 중 택1), Middleware Stack, Permissions, Memory Strategy, Roles를 확정. middleware-patterns, langchain-opus 스킬 참조. 산출물 _workspace/01_architect_spec.md." },
       { name: "arch_team", agent_type: "team-runtime-architect", model: "opus",
         prompt: "architect가 확정한 Build Recipe·Roles를 받아 팀 런타임 내부 스펙을 작성. multi-deepagent-team 스킬의 §3 레이아웃·§5 프로토콜·§6 도구 목록을 baseline으로 사용. 메시지 프로토콜·파일 레이아웃·동시성·lifecycle 확정. 산출물 _workspace/01_team_architect_spec.md." },
       { name: "curator", agent_type: "skill-curator", model: "opus",
         prompt: "architect/arch_team의 스펙을 지속 모니터하며 스킬 카탈로그 + multi-deepagent-team/references/protocol.md 동기화. skill-bundling 스킬 참조. 산출물 _workspace/02_skill_catalog.md." }
     ]
   )
   ```
2. 작업 등록:
   ```
   TaskCreate(tasks: [
     { title: "Behavior Goals + Failure Modes 확정", assignee: "architect" },
     { title: "Build Recipe 선택(Supervisor/Swarm/Maker-Checker)", assignee: "architect" },
     { title: "Middleware Stack + Permissions + Memory Strategy 확정", assignee: "architect", depends_on: ["Build Recipe 선택(Supervisor/Swarm/Maker-Checker)"] },
     { title: "팀 lifecycle · 1세션1팀 제약 확정", assignee: "arch_team", depends_on: ["Build Recipe 선택(Supervisor/Swarm/Maker-Checker)"] },
     { title: "Envelope/Event 스키마 + 파일 레이아웃 확정", assignee: "arch_team" },
     { title: "동시성 전략(fcntl + atomic rename + CAS) 확정", assignee: "arch_team" },
     { title: "스킬 후보 식별", assignee: "curator", depends_on: ["Behavior Goals + Failure Modes 확정"] },
     { title: "SKILL.md 초안 작성 (스킬별)", assignee: "curator" },
     { title: "protocol.md 동기화", assignee: "curator", depends_on: ["Envelope/Event 스키마 + 파일 레이아웃 확정"] }
   ])
   ```
3. SendMessage 경로:
   - architect ↔ arch_team: 상위 전략이 내부 프로토콜에 미치는 영향 실시간 공유
   - architect → curator: 새 스킬 필요 signal
   - arch_team → curator: 스키마 확정 notify
4. 팀 정리 전 검증: 세 산출물이 서로 참조 가능하고 모순 없는지 리더가 리뷰
5. `TeamDelete`로 설계 팀 해체

### Phase 3: 구현 (서브 에이전트, 병렬 호출)

팀 프리미티브와 팀 멤버 구현을 병렬로 서브 호출:

```
# 팀 프리미티브 (mailbox/tasks/registry/tools/runtime)
Agent(
  name: "team_engineer",
  subagent_type: "team-messaging-engineer",
  model: "opus",
  prompt: "_workspace/01_team_architect_spec.md를 따라 src/langchain_harness/team/ 모듈을 구현하라. multi-deepagent-team 스킬의 protocol.md·recipes.md 참조. 완료 후 _workspace/03_team_engineer_notes.md 작성.",
  run_in_background: true
)

# 공통 기반 + 팀 멤버용 agent factory
Agent(
  name: "member_engineer",
  subagent_type: "deepagent-engineer",
  model: "opus",
  prompt: "_workspace/01_architect_spec.md의 Roles 섹션을 참조해 각 role별 agent_factory를 작성. create_deep_agent(model, tools=TEAM_TOOLS+공통도구, middleware=team_middleware_stack(...))로 조립. 공통 middleware·tools·config·cli는 deepagents-bootstrap 스킬 참조. 완료 후 _workspace/03_engineer_notes.md 작성.",
  run_in_background: true
)
```

두 구현이 공유 의존(TEAM_TOOLS 시그니처)을 갖는 경우 먼저 team_engineer가 완료된 뒤 member_engineer를 순차 호출.

### Phase 4: 검증 (서브 에이전트)

구현 완료 직후 incremental QA:

```
Agent(
  name: "qa",
  subagent_type: "integration-qa",
  model: "opus",
  prompt: "src/langchain_harness/ 구현과 _workspace/01_architect_spec.md, _workspace/01_team_architect_spec.md, _workspace/02_skill_catalog.md를 cross-read하여 boundary contract를 검증. 11종 TEAM_TOOLS 시그니처 일치·모델 ID 고정·데이터 모델 drift·pytest tests/team/ 회귀 확인. _workspace/05_qa_report.md 생성.",
  run_in_background: false
)
```

- P0 이슈 존재 시 → 해당 engineer에게 재작업 요청 (`Phase 3` 부분 재실행)
- P1만 존재 → 가능한 한 즉시 fix, 불가능하면 사용자에게 수용 여부 질의
- 전부 PASS → Phase 5로 진행

### Phase 5: 진화 (선택, 사용자 승인 기반)

사용자가 실행 trace 또는 "개선" 요청 시:

```
Agent(
  name: "evaluator",
  subagent_type: "harness-evaluator",
  model: "opus",
  prompt: "_workspace/teams/{team}/runs/ 하위 trace와 01_architect_spec.md, 01_team_architect_spec.md를 읽고 개선 카드를 작성. trace-eval-loop 스킬 참조.",
  run_in_background: false
)
```

- 산출된 개선 카드를 사용자에게 제시 → 승인 카드만 Phase 2 또는 Phase 3의 부분 재실행으로 투입

### Phase 6: 정리 및 인덱싱

1. `_workspace/` 보존 (삭제 금지, .gitignore에 추가됨)
2. CLAUDE.md의 변경 이력 테이블에 이번 변경 append
3. 사용자에게 요약:
   - 무엇이 생성/변경되었는지 (파일 단위)
   - 실행 방법 (`uv run python -m langchain_harness.cli team ...`)
   - 다음 단계 제안 (스모크 실행, trace 수집)

## 데이터 흐름

```
사용자 요청
    ↓
[Phase 1] _workspace/00_request.md
    ↓
[Phase 2 — 팀]
    architect  ──→ _workspace/01_architect_spec.md        (상위 전략)
    arch_team  ──→ _workspace/01_team_architect_spec.md   (내부 프로토콜)
    curator    ──→ _workspace/02_skill_catalog.md + skills/*/SKILL.md
                   (+ multi-deepagent-team/references/protocol.md 동기화)
    (세 구성원 간 SendMessage 실시간 조율)
    ↓
[Phase 3 — 서브 병렬]
    team_engineer   → src/langchain_harness/team/* + _workspace/03_team_engineer_notes.md
    member_engineer → src/langchain_harness/{middleware,tools,config,cli,…}.py + _workspace/03_engineer_notes.md
    ↓
[Phase 4 — 서브] qa → _workspace/05_qa_report.md
    ↓ (P0 없으면)
[Phase 5 — 서브, 선택] evaluator → _workspace/04_*
    ↓
[Phase 6] CLAUDE.md 변경 이력 업데이트 + 사용자 보고
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 사용자 요구가 모호 | architect가 Phase 2 초입에 3가지 빌드 레시피 후보를 장단점과 함께 사용자에게 제시하여 선택 |
| 설계 팀 내 합의 실패 (SendMessage 3턴 이상 공전) | 리더가 개입하여 architect의 최종 결정을 채택 |
| 상위 전략과 내부 프로토콜 충돌 | architect와 arch_team 간 SendMessage 2라운드 후에도 불일치면 사용자에게 선택 질의 |
| 구현 중 `deepagents` API가 스펙과 다름 | engineer가 `_workspace/03_*engineer_notes.md`의 "Spec Deviations" 섹션에 기록, architect에게 notify |
| QA P0 | 해당 Phase 3 부분 재실행 (최대 2회). 3회째 실패 시 사용자에게 에스컬레이션 |
| 스모크 테스트 API 호출 실패 | rate-limit이면 재시도 1회, 키 문제면 QA를 advisory로 처리 |
| trace 없음 | Phase 5 스킵하고 "trace 수집 먼저 수행 필요" 안내 |
| 상충하는 개선 카드 여러 장 | 사용자에게 우선순위 질의. 임의 적용 금지 |
| TEAM_TOOLS 시그니처가 team_engineer와 member_engineer 사이에 drift | team_engineer가 single source of truth, member_engineer는 import로만 소비 |

## 테스트 시나리오

### 정상 흐름: 신규 팀 런타임 구축
1. 사용자: "대량 문서 병렬 요약 팀을 만들어줘 — 4명 reviewer가 공유 큐에서 집어가도록"
2. Phase 1: 도메인=문서처리, 성공지표=모든 문서 처리 완료, 제약=sandbox
3. Phase 2: 설계 팀 구성
   - architect: Build Recipe=Swarm, coordinator + 4 reviewer, InboxPoll 필수
   - arch_team: tasks.jsonl claim 프로토콜, `read_inbox` 폴링 주기 확정
   - curator: doc-summary 스킬 초안 + reviewer 역할 SKILL.md
4. Phase 3: team_engineer가 `src/langchain_harness/team/*` 구현(또는 기존 확장), member_engineer가 `summary_agent_factory.py` 작성
5. Phase 4: QA → 11종 도구 시그니처·모델 ID·pytest tests/team/ 모두 PASS
6. 결과: `uv run python -m langchain_harness.cli team create --team-name docs ...` 기동 가능

### 에러 흐름: 구현 중 API 불일치
1. team_engineer가 `create_deep_agent(interrupt_on=...)` 호출 시 API 시그니처가 스펙과 다름 발견
2. `03_team_engineer_notes.md`에 deviation 기록 → arch_team에게 SendMessage
3. arch_team이 스펙 revision 1 추가: `interrupt_on` 사용 불가, 대체로 `PreCompletionChecklistMiddleware`로 pause 구현
4. team_engineer 재구현 → QA PASS
5. 최종 보고서에 "Spec revision 1 발생, 사유 기록" 포함

### 후속 흐름: 개선 요청
1. 사용자: "지난주 실행에서 reviewer끼리 같은 문서를 두 번 집어가는 중복 claim이 자주 보여. 개선해줘"
2. Phase 0: `_workspace/teams/{team}/runs/` 존재 확인 → **진화 모드**
3. Phase 5: evaluator가 trace 분석 → "tasks/{id}.json의 CAS 버전 불일치 허용 범위를 줄이고 `expected_status=open` 강제" 개선 카드
4. 사용자 승인 → Phase 3 부분 재실행 (team/tasks.py만 수정)
5. Phase 4 QA → 회귀 테스트 세트 통과 확인 (H4 Task claim race-free)
6. CLAUDE.md 변경 이력 append

## 후속 작업 트리거 키워드 (description 확장 보강)

초기 구축 외에도 반드시 이 스킬이 발동해야 하는 표현:
- "하네스 다시 / 재실행 / 업데이트 / 보완 / 수정 / 개선"
- "{서브에이전트 이름} 추가 / 변경 / 삭제"
- "middleware 추가 / 교체"
- "스킬 추가 / 확장"
- "trace 분석 / 회귀 확인 / 실패 모드 분석"
- "hardening / robustness / 안정화"
- "팀 런타임 빌드 / 확장 / 축소"
- "teammate 추가 / 해체 / 재구성"
- "팀 재설계 / 빌드 레시피 변경 / Supervisor → Swarm 전환"

## 관련 스킬

- `multi-deepagent-team` — 팀 런타임 설계·운영 가이드 (Phase 2의 arch_team이 반드시 참조)
- `deepagents-bootstrap` — 프로젝트 스캐폴드
- `middleware-patterns` — 5가지 미들웨어 템플릿
- `langchain-opus` — Claude Opus 4.7 + LangChain 통합 베스트 프랙티스
- `trace-eval-loop` — 실행 trace 분석 · 회귀 테스트
- `skill-bundling` — deep-agent용 스킬 작성 방법

## Revisions

- 2026-04-18: Phase 2-팀 브랜치(2B) 추가. team-runtime-architect / team-messaging-engineer 에이전트 등재. multi-deepagent-team 스킬 참조 경로 삽입.
- 2026-04-18: 단일 에이전트·메타 경로 제거. Multi-DeepAgent Team 런타임을 유일 경로로 단일화. Phase 2A/2B 분기 제거, architect/arch_team/curator 3인 팀으로 재구성. Phase 3는 team_engineer + member_engineer 병렬 서브 호출.
