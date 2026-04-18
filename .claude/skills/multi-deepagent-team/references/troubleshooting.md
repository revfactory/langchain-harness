# Team Runtime Troubleshooting

SKILL.md 본문 §11의 확장본. 관측 → 원인 → 복구의 3단 구조.

## 고아 teammate

### 관측
- `_workspace/teams/{team}/team.json`의 `status == "active"`
- 그러나 lead 프로세스 부재 (PID tracking 파일 또는 session manifest 불일치)
- tasks.jsonl에 새 이벤트 0건이 N분 이상

### 원인 유형
1. lead 프로세스 OOM 또는 수동 kill
2. lead가 예외로 `team_shutdown` 호출 전 crash
3. CI 환경에서 runner가 timeout으로 강제 종료

### 복구
1. 외부 스크립트가 `team.json.status = "orphaned"` 로 마킹 + crashed_at 타임스탬프 기록
2. 모든 teammate에 `system` 메시지 append: `{"event":"shutdown","reason":"orphaned"}`
3. open 상태인 tasks에 `released` 이벤트 append (재사용 대비)
4. 다음 세션에서 동일 팀명 사용 전 수동 아카이브 (`mv teams/{team} teams/_archive/{team}-{ts}`)

### 예방
- lead 프로세스에 `atexit` 훅으로 `team_shutdown` 보증
- heartbeat 파일 `teammates/{lead}/heartbeat` 매 60초 touch, 3회 연속 miss 시 런타임이 자동 orphan 처리

## 메일박스 손상

### 관측
- `read_mailbox` 호출 시 JSON parse error
- mailbox.jsonl 마지막 라인이 `\n` 없이 끝남
- 또는 중간에 잘린 레코드

### 원인
1. 동시 append가 PIPE_BUF를 초과한 body로 interleave
2. disk full로 partial write
3. 외부 편집기로 수동 수정

### 복구
1. 마지막 parse 성공 위치를 projection 고정점으로 기록
2. 손상 라인부터 EOF까지 `mailbox.jsonl.broken-{ts}`로 이동
3. 나머지 prefix만 활용, 손상 구간은 **잃은 메시지**로 간주
4. 팀 broadcast: `{"type":"system","body":{"event":"mailbox_recovered","mate_id":"...","since_id":"<last_ok>"}}`
5. 발신자들에 재전송 요청 메시지 보내거나, 영향이 크면 lead 재계획 유도

### 예방
- 모든 body가 1KB 초과 시 `artifact_ref`로 파일 분리 (body에는 경로만)
- Envelope 크기 상한 2KB 강제 (런타임 검증)

## 태스크 락업

### 관측
- tasks.jsonl projection에 `claimed_at` 후 `completed|failed|released` 없음 상태 지속
- claimer의 mailbox에 해당 task에 대한 메시지 없음 (질문도 progress도)

### 원인
1. claimer가 무한 루프 (LoopDetection 임계 초과 전 보호 실패)
2. claimer가 crash
3. claimer가 동일 task에 대해 다른 파일 작업 중이나 update 호출 누락

### 복구
1. 런타임이 `claimed_at + timeout` 경과 시 `system`으로 claimer에 ping: `{"event":"progress_query"}`
2. 추가 timeout 초과 시 자동 `released` 이벤트 append → 다른 teammate claim 가능
3. 같은 task가 2회 이상 released 되면 lead에 브로드캐스트로 task를 수동 쪼개거나 취소

### 예방
- claimer 프롬프트에 "N분마다 team_task_update로 진행 기록" 명령
- `MailboxDrainMiddleware` (신규 제안)에서 before_model마다 자동 progress emit

## 중복 claim

### 관측
- tasks.jsonl에 동일 task_id에 대해 서로 다른 mate_id의 `claimed` 이벤트 2개 이상

### 원인
- append 동시성 (file system flush 전 두 프로세스가 공통 앞부분을 읽고 각자 append)

### 복구
1. projection에서 `ts` 오름차순으로 승자 결정 (early wins)
2. 패자에게 `system` 메시지: `{"event":"claim_rejected","task_id":"...","winner":"mate_x"}`
3. 패자는 해당 task의 state/* 작업을 폐기하고 다른 task 찾기

### 예방
- OS-level advisory lock(fcntl flock)을 append 주변에 사용 (추후 런타임 개선)
- ULID id에 monotonic 보장 → ts tie-break가 거의 필요 없음

## 팀 shutdown이 drain에 걸려 종료 안 됨

### 관측
- `team_shutdown(drain_timeout_s=60)` 호출 후 60초 경과했으나 프로세스 살아있음
- tasks.jsonl에 open 상태 태스크 잔존

### 원인
1. drain 로직이 "open 0" 대기 → teammate가 끝없이 새 태스크 생성
2. claimer가 complete 직전 무한 루프

### 복구
1. drain_timeout_s 초과 시 런타임이 강제 `cancelled` 이벤트 일괄 append
2. 모든 teammate에 `system:shutdown_now` broadcast
3. 10초 후 프로세스 강제 종료 (exit code 나눠 post-mortem 가능하게)

### 예방
- drain 중에는 `team_task_create` 비활성화
- `MaxIterationsMiddleware` 도입 고려 — teammate가 shutdown_requested 이후 N턴 초과 시 `sys.exit`

## 전체 플레이북 요약

| 증상 | 1차 조치 | 최후의 조치 |
|------|---------|-----------|
| lead 부재 | orphan 마킹 | 팀 디렉토리 archive |
| mailbox parse 실패 | broken rollout | 손상 구간 포기 |
| task claim 후 무응답 | progress_query | 자동 released |
| 중복 claim | ts 승자 결정 | 패자 작업 폐기 |
| shutdown 지연 | 강제 cancelled 일괄 | 프로세스 강제 종료 |
