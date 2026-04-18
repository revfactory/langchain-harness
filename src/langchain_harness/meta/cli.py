from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

from ..config import MODEL_ID, WORKSPACE_DIR
from .analyzer import analyze
from .evolution import analyze_runs
from .memory import MemoryStore
from .orchestrator import MetaHarness

load_dotenv()
meta_app = typer.Typer(
    add_completion=False, help="Meta-harness — LangGraph-routed multi-role team."
)


@meta_app.command("analyze")
def analyze_cmd(task: str, model: str = MODEL_ID) -> None:
    """Print the TaskSpec for a task without executing it."""
    spec = analyze(task, model_id=model)
    typer.echo(spec.model_dump_json(indent=2))


@meta_app.command("run")
def run_cmd(
    task: str,
    model: str = MODEL_ID,
    workspace: Path = WORKSPACE_DIR,
) -> None:
    """Execute a task through the Supervisor-routed multi-role team."""
    mh = MetaHarness(model_id=model, workspace=workspace)
    out = mh.run(task)
    final = out.get("final")
    typer.echo(getattr(final, "content", final) if final else "(no final message)")
    typer.echo(f"\n[trace] {out['trace_path']}")
    typer.echo(f"[roles] {', '.join(out['spec'].required_roles)}")


@meta_app.command("evolve")
def evolve_cmd(
    limit: int = 10,
    workspace: Path = WORKSPACE_DIR,
    model: str = MODEL_ID,
    agents_md: Path | None = None,
) -> None:
    """Read recent traces and produce improvement cards."""
    store = MemoryStore(workspace=workspace, agents_md=agents_md)
    cards = analyze_runs(store, limit=limit, model_id=model)
    if not cards:
        typer.echo("(no cards — insufficient traces or no actionable signal)")
        return
    for i, card in enumerate(cards, 1):
        typer.echo(f"\n--- Card {i} ---")
        typer.echo(card.model_dump_json(indent=2))


if __name__ == "__main__":
    meta_app()
