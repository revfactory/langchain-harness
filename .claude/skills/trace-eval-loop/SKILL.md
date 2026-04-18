---
name: trace-eval-loop
description: "실행된 에이전트의 trace를 수집·분석하여 실패 모드 분류표, 개선 카드, 회귀 테스트 세트를 생성하는 평가 루프. LangSmith export, JSONL 로그, CLI 출력을 통합. '실패 분석', 'trace 분석', '회귀 테스트', '개선 카드', '에이전트 성능 평가', 'eval 루프' 요청 시 반드시 사용. 단일 실행 로그가 없으면 N=10 이상 권장."
---

# Trace Evaluation Loop — Failure-Mode-Driven Improvement

## 원칙

1. **Trace가 진실이다.** 코드 리뷰로는 실패 모드를 못 찾는다.
2. **개선은 카드 단위**. 한 번에 한 변경, 한 지표, 한 가설.
3. **회귀 세트는 append-only**. 한번 잡은 실패는 다시 재현되지 않아야 한다.

## 입력 소스

| 소스 | 경로 예시 | 파싱 |
|------|----------|------|
| LangSmith export | `_workspace/runs/langsmith_{project}_{date}.jsonl` | JSON per line |
| 로컬 TraceAnalysisMiddleware | `_workspace/runs/{run_id}.jsonl` | JSON per line |
| CLI stdout | `_workspace/runs/cli_{run_id}.log` | 텍스트, ANSI 제거 필요 |

## 실패 모드 분류 (표준 taxonomy)

각 실행을 아래 중 하나 이상으로 라벨링. 다중 라벨 허용.

| 코드 | 이름 | 감지 신호 |
|------|------|----------|
| F1 | Loop | 동일 tool+args 3회 이상 연속 |
| F2 | Premature Completion | checklist 미통과 상태에서 종료 시도 |
| F3 | Context Overflow | 토큰 한도 근접 또는 compaction 트리거 |
| F4 | Tool Misuse | 잘못된 인자 타입, 존재하지 않는 경로 반복 |
| F5 | Prompt Drift | 초기 목표에서 벗어난 태스크 수행 |
| F6 | Silent Success | 완료 보고 했으나 실제 산출물 누락 |
| F7 | API Error Cascade | rate limit / 5xx 에러에서 복구 실패 |
| F8 | Permission Escape Attempt | declared permissions 외 경로 접근 시도 |

## 워크플로우

### Step 1. 수집
```bash
mkdir -p _workspace/runs
# LangSmith 이용 시
langsmith runs list --project $LANGSMITH_PROJECT --limit 100 --format jsonl > _workspace/runs/ls_$(date +%Y%m%dT%H%M%SZ).jsonl
```

### Step 2. 정렬 — 실행 단위 그룹화
각 JSONL 라인의 `run_id` 또는 trace id를 키로 그룹화. 한 실행당 하나의 "run object" 구성:
```
{
  "run_id": "...",
  "task": "...",
  "turns": [...tool calls + model calls...],
  "final_status": "completed | aborted | error",
  "tokens": { "input": N, "output": N, "thinking": N }
}
```

### Step 3. 라벨링
각 run에 대해 위 F1~F8 검사.
- **자동 감지 가능**: F1, F3, F7 (패턴 매칭)
- **모델 판정 필요**: F2, F5, F6 (내용 읽어야 함) — 서브 에이전트로 N개 run을 병렬 분류

### Step 4. 분류표 작성
`_workspace/04_eval_report.md`:
```markdown
# Eval Report — {YYYY-MM-DD}
| run_id | task | F1 | F2 | F3 | F4 | F5 | F6 | F7 | F8 | duration | tokens |
|--------|------|----|----|----|----|----|----|----|----|---------|-------|
| r001 | ... | ✓ | - | - | ✓ | - | - | - | - | 42s | 18K |

## Aggregates
- 총 run: N
- 성공률: M / N (X%)
- 최빈 실패 모드: F1 (K회)
```

### Step 5. 개선 카드 생성
최빈 실패 모드부터 개선 카드 작성. `_workspace/04_improvement_cards.md`:

```markdown
## Card #1 — LoopDetection threshold tightening
- 가설: F1(Loop)의 85%는 edit_threshold=3→2로 감소 가능
- 변경 대상: `src/langchain_harness/middleware.py` LoopDetectionMiddleware
- 변경 내용: 기본 임계 3 → 2, cooldown 5턴 추가
- 예상 지표: F1 비율 12% → < 5%
- 리스크: 정상적인 반복 편집도 차단될 수 있음. verify turn에서는 비활성
- 롤백 조건: F1이 5% 이하지만 태스크 성공률이 3%p 이상 하락 시
```

### Step 6. 회귀 세트 등록
개선 카드를 적용하면, 해당 실패 모드를 재현하는 run을 회귀 세트에 추가. `_workspace/04_regression_set.md`:

```markdown
## Regression Cases (append-only)

### RC-001 — Loop in edit_file repeated (added 2026-04-18)
- Origin: run r017, r023
- Task: "Fix failing test in auth module"
- Expected: F1 label 없음, 태스크 완료
- Command: `uv run python -m langchain_harness.cli run --task-file cases/rc-001.txt`
```

### Step 7. 검증 루프
개선 구현 후:
1. 회귀 세트 전체 재실행
2. 새 trace 수집 → Step 2~4 반복
3. 목표 지표 달성 확인
4. 미달 시 카드 롤백 또는 재설계

## 자동화 스크립트 (제안 번들)

`scripts/classify_traces.py` — JSONL을 읽어 F1~F8 자동 라벨 + 리포트 초안. 작성 시 매번 같은 코드를 반복 생성하면 번들 대상.

## 병렬 분석 패턴 (대량 trace)

10개 이상 run 분석 시 병렬 서브 에이전트:
```
Agent(
  subagent_type: "general-purpose",
  model: "opus",
  prompt: "다음 run 10개의 trace를 읽고 F1~F8 라벨을 JSON으로 반환하라. 각 run에 evidence(구체적 턴 번호) 포함.",
  run_in_background: true
)
```
N/10 개의 서브 에이전트를 단일 메시지에서 병렬 호출, 결과 합산.

## 주의

- **샘플 편향**: 쉬운 태스크만 trace에 많으면 지표 왜곡. 난이도 분포 고정
- **Confounder**: 모델 버전, prompt, 데이터가 동시 변경되면 원인 추적 불가. A/B 격리
- **토큰 예산**: 100 run × avg 20K tokens = 2M tokens. 서브 에이전트 분할 필수
- **PII**: trace에 사용자 데이터가 있을 수 있음. 분석 전 마스킹
