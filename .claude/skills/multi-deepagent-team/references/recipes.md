# Team Build Recipes — Full Code

SKILL.md 본문 §7에 요약된 3종 레시피의 풀 코드. `AgentTeamHarness`가 구현되기 전까지는 **참조 슈도코드**로 읽는다. 최종 시그니처는 `src/langchain_harness/team/runtime.py` 확정 시 이 파일을 갱신.

## (a) Supervisor 패턴

```python
from langchain_harness.team import AgentTeamHarness, TeammateSpec


LEAD_PROMPT = """너는 research-supervisor 팀의 리드다.
1) 사용자 과제를 3~5개의 독립 서브태스크로 분할해 team_task_create로 등록
2) 러너가 필요하면 spawn_teammate(role='runner', ...)로 생성
3) 각 러너에게 task_assigned 메시지로 지시 (body.task_id 포함)
4) 모든 task_result 수신 후 통합 보고서 작성
5) team_shutdown(drain_timeout_s=60)로 팀 해체

러너간 직접 대화는 허용하지 않는다. 러너가 서로 합의가 필요하면 너에게 question으로 올린다."""

RUNNER_PROMPT = """너는 러너다.
- 매 턴 시작 시 read_mailbox(since_id=...)로 unread를 비운다
- task_assigned를 받으면 team_task_claim(task_id) 후 수행
- 완료 시 team_task_complete(task_id, result_ref=state/out.md) + lead에 task_result 전송
- 애매하면 lead에 question 전송 (runner끼리 대화 금지)"""


def build_supervisor_team(user_task: str) -> None:
    team = AgentTeamHarness.create(
        name="research-supervisor",
        lead=TeammateSpec(role="lead", model="opus", prompt=LEAD_PROMPT),
        charter=f"Mission: {user_task}\nStyle: evidence-based, cite sources.",
    )
    # 러너는 lead가 런타임에 스폰. 초기엔 lead만.
    team.run(user_task=user_task)
```

주의:
- lead는 `spawn_teammate` 호출 시 러너 프롬프트에 RUNNER_PROMPT를 inject
- lead 토큰 병목을 줄이려면 `ReasoningBudgetMiddleware(plan_budget=12000, impl_budget=2000)`를 lead에만

## (b) 자율 협업 패턴

```python
from langchain_harness.team import AgentTeamHarness, TeammateSpec


COORD_PROMPT = """너는 swarm의 coordinator다.
시작 시: 사용자 과제에서 동질적 단위 작업 목록을 도출해 team_task_create로 전부 쌓는다.
운영 중: 태스크 claim/complete를 관찰만 한다. 지연 발생 시 (timeout 초과 task 관측 시)
    - claimer에게 question으로 상태 질의
    - 재할당이 필요하면 system 권한으로 released 이벤트 append 후 재생성
완료 조건: tasks.jsonl projection에서 open 태스크 0개."""

REVIEWER_PROMPT = """너는 reviewer다.
매 턴:
1) read_mailbox (broadcast 및 question 처리 우선)
2) team_task_claim(다음 unassigned task) - 없으면 idle broadcast 후 종료
3) 내용 검토 후 team_task_update로 진행 노트 남김
4) team_task_complete(task_id, result_ref=state/review_{task_id}.md)

다른 reviewer와 직접 메시지 불필요. 중복 관측 시 ts 오름차순 승자 규칙에 따라 포기."""


def build_swarm_team(user_task: str, runners: int = 4) -> None:
    team = AgentTeamHarness.create(
        name="swarm-review",
        lead=TeammateSpec(role="coordinator", model="opus", prompt=COORD_PROMPT),
        charter=f"Mission: {user_task}\nMode: autonomous swarm.",
    )
    for i in range(runners):
        team.spawn(role="reviewer", prompt=REVIEWER_PROMPT)
    team.run_until_tasks_empty(idle_shutdown_s=30)
```

주의:
- runners 수는 team.json의 size 제한(8명)을 지키자. coordinator 포함.
- idle broadcast로 "unassigned 0" 상태를 알리고, coordinator가 일정 시간 후 shutdown

## (c) 생성-검증 팀 (Maker-Checker)

```python
from langchain_harness.team import AgentTeamHarness, TeammateSpec


MAKER_PROMPT = """너는 maker다. 라운드 제한 3회.
라운드 n:
1) 이전 checker 피드백(있다면)을 반영해 드래프트 revise
2) 초안은 state/draft_r{n}.md로 저장
3) checker에 send_message(type=question, body={prompt:'review r{n}', expected:'structured'}, refs=[prev_draft_msg])
4) checker의 text 응답 수신 대기. 'APPROVED' 수신 시 team_task_complete 후 shutdown 요청.
라운드 3에서도 미승인 시 lead broadcast로 사람 에스컬레이션."""

CHECKER_PROMPT = """너는 checker다.
매 question 수신 시:
1) 드래프트(state/draft_r{n}.md) read
2) 결함/미비점/개선점 각 최대 3가지 bullet로 회신 (send_message type=text)
3) 통과 기준 충족 시 단어 'APPROVED'만 전송 (bullet 금지)
통과 기준은 charter.md의 acceptance_criteria 섹션 참조."""


def build_maker_checker_team(user_task: str) -> None:
    team = AgentTeamHarness.create(
        name="maker-checker",
        lead=TeammateSpec(role="maker", model="opus", prompt=MAKER_PROMPT),
        charter=f"""Mission: {user_task}

acceptance_criteria:
- 요구사항의 모든 필수 항목 충족
- 외부 의존성 명확히 문서화
- 예외 흐름 최소 2개 기술""",
    )
    team.spawn(role="checker", prompt=CHECKER_PROMPT)
    team.run_until_approved(max_rounds=3)
```

주의:
- 무한 핑퐁 방지: `max_rounds`를 런타임이 강제. 초과 시 `system` 메시지로 사람 에스컬레이션
- checker가 너무 관대하면 charter의 acceptance_criteria를 강화 — 프롬프트보다 charter가 공유 불변 조건

## 3종 비교

| 특성 | Supervisor | Autonomous Swarm | Maker-Checker |
|------|-----------|------------------|---------------|
| 통신 매체 | send_message 중심 | tasks.jsonl 중심 | send_message 핑퐁 |
| 병목 위치 | lead | 없음(데이터) | maker ↔ checker |
| 적합 과제 | 이질적 서브태스크 | 동질적 대량 작업 | 품질 편차 큰 생성 |
| 권장 팀 크기 | 1 lead + 2~4 runner | 1 coord + 3~6 | 고정 2명 |
| 주요 실패 모드 | lead 토큰 폭증 | claim race | 무한 핑퐁 |
