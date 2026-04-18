---
name: skill-bundling
description: "deep-agent 런타임에 탑재되는 스킬(SKILL.md + references/ + scripts/)을 작성·리팩터하는 가이드. Progressive disclosure, pushy description, 번들 스크립트 판정, AGENTS.md 설계 포함. '에이전트용 스킬 작성', '스킬 리팩터', 'SKILL.md 설계', 'AGENTS.md 작성', '스킬 트리거 조정' 요청 시 사용."
---

# Skill Bundling for Deep Agents

deep-agent이 런타임에 발견하고 로드하는 스킬. Claude Code의 스킬 규약을 deepagents에 동일하게 적용할 수 있으며, 핵심 원칙은 **3층 점진 공개**다.

## 3층 로딩 모델

| 층 | 로딩 시점 | 크기 목표 |
|----|----------|----------|
| Metadata (name + description) | 항상 | ~100 단어 |
| SKILL.md 본문 | 트리거 시 | ≤ 500줄 |
| references/ scripts/ assets/ | 조건부 | 무제한 |

## 파일 구조

```
skills/{skill-name}/
├── SKILL.md           # 필수
├── references/        # 선택 — 조건부로만 읽히는 상세 문서
│   ├── domain_a.md
│   └── domain_b.md
├── scripts/           # 선택 — 실행 가능한 헬퍼
│   └── helper.py
└── assets/            # 선택 — 템플릿, 이미지 등 산출물 재료
```

## SKILL.md YAML 규약

```yaml
---
name: skill-name                    # kebab-case, 글로벌 유일
description: "..."                  # 트리거의 유일한 신호. Pushy하게.
---
```

## Description 작성

### Why Pushy
Claude는 스킬을 보수적으로 트리거한다. "단순히 설명만 되는" description은 놓친다. 공격적으로 쓰되 false trigger가 나지 않는 경계를 지킨다.

### 좋은 예
```yaml
description: "PDF 파일 읽기, 텍스트/테이블 추출, 병합, 분할, 회전, 워터마크, 암호화/복호화, OCR 등 모든 PDF 작업을 수행. .pdf 파일을 언급하거나 PDF 산출물을 요청하면 반드시 이 스킬을 사용할 것."
```

### 나쁜 예
```yaml
description: "PDF 관련 작업을 수행하는 스킬"   # 모호, 트리거 상황 없음
description: "데이터 처리"                     # 너무 광범위
```

### 체크리스트
- [ ] 이 스킬이 **정확히 무슨 일**을 하는지 동사로 나열
- [ ] 어떤 **입력 키워드/상황**에서 트리거되는지 명시
- [ ] 유사하지만 다른 스킬과의 **경계 조건** 기술
- [ ] 초기 실행 뿐만 아니라 **후속 작업 키워드**(재실행/개선/수정) 포함

## 본문 작성 원칙

### Why > What
금지:
```
ALWAYS use X. NEVER use Y.
```
권장:
```
X를 사용한다. Y는 {특정 상황}에서 {특정 실패}를 일으키기 때문이다.
```
모델이 이유를 알면 엣지 케이스에서 스스로 판단한다.

### 명령형
"할 수 있습니다"보다 "한다/하라". 스킬은 지시서.

### 500줄 상한
SKILL.md가 500줄을 넘는 순간 세부 내용을 references/로 분리. 본문에는 포인터만:
```markdown
## 도메인별 상세
- 금융 메트릭: [references/finance.md](references/finance.md)
- 영업 파이프라인: [references/sales.md](references/sales.md)
```

## scripts/ 번들링 판단

테스트·실사용에서 에이전트가 **같은 헬퍼 코드를 3회 이상 재작성**하면 번들 대상.

| 신호 | 조치 |
|------|------|
| 동일 유틸 함수 반복 생성 | `scripts/` 모듈화 |
| 동일 pip install 반복 실행 | SKILL.md에 의존성 명시 + scripts에 install guard |
| 매번 같은 다단계 절차 | SKILL.md 본문에 표준 절차화 |
| 동일 에러 → 동일 회피 | SKILL.md에 known issue + 해결법 |

번들된 스크립트는 반드시 **실행 테스트** 후 커밋.

## AGENTS.md 설계 (deep-agent 메모리)

deep-agent의 `memory=` 파라미터에 주는 장기 지식 파일. 대표 이름은 `AGENTS.md`.

### 권장 섹션
```markdown
# AGENTS.md — {프로젝트명}

## 프로젝트 개요
- 목적, 아키텍처, 주요 모듈

## 코딩 컨벤션
- 언어, 스타일, 타입 힌트, 테스트

## 도구 사용 규칙
- 어떤 tool을 언제 쓰는지, 무엇을 피할지

## 평가 기준
- 무엇이 완료인가
- 어떤 테스트/검증을 통과해야 하는가

## 알려진 함정
- 과거 실패 사례와 회피 방법

## 외부 리소스
- 자주 참조할 URL, 내부 문서
```

### 관리 원칙
- 200줄 이내 유지. 초과 시 참조 링크로 분산
- `## Revisions` 섹션에 변경 이력 append (날짜 + 이유)
- deep-agent가 직접 수정하지 않는다 (사람 또는 큐레이터 에이전트만)

## 테스트 — Should-trigger / Should-NOT-trigger

각 스킬 작성 직후 쿼리 2세트로 검증:

### Should-trigger (8~10개)
스킬을 트리거해야 하는 다양한 표현:
- 명시적: "PDF 병합해줘"
- 암시적: "이 문서들 하나로 합칠 수 있어?"
- 캐주얼: "downloads의 pdf들 묶어서"

### Should-NOT-trigger (near-miss, 8~10개)
키워드가 비슷하지만 다른 도구가 적합한 경우:
- "PDF **읽기만**" (단순 Read로 처리 가능)
- "**이미지**를 PDF로 변환" (이미지 도구 먼저)
- "PDF를 **웹에 업로드**" (네트워크 도구)

near-miss 통과율이 낮으면 description 경계 조건을 강화.

## 기존 스킬 리팩터 플로우

1. 현재 SKILL.md Read
2. 줄 수 확인. 500 초과 시 references/ 분리 후보 식별
3. description이 should-trigger 놓치는 케이스가 있으면 키워드 추가
4. 스크립트 생성 패턴이 반복되면 scripts/로 번들
5. `## Revisions` append
6. 회귀: 기존 trigger 쿼리가 여전히 통과하는지 확인

## 절대 하지 않는 것

- 스킬 파일에 README.md, CHANGELOG.md, INSTALLATION_GUIDE.md 생성
- description을 수정할 때 기존 트리거 키워드 제거 (확장만 허용)
- 사용자용 튜토리얼 작성 (스킬은 AI를 위한 지시서)
- 이미 모델이 알고 있는 상식 서술 (토큰 낭비)
