---
name: harness-engineering
description: "LangChain deepagents + Anthropic ADK + Claude Opus 4.7 기반 딥에이전트 하네스를 설계·구현·평가·진화시키는 오케스트레이터. 새 하네스 구축, 기존 하네스 고도화, 실패 trace 기반 개선, 미들웨어/스킬/서브에이전트 추가, '하네스 만들어줘', '하네스 개선', '딥에이전트 구성', '고난이도 과제 자동화', '에이전트 시스템', 'LangChain 프로젝트', 'harness engineering', '재실행', '다시 실행', '업데이트', '수정', '보완', '이전 결과 개선' 등 하네스 관련 모든 요청에 반드시 이 스킬을 사용. 단순 Python 문법 질문 등은 제외."
---

# Harness Engineering Orchestrator

LangChain `deepagents` + Anthropic Claude Agent SDK(ADK) + Claude Opus 4.7을 결합한 **딥에이전트 하네스**를 구축·고도화하는 통합 워크플로우.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| Phase 2 (설계) | 에이전트 팀 | architect + skill-curator 간 스펙 토론·합의 |
| Phase 3 (구현) | 서브 에이전트 | deepagent-engineer 단독 코드 생성, 팀 통신 불필요 |
| Phase 4 (검증) | 서브 에이전트 | integration-qa 독립 검증 |
| Phase 5 (진화) | 서브 에이전트 또는 팀 | 단일 trace 분석은 서브, 대규모 개선 토론은 팀 |

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 관련 스킬 | 주 산출물 |
|---------|--------------|------|----------|----------|
| harness-architect | harness-architect | 스펙 설계 | middleware-patterns, langchain-opus | `_workspace/01_architect_spec.md` |
| skill-curator | skill-curator | 스킬 카탈로그 | skill-bundling | `_workspace/02_skill_catalog.md`, `skills/` |
| deepagent-engineer | deepagent-engineer | Python 구현 | deepagents-bootstrap, langchain-opus | `src/langchain_harness/*` |
| integration-qa | integration-qa | 경계면 검증 | — | `_workspace/05_qa_report.md` |
| harness-evaluator | harness-evaluator | Trace 기반 개선 | trace-eval-loop | `_workspace/04_*` |

> 모든 Agent 호출에 `model: "opus"` 명시. 모든 커스텀 서브에이전트는 내부적으로 `claude-opus-4-7`를 사용.

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

1. `_workspace/` 디렉토리 존재 여부 확인
2. `src/langchain_harness/` 존재 여부 확인
3. 실행 모드 결정:
   - **둘 다 미존재** → 초기 구축. Phase 1부터 전체 실행
   - **`_workspace/` 존재 + 사용자가 "다시/재실행/업데이트/수정" 언급** → **부분 재실행**. 영향받는 에이전트만 재호출, 기존 산출물은 해당 파일만 덮어쓰기
   - **둘 다 존재 + 사용자가 새 요구사항 제공** → **확장 모드**. 기존 스펙을 baseline으로 두고 delta만 반영
   - **`src/` 존재 + trace 분석 요청** → **진화 모드**. Phase 5만 실행
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

1. 팀 생성:
   ```
   TeamCreate(
     team_name: "harness-design-team",
     members: [
       { name: "architect", agent_type: "harness-architect", model: "opus",
         prompt: "사용자 요청(_workspace/00_request.md)을 읽고 Harness Spec을 작성하라. middleware-patterns, langchain-opus 스킬을 참조." },
       { name: "curator", agent_type: "skill-curator", model: "opus",
         prompt: "architect가 작성 중인 스펙을 지속 모니터하며 스킬 카탈로그를 병행 설계하라. skill-bundling 스킬 참조." }
     ]
   )
   ```
2. 작업 등록:
   ```
   TaskCreate(tasks: [
     { title: "Behavior Goals + Failure Modes 확정", assignee: "architect" },
     { title: "Topology + Middleware Stack 결정", assignee: "architect" },
     { title: "Subagents/Permissions/Memory 결정", assignee: "architect" },
     { title: "스킬 후보 식별", assignee: "curator", depends_on: ["Behavior Goals + Failure Modes 확정"] },
     { title: "SKILL.md 초안 작성 (스킬별)", assignee: "curator" },
     { title: "AGENTS.md 초안 작성", assignee: "curator" }
   ])
   ```
3. 팀원 간 직접 토론 허용 — SendMessage 경로:
   - architect ↔ curator: 스펙 변경이 스킬에 미치는 영향 실시간 공유
4. 팀 정리 전 검증: 두 산출물이 서로 참조 가능하고 모순 없는지 리더가 리뷰
5. `TeamDelete`로 설계 팀 해체

### Phase 3: 구현 (서브 에이전트)

단일 서브 에이전트 호출로 구현 담당:

```
Agent(
  name: "engineer",
  subagent_type: "deepagent-engineer",
  model: "opus",
  prompt: "_workspace/01_architect_spec.md와 _workspace/02_skill_catalog.md를 읽고 src/langchain_harness/ 패키지를 구현하라. deepagents-bootstrap 스킬에서 프로젝트 스캐폴드 참조. langchain-opus 스킬에서 모델 ID 'claude-opus-4-7', prompt caching, extended thinking 설정법 참조. 완료 후 _workspace/03_engineer_notes.md에 결정 사항 기록.",
  run_in_background: false
)
```

### Phase 4: 검증 (서브 에이전트)

구현 완료 직후 incremental QA:

```
Agent(
  name: "qa",
  subagent_type: "integration-qa",
  model: "opus",
  prompt: "src/langchain_harness/ 구현과 _workspace/01_architect_spec.md, _workspace/02_skill_catalog.md를 cross-read하여 boundary contract를 검증하라. ANTHROPIC_API_KEY 설정 시 스모크 테스트 1턴 실행. _workspace/05_qa_report.md 생성.",
  run_in_background: false
)
```

