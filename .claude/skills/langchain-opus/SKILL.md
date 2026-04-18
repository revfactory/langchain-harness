---
name: langchain-opus
description: "LangChain + Anthropic Claude Opus 4.7 통합의 핵심 노하우. 모델 ID, ChatAnthropic 파라미터, prompt caching, extended thinking, tool calling, 토큰 최적화 베스트 프랙티스를 제공. Opus 4.7 기반 에이전트 코드를 작성/검토하거나 'langchain-anthropic 설정', 'prompt caching', 'extended thinking', 'tool use' 관련 작업 시 반드시 사용."
---

# LangChain × Claude Opus 4.7 Integration Essentials

## 모델 ID (암기 필수)

| 모델 | ID | 용도 |
|------|-----|------|
| Claude Opus 4.7 | `claude-opus-4-7` | 하네스 기본 — 추론 품질 최우선 |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 비용 민감 보조 에이전트 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 고속 서브태스크 |

하네스 오케스트레이터·플래너는 Opus, 단순 tool executor는 Sonnet/Haiku로 혼합 가능.

## ChatAnthropic 기본 설정

```python
from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(
    model="claude-opus-4-7",
    max_tokens=8192,
    temperature=0,              # 에이전트는 일관성 우선
    thinking={"type": "enabled", "budget_tokens": 8000},
    default_headers={
        "anthropic-beta": "prompt-caching-2024-07-31",
    },
)
```

## Prompt Caching — 비용 50~90% 절감

대형 시스템 프롬프트, 도구 정의, 대용량 참고 문서는 반드시 캐싱한다.

### LangChain에서의 적용

```python
from langchain_core.messages import SystemMessage

system = SystemMessage(
    content=[
        {
            "type": "text",
            "text": LARGE_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
    ]
)
```

### 캐시 전략
1. **고정 영역을 앞에**: system prompt → tool defs → few-shot → 사용자 입력
2. **변동 영역은 뒤에**: 대화 히스토리, 사용자 쿼리는 캐시 대상 뒤
3. **breakpoint 최대 4개**: system, tools, 문서 블록 1, 문서 블록 2

## Extended Thinking

고난이도 태스크에서 품질 상승. 예산을 태스크 단계에 따라 조절한다 (`middleware-patterns`의 ReasoningBudget 참조).

```python
thinking={"type": "enabled", "budget_tokens": 12000}   # plan / verify
thinking={"type": "enabled", "budget_tokens": 4000}    # implementation
```

### 주의
- `thinking` 사용 시 `temperature=1` 고정 (Anthropic 제약). `temperature=0`과 동시 사용 불가 → LangChain이 경고 발생시킬 수 있음. Production에선 `temperature`를 명시하지 않고 thinking만 켜는 것이 안전
- Thinking 토큰은 `max_tokens`에 포함되지 않고 별도 과금

## Tool Calling — @tool 패턴

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str = Field(description="Absolute path to file")
    max_lines: int = Field(default=2000, description="Max lines to read")


@tool(args_schema=ReadFileArgs)
def read_file(path: str, max_lines: int = 2000) -> str:
    """Read a file from disk, returning at most max_lines."""
    with open(path) as f:
        return "\n".join(f.readlines()[:max_lines])


model_with_tools = model.bind_tools([read_file])
```

### Tool 설계 원칙
- **하나의 함수 = 하나의 의도**: `edit_or_create_file` 같은 복합 tool은 모델 혼란 유발
- **docstring이 곧 문서**: LLM은 docstring을 읽는다. 인자와 반환을 명시
- **pydantic 스키마**: 타입 검증으로 silent 실패 방지

## deepagents와의 통합

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model,
    tools=[read_file, write_file, execute_bash],
    subagents=[
        {
            "name": "planner",
            "description": "Break complex tasks into ordered steps.",
            "system_prompt": PLANNER_PROMPT,
            "tools": [read_file],
        }
    ],
    # permissions, memory, middleware 는 실제 deepagents API 시그니처에 따름
)
```

### deepagents API 호환성 노트
공식 문서(`docs.langchain.com/oss/python/deepagents/harness`)는 다음 파라미터를 암시한다:
- `permissions=` — 파일/커맨드 권한 규칙
- `memory=` — 파일 경로 리스트
- `interrupt_on=` — 특정 tool 호출 시 사용자 확인
- `subagents=` — 스페셜 서브에이전트 정의

실제 버전에 따라 시그니처가 변동할 수 있으므로, 설치 후 `help(create_deep_agent)`로 반드시 확인.

## Streaming

```python
async for event in agent.astream_events({"messages": [...]}, version="v2"):
    if event["event"] == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        print(chunk.content, end="", flush=True)
```

## LangSmith Tracing (권장)

```python
import os
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = "langchain-harness"
```

자동으로 모든 chain/agent/tool 호출이 trace된다. `harness-evaluator`가 분석에 사용.

## 비용·지연 튜닝 체크리스트

- [ ] 시스템 프롬프트 > 1024 tokens → 캐시 적용
- [ ] 도구 정의 > 1024 tokens → 캐시 적용
- [ ] 반복 참조 문서 → `cache_control` 블록
- [ ] Extended thinking → 단계별 예산 차등
- [ ] 대량 서브태스크 → Haiku로 다운샤드
- [ ] 스트리밍 적용 → 체감 지연 감소

## 흔한 실수

1. `model="claude-opus"` 처럼 버전 생략 → 400 에러. 반드시 `claude-opus-4-7`
2. Thinking + temperature=0 동시 설정 → 경고 또는 에러
3. `cache_control`을 모든 메시지에 붙임 → 캐시 히트 저하. 고정 prefix만
4. `max_tokens`를 thinking 포함으로 오해 → thinking은 별도. `max_tokens`는 출력 토큰
5. 긴 대화에서 tool result를 messages에 누적만 → 컨텍스트 폭발. 파일로 offload
