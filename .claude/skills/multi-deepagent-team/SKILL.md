---
name: multi-deepagent-team
description: "여러 DeepAgent 인스턴스를 하나의 팀으로 묶어 메일박스 기반 메시지와 공유 태스크 큐로 자율 협업시키는 런타임 설계·구현·운영 가이드. 'Multi-DeepAgent', '멀티 에이전트', 'AgentTeam', '팀 런타임', '팀 빌드', '팀 스폰', '팀 해체', '팀 추가', '팀 재구성', 'teammate', 'team lead', 'mailbox', 'send_message', 'broadcast', 'team_task', 'shared task list', '팀 컨텍스트', '팀 모드로 실행', '여러 에이전트 협업', 'supervisor 패턴', '자율 협업 에이전트', '생성-검증 팀', 'AgentTeamHarness', '_workspace/teams' 등 다수 DeepAgent가 **한 팀으로 함께 실행**되는 과제에 반드시 이 스킬을 사용한다. 단, 단일 DeepAgent(create()) 또는 LangGraph Supervisor(meta/) 경로만 다루는 경우 이 스킬은 쓰지 않는다."
---

# Multi-DeepAgent Team Runtime

여러 DeepAgent 인스턴스가 **하나의 팀**으로 묶여 메일박스 · 공유 태스크 큐 · 팀 컨텍스트를 공유하며 자율 조율하도록 만든 런타임. 단일 에이전트 경로(`create()`)와 LangGraph 기반 Meta-Supervisor(`meta/`)와는 독립된 세 번째 경로다.

## 1. 언제 이 스킬을 쓰는가 / 쓰지 않는가

### 쓴다
- 사용자가 "멀티 DeepAgent", "에이전트 팀", "여러 에이전트가 협업", "메일박스로 통신" 등을 명시
- 하나의 과제를 여러 역할(예: 생성자 + 검증자, 리드 + 러너)이 **동시 실행**하며 **서로 메시지**를 주고받아야 할 때
- 팀원 수·구성이 **런타임에 변동**되어야 할 때 (lead가 러너를 추가 스폰)
- 팀 상태(메일박스, 태스크 큐)가 **파일 기반으로 영속화**되어 세션·프로세스 경계를 넘어 조회되어야 할 때
- `AgentTeamHarness`, `team_create`, `spawn_teammate`, `send_message`, `team_task_create` 등 팀 프리미티브 등장 시

### 쓰지 않는다
- **단일** DeepAgent로 충분한 과제 → `deepagents-bootstrap` + 단순 `create()`
- LangGraph `Supervisor` 기반 파이프라인(이미 `meta/`에 있음) — 고정 토폴로지, 메일박스 없음
- SendMessage 없이 순차 파이프 호출만 필요 → `subagents=[...]` 파라미터로 충분

### 경계 규칙
| 요청 표현 | 써야 할 스킬 |
|----------|-------------|
| "팀으로 협업시켜줘" · "팀 lead가 teammate 스폰" · "메일박스" | **multi-deepagent-team** |
| "새 하네스 만들어줘" · "미들웨어 추가" (팀 무관) | harness-engineering |
| "프로젝트 초기화" · "pyproject 스캐폴드" | deepagents-bootstrap |
| "루프 방지 미들웨어" · "LocalContext 주입" | middleware-patterns |

## 2. 핵심 개념

| 개념 | 정의 | 저장 위치 |
|------|------|----------|
| **Team** | 이름이 부여된 러닝 세션. 1 프로세스 1 팀 제약으로 시작 | `_workspace/teams/{team_name}/team.json` |
| **Teammate** | 팀에 속한 DeepAgent 인스턴스. 역할(role) + 프로필(profile) + 모델 지정 | `teammates/{mate_id}/config.json` |
| **Team Lead** | 팀을 생성한 teammate. teammate 스폰/해체 권한. 재스폰 금지 | team.json의 `lead_id` |
| **Mailbox** | teammate별 수신함. append-only JSONL. send_message/broadcast 수신처 | `teammates/{mate_id}/mailbox.jsonl` |
| **Shared Task List** | 팀 전체 공용 태스크 큐. claim/update/complete 프로토콜 | `tasks.jsonl` |
| **Team Context** | 팀 공용 지식 파일(role charter, 공유 결정). 읽기 공용, 쓰기는 owner만 | `context/*.md` |

**Why 팀 프리미티브인가?** `subagents=[...]`는 호출자가 하나의 전체 프롬프트를 관리해야 하고 양방향 교신이 없다. 팀은 비동기 메일박스와 태스크 큐를 통해 **에이전트 스스로가 조율**하게 만든다. 복잡한 과제일수록 중앙 플래너가 병목이 된다.

## 3. 파일 레이아웃

