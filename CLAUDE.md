# langchain-harness — Project Context

Claude Opus 4.7 + LangChain `deepagents` + Anthropic ADK로 런타임 구성 가능한 **딥에이전트 하네스 엔진**을 개발하는 프로젝트.

## 하네스: harness-engineering

**목표:** 사용자 과제에 맞춰 에이전트·스킬·미들웨어를 실시간 구성하고, 실행 trace를 기반으로 지속 고도화한다.

**트리거:** 아래 요청 시 반드시 `harness-engineering` 스킬을 사용하라.
- 새로운 하네스 구축, 확장, 리팩터
- 미들웨어/서브에이전트/스킬 추가·수정·삭제
- trace 기반 실패 분석, 개선 카드 요청
- "하네스", "딥에이전트", "에이전트 시스템", "하네스 고도화", "재실행", "업데이트", "보완" 등
- 단순 Python 문법 질문은 직접 응답 가능 (스킬 우회).

**핵심 구성 (에이전트 5 · 스킬 6):**
- 에이전트: `harness-architect`, `deepagent-engineer`, `skill-curator`, `harness-evaluator`, `integration-qa`
- 스킬: `harness-engineering`(오케스트레이터), `deepagents-bootstrap`, `middleware-patterns`, `langchain-opus`, `trace-eval-loop`, `skill-bundling`

**모델 ID 규약:** 코드에서 모델을 지정할 때 반드시 `claude-opus-4-7`. 다른 ID 사용 시 boundary QA가 P0로 실패 처리한다.

**실행 규약:**
- 모든 Agent 도구 호출에 `model: "opus"` 명시
- 산출물은 `_workspace/` 경유. 최종 코드만 `src/`에 둔다
- 실행 trace는 `_workspace/runs/{run_id}.jsonl`

## 변경 이력

| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-04-18 | 초기 구성 (에이전트 5, 스킬 6, Python 스캐폴드) | 전체 | 하네스 엔진 프로젝트 출범 |