- P0 이슈 존재 시 → engineer에게 재작업 요청 (`Phase 3` 부분 재실행)
- P1만 존재 → 사용자에게 수용 여부 질의 후 진행
- 전부 PASS → Phase 5로 진행

### Phase 5: 진화 (선택, 사용자 승인 기반)

사용자가 실행 trace 또는 "개선" 요청 시:

```
Agent(
  name: "evaluator",
  subagent_type: "harness-evaluator",
  model: "opus",
  prompt: "_workspace/runs/ 하위 trace와 01_architect_spec.md를 읽고 개선 카드를 작성하라. trace-eval-loop 스킬 참조.",
  run_in_background: false
)
```

- 산출된 개선 카드를 사용자에게 제시 → 승인 카드만 Phase 2 또는 Phase 3의 부분 재실행으로 투입

### Phase 6: 정리 및 인덱싱

1. `_workspace/` 보존 (삭제 금지)
2. CLAUDE.md의 변경 이력 테이블에 이번 변경 append
3. 사용자에게 요약:
   - 무엇이 생성/변경되었는지 (파일 단위)
   - 실행 방법 (`uv run python -m langchain_harness.cli ...`)
   - 다음 단계 제안 (스모크 실행, trace 수집)

## 데이터 흐름

```
사용자 요청
    ↓
[Phase 1] _workspace/00_request.md
    ↓
[Phase 2 — 팀]
    architect ──→ _workspace/01_architect_spec.md
    curator   ──→ _workspace/02_skill_catalog.md + skills/*/SKILL.md
    (양쪽 SendMessage로 실시간 조율)
    ↓
[Phase 3 — 서브] engineer → src/langchain_harness/* + _workspace/03_engineer_notes.md
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
| 사용자 요구가 모호 | architect가 Phase 2 초입에 3개 토폴로지 후보를 사용자에게 제시하여 선택 |
| 설계 팀 내 합의 실패 (SendMessage 3턴 이상 공전) | 리더가 개입하여 architect의 최종 결정을 채택 |
| 구현 중 `deepagents` API가 스펙과 다름 | engineer가 `_workspace/03_engineer_notes.md`의 "Spec Deviations" 섹션에 기록, architect에게 notify |
| QA P0 | Phase 3 부분 재실행 (최대 2회). 3회째 실패 시 사용자에게 에스컬레이션 |
| 스모크 테스트 API 호출 실패 | rate-limit이면 재시도 1회, 키 문제면 QA를 advisory로 처리 |
| trace 없음 | Phase 5 스킵하고 "trace 수집 먼저 수행 필요" 안내 |
| 상충하는 개선 카드 여러 장 | 사용자에게 우선순위 질의. 임의 적용 금지 |

## 테스트 시나리오

### 정상 흐름: 신규 하네스 구축
1. 사용자: "고난이도 SWE-Bench 스타일 버그 수정을 자동화하는 하네스를 만들어줘"
2. Phase 1: 도메인=코드수정, 성공지표=테스트통과, 제약=sandbox
3. Phase 2: 설계 팀 구성
   - architect: self-verification + loop detection + permissions(sandbox/workspace) 선정
   - curator: debug-reproduction, test-first-fix, patch-review 스킬 초안
4. Phase 3: engineer가 `src/langchain_harness/{agent,middleware,tools,cli}.py` + `pyproject.toml` 생성
5. Phase 4: QA → 모델 ID/import/스모크 테스트 모두 PASS
6. 결과: `uv run python -m langchain_harness.cli run "fix issue #123"` 기동 가능

### 에러 흐름: 구현 중 API 불일치
1. engineer가 `create_deep_agent(interrupt_on=...)` 호출 시 API 시그니처가 스펙과 다름 발견
2. `03_engineer_notes.md`에 deviation 기록 → architect에게 SendMessage
3. architect가 스펙 revision 1 추가: `interrupt_on` 사용 불가, 대체로 custom middleware로 pause 구현
4. engineer 재구현 → QA PASS
5. 최종 보고서에 "Spec revision 1 발생, 사유 기록" 포함

### 후속 흐름: 개선 요청
1. 사용자: "지난주 실행에서 같은 파일을 5번 수정하는 루프가 자주 발생했어. 개선해줘"
2. Phase 0: `_workspace/runs/` 존재 확인 → **진화 모드**
3. Phase 5: evaluator가 trace 분석 → "LoopDetection 임계치를 5→3으로 낮추고 cooldown 추가" 개선 카드
4. 사용자 승인 → Phase 3 부분 재실행 (middleware.py만 수정)
5. Phase 4 QA → 회귀 테스트 세트 통과 확인
6. CLAUDE.md 변경 이력 append

## 후속 작업 트리거 키워드 (description 확장 보강)

초기 구축 외에도 반드시 이 스킬이 발동해야 하는 표현:
- "하네스 다시 / 재실행 / 업데이트 / 보완 / 수정 / 개선"
- "{서브에이전트 이름} 추가 / 변경 / 삭제"
- "middleware 추가 / 교체"
- "스킬 추가 / 확장"
- "trace 분석 / 회귀 확인 / 실패 모드 분석"
- "hardening / robustness / 안정화"

## 관련 스킬

- `deepagents-bootstrap` — 프로젝트 스캐폴드
- `middleware-patterns` — 5가지 미들웨어 템플릿
- `langchain-opus` — Claude Opus 4.7 + LangChain 통합 베스트 프랙티스
- `trace-eval-loop` — 실행 trace 분석 · 회귀 테스트
- `skill-bundling` — deep-agent용 스킬 작성 방법