```
_workspace/teams/{team_name}/
├── team.json                 # 팀 메타 (name, lead_id, created_at, status)
├── registry.json             # teammate id → role 매핑 (중복 role 허용)
├── tasks.jsonl               # shared task list (append-only 이벤트 로그)
├── broadcast.jsonl           # 브로드캐스트 기록 (감사용)
├── context/
│   ├── charter.md            # 팀 미션 선언
│   └── decisions.md          # 공유 결정 로그
└── teammates/
    └── {mate_id}/
        ├── config.json       # role, model, profile, spawned_by
        ├── mailbox.jsonl     # append-only 수신함
        └── state/            # teammate 고유 작업 공간 (파일 자유)
```

**Why 파일 기반?** 외부 DB 금지 제약 + 세션·프로세스 경계 넘어 조회 가능 + trace-eval-loop가 동일 레이아웃을 읽어 실패 분석에 재사용 가능.

**append-only JSONL** 선택 이유: 동시 쓰기 시 개행 단위 원자성에 의존해 락 복잡도를 최소화. 읽기 측은 전체 스캔 + in-memory projection.

## 4. 팀 lifecycle

```
[T0 team_create]
    └─ team.json + lead teammate config + mailbox 생성
       └─ charter.md 초기 작성 (lead가)

[T1..Tn 운영]
    ├─ spawn_teammate(role=..., prompt=...) → teammates/{new_id} 생성
    ├─ send_message(to=mate_id, type=..., body=...) → 대상 mailbox.jsonl append
    ├─ broadcast(type=..., body=...) → 모든 teammate mailbox + broadcast.jsonl append
    ├─ team_task_create/claim/update/complete → tasks.jsonl append
    └─ team_context_write(path, content, owner=...)

[Tend team_shutdown]
    └─ 모든 teammate "drain" 신호 수신 → 진행 중 태스크 마감 → status=archived
       (파일은 보존, trace-eval-loop가 후분석)
```

생명주기 불변식:
- 1 세션 = 1 팀 (참조 구현 규약). 두 팀 동시 운영 금지
- lead는 재스폰 불가. lead가 죽으면 팀 전체 shutdown
- teammate 스폰·해체는 lead만 수행

## 5. 메시지 프로토콜 개요

메시지 단위는 `mailbox.jsonl`의 한 줄 = 하나의 이벤트.

**공통 필드:**
```json
{
  "id": "msg_<ulid>",
  "ts": "2026-04-18T11:45:00Z",
  "from": "<mate_id>",
  "to": "<mate_id>|*",
  "type": "text|task_assigned|task_result|question|ack|broadcast|system",
  "body": "<string or structured payload>",
  "refs": ["msg_...", "task_..."]
}
```

**타입별 의미:**
- `text` — 자유 서술. 내부 reasoning 공유
- `task_assigned` — body에 `task_id` + 지시. 수신자가 claim 후 작업
- `task_result` — body에 `task_id` + 결과 + 링크. claim 해제
- `question` — 수신자에게 응답 요청. refs로 질문 원본 연결
- `ack` — 읽음 확인. 필수 아니지만 장시간 무응답 문제 분리용
- `broadcast` — 수신자 `*`. 모두에게 append
- `system` — 런타임이 주입 (팀 shutdown 경고, 태스크 timeout 등)

> **주의:** 전체 JSON Schema는 architect 스펙 `_workspace/01_team_architect_spec.md` 확정 후 `references/protocol.md`에서 동기화한다. 불일치 발견 시 이 본문보다 `references/protocol.md`를 우선.

## 6. 팀 도구 목록과 사용 시점

| 도구 | 누가 | 언제 | 주요 인자 |
|------|------|------|-----------|
| `team_create` | 부트 스크립트 | 팀 시작 1회 | name, lead_profile, charter |
| `spawn_teammate` | lead만 | 러너 추가 필요 시 | role, model=`opus`, profile_prompt, initial_message |
| `send_message` | 모든 teammate | 1:1 교신 | to, type, body, refs |
| `broadcast` | lead 권장 / 모두 허용 | 전체 공지 · 결정 전파 | type, body |
| `read_mailbox` | 각자 본인만 | 매 턴 초입 권장 | since_id (증분 읽기) |
| `team_task_create` | 모두 허용 | 새 작업 추가 | title, description, assignee(optional) |
| `team_task_claim` | 모두 | unassigned 태스크 집기 | task_id |
| `team_task_update` | claimer | 진행 상태 기록 | task_id, note |
| `team_task_complete` | claimer | 완료 + 결과 반영 | task_id, result_ref |
| `team_context_read` | 모두 | 공유 지식 참조 | path |
| `team_context_write` | owner만 | 공유 지식 갱신 | path, content |
| `team_shutdown` | lead만 | 팀 종료 | drain_timeout_s |

