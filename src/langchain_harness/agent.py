from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from langchain_anthropic import ChatAnthropic

from .config import DEFAULT_SYSTEM_PROMPT, MODEL_ID, THINKING_BUDGET, WORKSPACE_DIR
from .middleware import default_middleware_stack
from .tools import default_tools


@dataclass
class HarnessConfig:
    model_id: str = MODEL_ID
    thinking_budget: int = THINKING_BUDGET
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    workspace: Path = field(default_factory=lambda: WORKSPACE_DIR)
    subagents: Sequence[dict[str, Any]] = field(default_factory=tuple)
    extra_tools: Sequence[Any] = field(default_factory=tuple)
    checklist: Sequence[str] = field(default_factory=tuple)
    agents_md: Path | None = None


def build_model(cfg: HarnessConfig) -> ChatAnthropic:
    kwargs: dict[str, Any] = {
        "model": cfg.model_id,
        "max_tokens": 8192,
    }
    if cfg.thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": cfg.thinking_budget}
    return ChatAnthropic(**kwargs)


def _collect_tools(cfg: HarnessConfig) -> list[Any]:
    tools = list(default_tools())
    tools.extend(cfg.extra_tools)
    return tools


def _collect_middleware(cfg: HarnessConfig) -> list[Any]:
    checklist = list(cfg.checklist) if cfg.checklist else None
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    return default_middleware_stack(
        workspace=cfg.workspace,
        checklist=checklist,
        agents_md=cfg.agents_md,
    )


def create(cfg: HarnessConfig | None = None) -> Any:
    """Factory that builds a deep-agent harness. Deferred imports so that
    missing optional deps surface a clear error only at call time."""
    cfg = cfg or HarnessConfig()
    model = build_model(cfg)
    tools = _collect_tools(cfg)
    middleware = _collect_middleware(cfg)

    try:
        from deepagents import create_deep_agent  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "deepagents package is not installed. Run `uv pip install deepagents` "
            "or `pip install deepagents` before calling create()."
        ) from exc

    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": cfg.system_prompt,
    }
    if cfg.subagents:
        kwargs["subagents"] = list(cfg.subagents)
    # Pass middleware through if the installed deepagents version supports it.
    # Unknown kwargs would fail; we wrap call in try/except and retry without.
    try:
        return create_deep_agent(middleware=middleware, **kwargs)
    except TypeError:
        # Older deepagents versions may not accept middleware= — attach manually.
        agent = create_deep_agent(**kwargs)
        setattr(agent, "_harness_middleware", middleware)
        return agent
