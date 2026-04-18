# Team Message & Task Protocol

> **Status:** Synchronized with architect spec `_workspace/01_team_architect_spec.md` v1.0 and `src/langchain_harness/team/types.py`. SKILL.md 본문과 본 문서가 충돌하면 **본 문서가 우선**한다.

## 파일 레이아웃

```
_workspace/teams/{team_name}/
├── config.json                   # TeamFile (rewrite + flock + version CAS)
├── mailbox/
│   ├── {agent_name}.jsonl        # MailboxEntry — O_APPEND
│   ├── _broadcast.jsonl          # 브로드캐스트 원본 로그 — O_APPEND
│   └── payloads/
│       └── {message_id}.txt      # body 4KB 초과 시 분리 저장 (body_ref)
├── tasks/
│   ├── _index.jsonl              # task_id 생성 이벤트 (O_APPEND)
│   └── {task_id}.json            # TeamTask (rewrite + flock + version CAS)
├── locks/
│   ├── config.lock
│   └── task_{task_id}.lock
└── logs.jsonl                    # 전역 감사 로그 (O_APPEND)
```

## MailboxEntry 스키마

`mailbox/{name}.jsonl` 및 `mailbox/_broadcast.jsonl`의 각 라인.

```json
{
  "message_id": "8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c",
  "sender": "researcher",
  "recipient": "reviewer",
  "kind": "plain",
  "body": "자유 텍스트 또는 JSON-stringified payload",
  "body_ref": null,
  "created_at": "2026-04-18T11:45:00+00:00",
  "reply_to": null,
  "requires_ack": false,
  "status": "unread",
  "ttl_seconds": 60
}
```

**필드 계약 (types.MailboxEntry)**

| 필드 | 타입 | 규칙 |
|------|------|------|
| `message_id` | str | `uuid4().hex`. dedup 및 ack 매칭 키 |
| `sender` | str | agent_name (팀 내 유니크) |
| `recipient` | str | agent_name 또는 `*` (broadcast) |
| `kind` | Literal | 9종 중 택1 (아래) |
| `body` | str | 본문. 4KB 초과 시 `body_ref`로 분리되고 `body=""` |
| `body_ref` | str \| null | `payloads/{message_id}.txt` 상대 경로 |
| `created_at` | str | ISO8601 UTC |
| `reply_to` | str \| null | 응답이면 원본 `message_id` |
| `requires_ack` | bool | true면 수신자가 response 필수 |
| `status` | Literal | `unread` / `read` / `acked` / `expired` |
| `ttl_seconds` | int \| null | null이면 TTL 없음, 있으면 초과 시 `expired` 전이 |

## 메시지 kind 카탈로그

| kind | 방향 | requires_ack | body 의미 |
|------|------|--------------|-----------|
| `plain` | p2p or broadcast | false | 자유 텍스트 |
| `shutdown_request` | lead → member | **true** | `{"reason": str, "grace_sec": int}` JSON |
| `shutdown_response` | member → lead | false | `{"accepted": bool, "final_state": str}` |
| `task_assigned` | any → member | **true** | `{"task_id": str}` |
| `task_completed` | member → 관심 수신자 | false | `{"task_id": str, "artifacts": [str], "summary": str}` |
| `plan_approval_request` | member → lead | **true** | `{"plan": str, "risk": str}` |
| `plan_approval_response` | lead → member | false | `{"approved": bool, "note": str}` |
| `idle_escalation` | middleware → lead | false | `{"target": str, "idle_sec": int}` |
| `heartbeat_ping` | internal | false | `{"ts": iso8601}` (v1.0은 tool 호출 시 자동 갱신으로 대체, 별도 ping 비활성) |

## ack 정책

- `requires_ack=true` 메시지는 수신자가 **동일 `message_id`를 `reply_to`에 담은 응답**을 보낼 때까지 "pending".
- `status` 전이: `unread` → (`read_inbox()`) → `read` → (ack 수신) → `acked` 또는 (ttl 초과) → `expired`
- fire-and-forget: `plain`, `task_completed`, `shutdown_response`, `plan_approval_response`, `idle_escalation`, `heartbeat_ping`

## TeamTask 스키마

`tasks/{task_id}.json`의 단일 JSON 문서 (rewrite + CAS).

```json
{
  "task_id": "8f9a0b1c2d3e",
  "title": "한 줄 요약",
  "description": "세부 지시",
  "created_by": "lead",
  "assignee": "researcher",
  "status": "open",
  "priority": "P2",
  "depends_on": [],
  "artifacts": [],
  "claimed_by": null,
  "claimed_at": null,
  "updated_at": null,
  "completed_at": null,
  "version": 0,
  "result_summary": null
}
```

**status 전이:** `open` → `claimed` → `in_progress` → `done`
보조 상태: `blocked`, `cancelled`

**CAS 규칙:**
- `team_task_claim(task_id, expected_status="open")` — 현재 status가 `open`이 아니면 `VersionConflictError`
- `team_task_update(task_id, new_status, expected_version)` — `version` 불일치 시 `VersionConflictError`
- `depends_on`의 모든 선행 task가 `done`일 때만 claim 가능

## `tasks/_index.jsonl` 이벤트 로그

append-only. task 생성 시 1라인 기록.

```json
{"event": "created", "task_id": "...", "title": "...", "created_by": "...", "ts": "..."}
```

상태 전이 자체는 `{task_id}.json` 의 rewrite로 기록되며, `_index.jsonl`은 **생성 추적용**이다.

## Lifecycle 로그 (logs.jsonl)

전이마다 한 줄 append. kind 값:
- `spawn_requested`, `alive`, `idle_enter`, `resume`, `shutdown_enter`, `stopped`, `orphan_detected`
- `kind=send`, `kind=claim`, `kind=task_done`, `kind=corrupt_line`, `kind=ack_timeout`, `kind=flood_block`

## 동시성 계약

| 파일 유형 | 쓰기 패턴 | 규칙 |
|-----------|-----------|------|
| JSONL (mailbox, _broadcast, _index, logs) | multi-writer append | POSIX `O_APPEND`. 라인 ≤ 4096B 원자성에 의존 |
| JSON (config, task) | multi-writer rewrite | `fcntl.LOCK_EX` + atomic rename (`os.replace`) + version CAS |
| locks/*.lock | flock 전용 placeholder | 컨텐츠 없음 |

**라인 크기 초과 처리 (body 4KB+):**
- `body` → `payloads/{message_id}.txt`에 전문 저장
- entry의 `body`는 빈 문자열, `body_ref`에 상대 경로 저장
- 소비 시 `body_ref`가 있으면 payload 파일을 읽어 재구성

## 식별자 포맷

- `team_name` / `agent_name`: regex `^[a-z][a-z0-9_-]{1,31}$`
- `agent_id`: `{agent_name}@{team_name}` — 전역 유니크
- `task_id`: `uuid4().hex[:12]`
- `message_id`: `uuid4().hex` (32자)

## Open Questions (후속 개정)

- mailbox rotation 정책 (크기·시간 기반) — v1.1에서 검토
- cross-team 통신 — v1.0 비목표 (스펙 §15 N3)
- lead 외 권한 격상 패턴 — 현재 elevated 도구는 lead 전용, tools.py는 `is_lead` 검증 런타임 강제 없음 (문서 규약) → v1.1에서 강제화 여부 논의
