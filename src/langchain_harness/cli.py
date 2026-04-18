from __future__ import annotations

import typer
from dotenv import load_dotenv

from .team.cli import team_app

load_dotenv()
app = typer.Typer(
    add_completion=False,
    help="LangChain Multi-DeepAgent Team harness CLI (Claude Opus 4.7).",
)
app.add_typer(team_app, name="team", help="Multi-DeepAgent team runtime.")


if __name__ == "__main__":
    app()