**왜 claim 프로토콜인가?** 동일 태스크를 두 teammate가 중복 수행하는 낭비 방지. claim은 tasks.jsonl에 `event:claimed` 라인 append로 구현하고, 최신 projection으로 현재 owner를 결정.

## 7. 팀 빌드 레시피 3종

각 레시피는 `AgentTeamHarness` 위에 **프로필 + 초기 태스크 + 메시지 라우팅 룰**의 조합으로 실체화된다.

### (a) Supervisor 패턴 — 중앙 lead가 teammate에 지시

**Why:** 과제가 명확히 **분할 가능**하지만 각 분할의 **품질 편차**가 커서 중앙 조율이 필요한 경우(리서치, 다단계 리포트 작성).

```python
team = AgentTeamHarness.create(
    name="research-supervisor",
    lead=TeammateSpec(role="lead", model="opus",
        prompt="너는 리드다. 사용자 과제를 3~5개 서브태스크로 분할해 spawn_teammate로 러너를 만들고, team_task_assigned 메시지로 지시하라. 결과 수신 후 통합 보고서 작성."),
)
team.run_until_shutdown(user_task="경쟁사 A/B/C의 가격 전략 비교 분석")
```

- 라우팅: runner → lead만 `task_result`로 회신. 러너끼리 직접 대화 금지(브로드캐스트로 합의 필요 시만)
- 위험: lead 병목. lead가 러너 출력을 직렬 처리하면 토큰 사용 폭증 → `ReasoningBudgetMiddleware`를 lead에만 high로

### (b) 자율 협업 패턴 — 모두 동등, 태스크 큐에서 self pickup

**Why:** 과제가 **동질적인 다수 단위 작업**의 집합(1000개 파일 개별 리뷰, 대량 데이터 엔리치먼트)이어서 지시-결과 오버헤드가 낭비인 경우.

```python
team = AgentTeamHarness.create(
    name="swarm-review",
    lead=TeammateSpec(role="coordinator", model="opus",
        prompt="너는 좌장이다. 초기 태스크를 team_task_create로 쌓고, 모든 teammate가 claim/complete하게 하라. 진행 지연 발생 시에만 개입."),
)
for _ in range(4):
    team.spawn(role="reviewer", prompt="unassigned 태스크를 claim해 검토하고 결과를 team_task_complete에 기록하라.")
team.run_until_tasks_empty()
```

- 라우팅: 메시지보다 **태스크 큐가 1차 통신 매체**. send_message는 충돌 시에만
- 위험: race 조건 — `team_task_claim`이 tasks.jsonl 원자적 append에 의존. 동일 task_id를 두 명이 claim한 이벤트가 관측되면 먼저 기록된 라인이 우선(tie-break는 `ts` 오름차순)

### (c) 생성-검증 팀 — 생성자 1 + 검증자 1 고정 짝

**Why:** 품질 편차가 큰 생성 작업(코드 패치, 설계 문서)에서 **독립적 관점의 검증**이 품질을 크게 끌어올린다. 같은 모델이 자가 검증하는 것보다 프롬프트가 분리된 쌍이 실패를 더 잘 잡는다.

```python
team = AgentTeamHarness.create(
    name="maker-checker",
    lead=TeammateSpec(role="maker", model="opus",
        prompt="너는 생성자다. 과제 해결 드래프트를 작성 후 checker에 send_message(type=question, body=draft)로 검증 요청. checker 의견 받으면 개정. 3라운드 이상이면 사람에게 에스컬레이션."),
)
team.spawn(role="checker",
    prompt="너는 검증자다. maker의 draft에 대해 (1)결함, (2)미비점, (3)개선 제안 3가지를 짧게 회신. 통과 시 'APPROVED' 1단어만.")
team.run_until_approved()
```

- 라우팅: maker ↔ checker 핑퐁. 외부 브로드캐스트 없음
- 위험: 무한 핑퐁 → `PreCompletionChecklistMiddleware`의 `max_reminders`와 동형 가드로 라운드 수 제한

## 8. AgentTeamHarness 사용 예

```python
from langchain_harness.team import AgentTeamHarness, TeammateSpec

team = AgentTeamHarness.create(
    name="maker-checker",
    lead=TeammateSpec(role="maker", model="opus", prompt="..."),
)
team.spawn(role="checker", prompt="...")
team.run(user_task="Write a spec for feature X")
```

더 긴 예: `references/recipes.md`.

## 9. 미들웨어 조합 가이드

팀 모드에서 권장 스택 (단일 에이전트 default에 더하여):

