# langchain-harness — Project Context

Claude Opus 4.7 + LangChain `deepagents` + Anthropic ADK로 실행되는 **Multi-DeepAgent Team 런타임 엔진**. 파일 기반 메일박스·공유 태스크 큐로 자율 조율하는 팀 런타임이 유일한 실행 경로.

## 하네스: harness-engineering

**목표:** 사용자 과제에 맞춰 팀(에이전트 수·역할·미들웨어·빌드 레시피)을 실시간 구성하고, 실행 trace를 기반으로 지속 고도화한다.

**트리거:** 아래 요청 시 반드시 `harness-engineering` 스킬을 사용하라.
- 새로운 팀 하네스 구축, 확장, 리팩터
- 미들웨어/teammate/스킬 추가·수정·삭제
- trace 기반 실패 분석, 개선 카드 요청
- "하네스", "딥에이전트", "에이전트 시스템", "팀 런타임", "teammate 추가", "빌드 레시피 변경", "하네스 고도화", "재실행", "업데이트", "보완" 등
- 팀 런타임 세부(메일박스·공유 태스크·spawn_teammate) drill-down은 `multi-deepagent-team` 스킬
- 단순 Python 문법 질문은 직접 응답 가능 (스킬 우회).

**핵심 구성 (에이전트 7 · 스킬 7):**
- 에이전트: `harness-architect`(상위 전략), `team-runtime-architect`(런타임 내부 설계), `deepagent-engineer`(팀 멤버 factory + 공통 기반), `team-messaging-engineer`(팀 프리미티브), `skill-curator`, `harness-evaluator`, `integration-qa`
- 스킬: `harness-engineering`(오케스트레이터), `multi-deepagent-team`, `deepagents-bootstrap`, `middleware-patterns`, `langchain-opus`, `trace-eval-loop`, `skill-bundling`

**단일 실행 경로:** `AgentTeamHarness(team_name=...).start()` — 다수 DeepAgent 인스턴스가 `_workspace/teams/{team}/` 하위의 mailbox·tasks·config를 공유하며 자율 조율. 단일 DeepAgent(create())와 LangGraph Supervisor(meta/) 경로는 2026-04-18부로 제거됨.

**모델 ID 규약:** 코드에서 모델을 지정할 때 반드시 `claude-opus-4-7`. 다른 ID 사용 시 boundary QA가 P0로 실패 처리한다.

**실행 규약:**
- 모든 Agent 도구 호출에 `model: "opus"` 명시
- 산출물은 `_workspace/` 경유(gitignore). 최종 코드만 `src/`에 둔다
- 팀 상태와 실행 trace는 `_workspace/teams/{team}/{config.json,mailbox/,tasks/,logs.jsonl,runs/}`

## 변경 이력

| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-04-18 | 초기 구성 (에이전트 5, 스킬 6, Python 스캐폴드) | 전체 | 하네스 엔진 프로젝트 출범 |
| 2026-04-18 | Meta-harness 레이어 추가 (LangGraph Supervisor + 6개 역할) | src/langchain_harness/meta/* | Claude Code 없이 순수 LangChain만으로 메타 하네스가 실행되도록 |
| 2026-04-18 | Multi-DeepAgent Team 런타임 추가 (mailbox + 공유 태스크 + 11 팀 도구 + AgentTeamHarness). `team-runtime-architect`, `team-messaging-engineer` 에이전트 2종 + `multi-deepagent-team` 스킬 등재. `harness-engineering` 오케스트레이터에 Phase 2B(팀 런타임 브랜치) 분기 추가 | src/langchain_harness/team/*, .claude/agents/team-*.md, .claude/skills/multi-deepagent-team/*, .claude/skills/harness-engineering/SKILL.md | 다수 DeepAgent 인스턴스가 파일 기반 메시지·태스크 큐로 자율 협업하는 제3 실행 경로 확보 |
| 2026-04-18 | QA P1 2건 fix: (P1-1) `multi-deepagent-team/references/protocol.md`를 types.MailboxEntry 실 스키마와 재동기화. (P1-2) `TeamStatusArgs`에 `heartbeat_ttl_sec` 필드 추가하여 orphan 판정 TTL의 단일 진실원천 확보 | .claude/skills/multi-deepagent-team/references/protocol.md, src/langchain_harness/team/tools.py | QA boundary cross-read에서 스펙 drift 2건 탐지 — follow-up 즉시 반영 |
| 2026-04-18 | 단일 DeepAgent(`create()`) 및 LangGraph Supervisor(`meta/`) 경로 제거. Multi-DeepAgent Team 런타임을 **유일한 실행 경로**로 단일화. `harness-architect`/`deepagent-engineer` 스코프 재정의(상위 전략 + 팀 멤버 factory로 축소). `harness-engineering` 오케스트레이터 Phase 2A/2B 분기 제거, 3인 설계 팀(architect/arch_team/curator) + 2인 병렬 구현(team_engineer/member_engineer)으로 재구성. 예제·README·AGENTS.md 팀 중심 재작성 | src/langchain_harness/{agent.py,meta/}(삭제), src/langchain_harness/{__init__.py,cli.py}, examples/, README.md, AGENTS.md, .claude/agents/{harness-architect,deepagent-engineer}.md, .claude/skills/{harness-engineering,multi-deepagent-team}/SKILL.md | 사용자 요청 — 단일/메타 경로 유지 불필요, 복잡도 감소 |

## Follow-up (QA P2, 다음 iteration)

- P2-1: `HarnessConfig.team_context` (`src/langchain_harness/agent.py:25`) 선언만 존재, `_collect_middleware/_collect_tools`에서 미소비 → placeholder를 실제 분기로 연결 필요
- P2-2: `multi-deepagent-team/SKILL.md §8` 및 `references/recipes.md`의 `AgentTeamHarness.create()`, `TeammateSpec`, `run_until_*` 등 API가 실제 구현과 drift → recipes 업데이트 필요
- P2-3: `tools.broadcast_message`가 `mailbox/_broadcast.jsonl`에 기록되지 않음 → `append_entry(recipient='*')` 분기 추가 필요 (감사 트레일 보강)
- P2-4: `mailbox.sweep_expired` 구현은 있으나 호출 스케줄 없음 → `InboxPollMiddleware` 또는 `AgentTeamHarness.tick()` 에 주기적 호출 삽입 필요
