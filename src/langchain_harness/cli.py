from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from .config import WORKSPACE_DIR
from .repl.app import run_repl
from .team.cli import team_app

load_dotenv()

app = typer.Typer(
    add_completion=False,
    help="LangChain Multi-DeepAgent Team harness (Claude Opus 4.7).",
    invoke_without_command=True,
)
app.add_typer(team_app, name="team", help="Multi-DeepAgent team runtime.")


@app.callback()
def _default(
    ctx: typer.Context,
    team: Optional[str] = typer.Option(
        None,
        "--team",
        "-t",
        help="Team name to resume or create. Defaults to the last used team or 'default'.",
    ),
    objective: Optional[str] = typer.Option(
        None,
        "--objective",
        "-o",
        help="Shared objective seeded when a new team is created.",
    ),
    workspace: Path = typer.Option(
        WORKSPACE_DIR,
        "--workspace",
        "-w",
        help="Workspace root (teams live under {workspace}/teams/).",
    ),
) -> None:
    """Start the natural-language REPL when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    rc = run_repl(workspace=workspace, team=team, objective=objective)
    raise typer.Exit(code=rc)


@app.command("repl")
def repl_cmd(
    team: Optional[str] = typer.Option(None, "--team", "-t"),
    objective: Optional[str] = typer.Option(None, "--objective", "-o"),
    workspace: Path = typer.Option(WORKSPACE_DIR, "--workspace", "-w"),
) -> None:
    """Explicit REPL launcher (equivalent to running `langchain-harness` with no args)."""
    rc = run_repl(workspace=workspace, team=team, objective=objective)
    raise typer.Exit(code=rc)


if __name__ == "__main__":
    app()
