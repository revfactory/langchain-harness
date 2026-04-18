# AGENTS.md — langchain-harness

Deep-agent의 장기 기억 파일. `_workspace/teams/{team}/AGENTS.md`가 존재하면 `TeamContextMiddleware`가 우선 로드하고, 팀별 파일이 없으면 이 글로벌 AGENTS.md를 fallback으로 사용한다.

## 프로젝트 개요

- **목적**: LangChain `deepagents` + Anthropic ADK(Claude Agent SDK) + Claude Opus 4.7로 구축한 **Multi-DeepAgent Team 런타임**
- **단일 엔트리포인트**: `AgentTeamHarness(team_name=...).start()` — 다수의 DeepAgent 인스턴스가 파일 기반 메일박스·공유 태스크 큐로 자율 협업
- **핵심 구성요소**:
  - `src/langchain_harness/config.py` — 모델 ID, 기본 시스템 프롬프트, 워크스페이스
  - `src/langchain_harness/middleware.py` — 5종 공통 미들웨어
  - `src/langchain_harness/tools.py` — `read_file`, `write_file`, `bash` 공통 도구
  - `src/langchain_harness/team/` — 팀 런타임 (types · registry · mailbox · tasks · context · tools · middleware · runtime · cli)
  - `src/langchain_harness/cli.py` — `python -m langchain_harness.cli team …`

## 팀 프리미티브 요약

| 이름 | 역할 |
|------|------|
| `AgentTeamHarness` | 다수 DeepAgent 구동 런타임 호스트 (thread/sequential/process isolation) |
| `TeamContext` | 현재 에이전트의 팀·역할·메일박스 경로 식별 (contextvars + env fallback) |
| `TEAM_TOOLS` | 11종 LangChain 도구: team_create, team_delete, spawn_teammate, send_message, broadcast_message, read_inbox, team_task_create, team_task_claim, team_task_update, team_task_list, team_status |
| `team_middleware_stack()` | 공통 5종 + 팀 전용 2종(TeamContext, InboxPoll) |

## 파일 레이아웃

- 팀 상태: `_workspace/teams/{team}/` — config.json · mailbox/{agent}.jsonl · tasks/{id}.json · logs.jsonl · locks/
- 실행 trace: `_workspace/teams/{team}/runs/*.jsonl`
- 동시성: POSIX `O_APPEND` (JSONL) + `fcntl.LOCK_EX` + atomic rename + version CAS (JSON rewrite)

## 코딩 컨벤션

- Python 3.11+, `from __future__ import annotations` 사용
- 타입 힌트 필수. 런타임 의존만 있는 import는 함수 내부에 (e.g. `deepagents`)
- 에러는 명확히 raise. silent fallback 금지
- `ruff`가 스타일 검사

## 도구 사용 규칙

- `read_file`: 파일 확인용. 직전 편집 결과를 다시 읽지 않는다 (상태 보존됨)
- `write_file`: 부분 수정이 아닌 파일 통째 대체에만 사용
- `bash`: 테스트·빌드·조사. `rm -rf`, `git push`, `--force` 류는 금지
- 팀 도구: `current_team_context()`가 반환하는 `TeamContext`로 자동 팀 식별. 다른 팀의 메일박스/태스크를 직접 조작하지 않는다

## 평가 기준

1. `pytest tests/team/ -x -q` 모두 통과 (ANTHROPIC_API_KEY 없이)
2. `python -m langchain_harness.cli team --help` 에러 없이 출력
3. `python -c "from langchain_harness.team import TEAM_TOOLS; print(len(TEAM_TOOLS))"` → 11
4. 모든 모델 호출에 `claude-opus-4-7` 사용. 다른 ID 발견 시 P0

## 알려진 함정

- **모델 ID 오타**: `claude-opus-4.7`(점 포함) 은 Anthropic API 400 에러. 반드시 `claude-opus-4-7`
- **thinking + temperature=0**: Anthropic 제약으로 동시 설정 불가. thinking만 쓸 때는 temperature 생략
- **deepagents 버전 드리프트**: `create_deep_agent(middleware=...)` 시그니처는 버전에 따라 다름. 팀 멤버 스폰 시 TypeError 발생하면 middleware를 호환 경로로 교체
- **1 세션 1 팀 제약**: v1.0 규약. 두 팀 동시 운영 금지
- **Windows 비지원**: fcntl 비가용. darwin/linux만 지원
- **브로드캐스트 남발 금지**: 팀원 n명 시 n 번 mailbox append. 필요한 role만 send_message

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
| 2026-04-18 | 단일 에이전트·메타 경로 제거, Multi-DeepAgent Team 런타임 단일화 | 팀 런타임을 표준 경로로 채택 |
