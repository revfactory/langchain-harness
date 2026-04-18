from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from .agent import HarnessConfig, create
from .config import DEFAULT_SYSTEM_PROMPT, MODEL_ID, WORKSPACE_DIR

load_dotenv()
app = typer.Typer(add_completion=False, help="LangChain deep-agent harness CLI (Claude Opus 4.7).")


@app.command()
def run(
    task: str = typer.Argument(..., help="Task description to hand to the agent."),
    system: str = typer.Option(DEFAULT_SYSTEM_PROMPT, help="System prompt."),
    workspace: Path = typer.Option(WORKSPACE_DIR, help="Workspace directory."),
    thinking: int = typer.Option(8000, help="Extended thinking budget in tokens."),
    model: str = typer.Option(MODEL_ID, help="Anthropic model id."),
    agents_md: Optional[Path] = typer.Option(None, help="Path to AGENTS.md memory file."),
) -> None:
    """Run a single task through the harness."""
    cfg = HarnessConfig(
        model_id=model,
        thinking_budget=thinking,
        system_prompt=system,
        workspace=workspace,
        agents_md=agents_md,
    )
    agent = create(cfg)
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    last = result["messages"][-1]
    typer.echo(getattr(last, "content", last))


@app.command()
def info() -> None:
    """Print the resolved harness configuration."""
    cfg = HarnessConfig()
    typer.echo(f"model_id        : {cfg.model_id}")
    typer.echo(f"thinking_budget : {cfg.thinking_budget}")
    typer.echo(f"workspace       : {cfg.workspace}")
    typer.echo(f"agents_md       : {cfg.agents_md}")


if __name__ == "__main__":
    app()
