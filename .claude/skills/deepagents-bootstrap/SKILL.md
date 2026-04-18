---
name: deepagents-bootstrap
description: "LangChain deepagents + Anthropic ADK + Claude Opus 4.7 기반 파이썬 프로젝트를 스캐폴딩한다. pyproject.toml, uv 설정, 패키지 구조, .env 템플릿, 최소 실행 가능 에이전트를 생성. 'deepagents 프로젝트', '프로젝트 초기화', '스캐폴드', 'langchain 프로젝트 셋업' 요청 시 사용. 이미 존재하는 프로젝트를 덮어쓰지 않는다."
---

# Deepagents Project Bootstrap

`deepagents` 라이브러리를 사용한 Python 프로젝트의 표준 스캐폴드. 파일 생성 전에 **기존 파일 존재 여부를 반드시 Read로 확인**한다.

## 최소 디렉토리 구조

```
프로젝트/
├── pyproject.toml         # uv-ready, Python >=3.11
├── .env.example           # ANTHROPIC_API_KEY 템플릿
├── .gitignore             # .env, __pycache__, _workspace/runs/ 등
├── src/
│   └── langchain_harness/
│       ├── __init__.py
│       ├── agent.py       # create_deep_agent 팩토리
│       ├── middleware.py  # 커스텀 미들웨어
│       ├── tools.py       # @tool 함수
│       ├── config.py      # 모델 ID, 상수
│       └── cli.py         # 엔트리포인트
├── examples/
│   └── hello.py           # 최소 스모크 예제
└── _workspace/            # 하네스 산출물 보관
```

## pyproject.toml 템플릿

```toml
[project]
name = "langchain-harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "deepagents>=0.1.0",
  "langchain-anthropic>=0.3.0",
  "anthropic>=0.40.0",
  "typer>=0.12.0",
  "python-dotenv>=1.0.0",
  "pydantic>=2.8.0",
]

[project.scripts]
langchain-harness = "langchain_harness.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/langchain_harness"]
```

## 필수 환경변수 (.env.example)

```
ANTHROPIC_API_KEY=sk-ant-...
LANGCHAIN_HARNESS_MODEL=claude-opus-4-7
LANGCHAIN_HARNESS_THINKING_BUDGET=8000
# 선택: LangSmith tracing
# LANGSMITH_API_KEY=...
# LANGSMITH_TRACING=true
# LANGSMITH_PROJECT=langchain-harness
```

## agent.py 뼈대 (반드시 `claude-opus-4-7` 사용)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic

from .config import MODEL_ID, THINKING_BUDGET
from .middleware import default_middleware_stack
from .tools import default_tools


@dataclass
class HarnessConfig:
    model_id: str = MODEL_ID
    thinking_budget: int = THINKING_BUDGET
    system_prompt: str = ""
    subagents: Sequence[dict] = ()


def build_model(cfg: HarnessConfig) -> ChatAnthropic:
    return ChatAnthropic(
        model=cfg.model_id,
        max_tokens=8192,
        thinking={"type": "enabled", "budget_tokens": cfg.thinking_budget},
    )


def create(cfg: HarnessConfig | None = None):
    cfg = cfg or HarnessConfig()
    return create_deep_agent(
        model=build_model(cfg),
        system_prompt=cfg.system_prompt,
        tools=default_tools(),
        subagents=list(cfg.subagents),
        middleware=default_middleware_stack(),
    )
```

## config.py

```python
from __future__ import annotations
import os

MODEL_ID = os.getenv("LANGCHAIN_HARNESS_MODEL", "claude-opus-4-7")
THINKING_BUDGET = int(os.getenv("LANGCHAIN_HARNESS_THINKING_BUDGET", "8000"))
WORKSPACE_DIR = os.getenv("LANGCHAIN_HARNESS_WORKSPACE", "_workspace")
```

## cli.py (typer)

```python
from __future__ import annotations
import typer
from dotenv import load_dotenv

from .agent import HarnessConfig, create

load_dotenv()
app = typer.Typer(add_completion=False)


@app.command()
def run(task: str, system: str = "You are a helpful coding agent.") -> None:
    agent = create(HarnessConfig(system_prompt=system))
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    typer.echo(result["messages"][-1].content)


if __name__ == "__main__":
    app()
```

## .gitignore 최소 항목

```
.env
__pycache__/
*.pyc
.venv/
dist/
build/
_workspace/runs/
*.egg-info/
```

## 작성 원칙 (Why를 따라 판단)

1. **uv 우선**: `uv sync`, `uv run` 워크플로우가 pip보다 10배 빠르고 lock 관리가 자동이다. 팀 재현성의 핵심
2. **src/ layout**: flat layout은 test import/packaging에서 함정이 많다. 표준 src-layout 사용
3. **`from __future__ import annotations`**: 타입 힌트 지연 평가로 circular import 완화 + 성능
4. **환경변수는 config.py에 집중**: 코드 전역에서 `os.getenv` 산발 호출은 테스트 가능성을 파괴
5. **모델 ID는 상수**: `"claude-opus-4-7"` 하드코딩 허용 위치는 `config.py` 한 곳뿐

## 생성 전 체크리스트

- [ ] `pyproject.toml` 이미 존재? → 존재 시 dependencies 섹션에 필요 항목 append만
- [ ] `src/langchain_harness/` 이미 존재? → 존재 시 전체 Read 후 최소 diff 수정만
- [ ] `.env` 파일이 이미 있는지 확인 (절대 덮어쓰지 않음, `.env.example`만 생성)
- [ ] 프로젝트 루트에 git 저장소 있는지 (`git status`). 없으면 그대로 진행, 있으면 `.gitignore` 갱신 필요 확인

## 절대 하지 않는 것

- README.md 자동 생성 (사용자 명시 요청이 없는 한)
- `__init__.py`에 공개 API 과다 export (implicit re-export 하지 않음)
- `.env` 파일 직접 생성 (키가 유출될 위험)
- `requirements.txt` + `pyproject.toml` 이중 관리