| 미들웨어 | 팀 맥락 적용 이유 |
|---------|----------------|
| `LocalContextMiddleware` | 매 teammate가 자기 `state/` 디렉토리·charter.md·본인 role 알게 주입 |
| `PreCompletionChecklistMiddleware` | lead는 "모든 태스크 complete인가" / teammate는 "mailbox unread 0인가" 체크리스트 |
| `LoopDetectionMiddleware` | 동일 teammate에 같은 메시지 3회 보낸 경우 감지(새 항목) |
| `TraceAnalysisMiddleware` | `_workspace/teams/{team}/runs/` 하위에 teammate별 jsonl 저장 |
| (신규 제안) `MailboxDrainMiddleware` | 매 before_model에서 unread mailbox 비우기 강제. 미들웨어-patterns에 추가 후보 |

**Why 별도 가이드?** 단일 에이전트와 달리 `before_model` 훅에 "mailbox 읽기" 선행 필요 — 이 훅 누락 시 메시지가 오지만 모델이 못 보는 침묵 실패가 발생한다.

## 10. 안티패턴과 그 이유

| 안티패턴 | 왜 나쁜가 | 대안 |
|----------|---------|------|
| 팀 크기 8명 초과 | 브로드캐스트 cost가 n^2, lead 관리 실패 | 2-tier: lead가 sub-lead를 스폰해 재귀 팀 | 
| 브로드캐스트 남발 | 모든 mailbox append → 토큰 낭비 + 주의 분산 | 관심 있는 role만 대상으로 send_message |
| 순환 태스크 의존 | task A→B→A claim 데드락 | 태스크 생성 시 `depends_on` 사이클 감지 |
| teammate가 lead 재스폰 | 책임 주체 모호 → 이중 shutdown | lead 권한은 시작 시점에 고정 |
| send_message로 대용량 payload | mailbox.jsonl 비대화 + 읽기 비용 | context/ 에 파일 쓰고 message엔 경로만 |
| mailbox를 읽지 않고 작업 | 메시지 침묵 실패 | before_model에서 `read_mailbox(since_id)` 강제 |
| 태스크 claim 후 무응답 | 진행 상태 블랙홀 | 주기적 `team_task_update` 필수화, timeout 시 자동 release |
| 같은 role 이름 여러 teammate 혼용 인자 없이 | 메시지 라우팅 모호 | role이 같더라도 mate_id로 지정 |

## 11. 트러블슈팅

### 고아 teammate (lead 죽었는데 살아있음)
- 증상: tasks.jsonl 정체, mailbox는 계속 append
- 원인: lead 프로세스 크래시 후 `team_shutdown` 미호출
- 복구: `team.json.status = "orphaned"`로 마킹 스크립트 → 다음 세션 시작 시 archive 처리

### 메일박스 손상 (JSONL 깨짐)
- 증상: `read_mailbox` 파싱 에러
- 원인: 동시 append에서 partial write (파일 시스템 버퍼 flush 실패) 또는 외부 편집
- 복구: 깨진 라인부터 끝까지 `.broken` 롤아웃 → 남은 prefix만 projection. 팀 전체 broadcast로 "마지막 id 재전송 요청"

### 태스크 락업 (claim 후 N분 무응답)
- 증상: tasks.jsonl projection에서 claimed 상태 지속
- 원인: claimer가 crash 또는 무한 루프
- 복구: 런타임이 `system` 타입 메시지를 claimer에 발송 + timeout 초과 시 `event:released` 자동 append → 다른 teammate가 재claim 가능

### 중복 claim (같은 task_id를 두 명이 claim)
- 증상: projection 이상
- 원인: append 동시성 문제
- 복구: `ts` 오름차순 tie-break. 진 쪽은 자신의 `state/`에서 롤백 + 다른 태스크 찾기

## 12. 데이터 스키마 동기화 주의

- 이 SKILL.md의 스키마·도구 시그니처는 **초안**. architect가 `_workspace/01_team_architect_spec.md`를 확정하면 `references/protocol.md`로 세부 스키마를 이관·보강한다
- 본문 vs `references/protocol.md` 충돌 시 references 우선
- 스키마 변경 시 이 SKILL.md는 "개요 + 포인터"만 유지. 확장은 references/로

## 관련 참조

- [references/protocol.md](references/protocol.md) — 메시지 타입별 전체 스키마 (architect 스펙 확정 후)
- [references/recipes.md](references/recipes.md) — 빌드 레시피 3종 풀 코드 예시
- [references/troubleshooting.md](references/troubleshooting.md) — 실패 모드·복구 절차 상세
- `middleware-patterns` 스킬 — `MailboxDrainMiddleware` 등 팀 전용 미들웨어 추가 예정
- `deepagents-bootstrap` 스킬 — 프로젝트 구조(`src/langchain_harness/team/`) 스캐폴드 시 참조
- `harness-engineering` 스킬 — Phase 2 팀 빌드 경로의 entry point
