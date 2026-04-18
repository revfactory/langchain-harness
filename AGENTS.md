# AGENTS.md — langchain-harness

Deep-agent의 장기 기억 파일. `HarnessConfig(agents_md=Path("AGENTS.md"))`로 주입하면 런타임에 `LocalContextMiddleware`가 읽어 시스템 메시지에 추가한다.

## 프로젝트 개요

- **목적**: LangChain `deepagents` + Anthropic ADK(Claude Agent SDK) + Claude Opus 4.7로 구축한 런타임 구성 가능 하네스 엔진
- **두 엔트리포인트**:
  - `HarnessConfig → create()` — 단일 deep-agent (단순 과제)
  - `MetaHarness().run(task)` — LangGraph Supervisor가 라우팅하는 6역할 팀 (복잡 과제)
- **핵심 구성요소**:
  - `src/langchain_harness/config.py` — 모델 ID, 기본 시스템 프롬프트
  - `src/langchain_harness/agent.py` — 단일 에이전트 팩토리 `create()`
  - `src/langchain_harness/middleware.py` — 5종 미들웨어
  - `src/langchain_harness/tools.py` — `read_file`, `write_file`, `bash`
  - `src/langchain_harness/meta/` — 메타 하네스 (schemas, roles, analyzer, composer, orchestrator, memory, evolution)
  - `src/langchain_harness/cli.py` — `langchain-harness run "..."` · `langchain-harness meta run "..."`

## Meta-Harness 역할 (순수 LangChain)

`meta/roles.py`에 정의된 6개 역할이 Supervisor-routed StateGraph로 협업한다:

| 역할 | 책임 | 허용 도구 |
|------|------|----------|
| architect | 스펙·실패 모드·토폴로지 정의 | read, write |
| engineer | 스펙 → 코드/커맨드/파일 | read, write, bash |
| curator | AGENTS.md 장기 기억 관리 | read, write |
| evaluator | trace 분류 + 개선 카드 | read, write |
| qa | 경계면 cross-read 검증 | read, write, bash |
| synthesizer | 최종 사용자 답 통합 | read |

Supervisor LLM은 TaskSpec + 최근 메시지를 보고 다음 actor를 결정하거나 `FINISH`를 반환한다.

## 코딩 컨벤션

- Python 3.11+, `from __future__ import annotations` 사용
- 타입 힌트 필수. 런타임 의존만 있는 import는 함수 내부에 (e.g. `deepagents`)
- 에러는 명확히 raise. silent fallback 금지
- `ruff`가 스타일 검사

## 도구 사용 규칙

- `read_file`: 파일 확인용. 직전 편집 결과를 다시 읽지 않는다 (상태 보존됨)
- `write_file`: 부분 수정이 아닌 파일 통째 대체에만 사용
- `bash`: 테스트·빌드·조사. `rm -rf`, `git push`, `--force` 류는 금지

## 평가 기준

1. `uv run python -m langchain_harness.cli info` 가 에러 없이 실행
2. `examples/hello.py`가 `ANTHROPIC_API_KEY` 존재 시 1턴 내 "ready" 유사 응답
3. `_workspace/runs/` 아래 JSONL 로그가 매 실행마다 생성
4. 미들웨어가 한 번도 발화하지 않는 실행은 의심 — 최소 `LocalContextMiddleware`는 1회 주입됨

## 알려진 함정

- **모델 ID 오타**: `claude-opus-4.7` (점 포함) 같은 표기는 Anthropic API에서 400 에러. 반드시 `claude-opus-4-7`
- **thinking + temperature=0**: Anthropic 제약으로 동시 설정 불가. thinking만 쓸 때는 temperature 생략
- **deepagents 버전 드리프트**: `create_deep_agent` 시그니처가 버전에 따라 다름 — `agent.py`의 TypeError 폴백 로직 확인
- **LoopDetectionMiddleware 오탐**: verify phase에서는 동일 파일 편집이 정상. `verify_trigger` 메시지 포함 시 비활성 고려

## 외부 리소스

- [LangChain blog: The anatomy of an agent harness](https://www.langchain.com/blog/the-anatomy-of-an-agent-harness)
- [LangChain blog: Improving deep agents with harness engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- [deepagents harness docs](https://docs.langchain.com/oss/python/deepagents/harness)
- [Anthropic Claude Agent SDK](https://docs.anthropic.com/en/api/agent-sdk)

## Revisions

| 날짜 | 변경 | 이유 |
|------|------|------|
| 2026-04-18 | 초기 작성 | 하네스 구성 시 |
| 2026-04-18 | Meta-Harness 역할 섹션 추가, 두 엔트리포인트 구분 | 순수 LangChain 메타 하네스 도입 |
