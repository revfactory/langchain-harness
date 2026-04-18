"""Rich-based rendering for REPL output.

The REPL receives two kinds of events:
- Mailbox entries addressed to the user (lead → user replies).
- Team log events (send, spawn, lifecycle transitions, errors).

We render both on the shared `Console`, keeping a consistent palette so the
user can scan a running session easily.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class ReplRenderer:
    """Thin facade around ``rich.console.Console``."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        # Defense-in-depth: suppress duplicate lifecycle events per agent.
        self._last_lifecycle: dict[str, str] = {}

    # ------------------------------------------------------------------
    # banner / prompts
    # ------------------------------------------------------------------

    def banner(self, *, team_name: str, lead_name: str, workspace: str) -> None:
        self.console.print()
        self.console.print(
            Panel(
                Text.from_markup(
                    f"[bold cyan]langchain-harness[/bold cyan]  "
                    f"team=[magenta]{team_name}[/magenta] "
                    f"lead=[green]{lead_name}[/green]\n"
                    f"workspace=[dim]{workspace}[/dim]\n\n"
                    "Type [bold]/help[/bold] for commands, or just ask in natural language. "
                    "[dim]Ctrl-D or /exit to quit.[/dim]"
                ),
                title="Multi-DeepAgent REPL",
                title_align="left",
                border_style="cyan",
            )
        )

    def info(self, text: str) -> None:
        self.console.print(Text.from_markup(f"[cyan]·[/cyan] {text}"))

    def warn(self, text: str) -> None:
        self.console.print(Text.from_markup(f"[yellow]![/yellow] {text}"))

    def error(self, text: str) -> None:
        self.console.print(Text.from_markup(f"[red]✗[/red] {text}"))

    # ------------------------------------------------------------------
    # conversation
    # ------------------------------------------------------------------

    def lead_reply(self, body: str, *, sender: str = "lead") -> None:
        """Lead's natural-language reply to the user."""
        self.console.print(
            Panel(
                Markdown(body or "(empty)"),
                title=f"[bold green]{sender}[/bold green]",
                title_align="left",
                border_style="green",
            )
        )

    def user_echo(self, body: str) -> None:
        self.console.print(Text.from_markup(f"[bold magenta]you[/bold magenta] · {body}"))

    # ------------------------------------------------------------------
    # log stream
    # ------------------------------------------------------------------

    def log_event(self, event: dict[str, Any], *, lead_name: str) -> None:
        """Render a team log event (skips events already shown via mailbox)."""
        kind = event.get("kind", "?")
        if kind == "send":
            sender = event.get("sender", "?")
            recipient = event.get("recipient", "?")
            # Mailbox renderer handles lead → user separately.
            if sender == lead_name and recipient == "user":
                return
            msg_kind = event.get("message_kind", "plain")
            self.console.print(
                Text.from_markup(
                    f"[dim]↪[/dim] [cyan]{sender}[/cyan] → [cyan]{recipient}[/cyan] "
                    f"[dim]({msg_kind})[/dim]"
                )
            )
        elif kind == "spawn":
            self.console.print(
                Text.from_markup(
                    f"[dim]+[/dim] spawned [bold]{event.get('agent_name', '?')}[/bold] "
                    f"([dim]{event.get('role', '?')}[/dim])"
                )
            )
        elif kind == "spawn_requested":
            self.console.print(
                Text.from_markup(
                    f"[dim]?[/dim] spawn requested: {event.get('agent_name', '?')} "
                    f"([dim]{event.get('role', '?')}[/dim])"
                )
            )
        elif kind in {"alive", "resume", "idle_enter", "stopped"}:
            agent = event.get("agent_name", "?")
            if self._last_lifecycle.get(agent) == kind:
                return
            self._last_lifecycle[agent] = kind
            marker = "–" if kind == "stopped" else "·"
            self.console.print(
                Text.from_markup(f"[dim]{marker}[/dim] {agent} [dim]{kind}[/dim]")
            )
        elif kind == "agent_error":
            self.console.print(
                Panel(
                    Text(event.get("error", ""), style="red"),
                    title=f"agent_error · {event.get('agent_name', '?')}",
                    border_style="red",
                )
            )
        elif kind == "orphan_detected":
            self.console.print(
                Text.from_markup(
                    f"[yellow]⚠[/yellow] orphan: {event.get('agent_name', '?')}"
                )
            )
        elif kind == "flood_block":
            self.console.print(
                Text.from_markup(
                    f"[yellow]⚠[/yellow] inbox flood: {event.get('recipient', '?')} "
                    f"pending={event.get('pending', '?')}"
                )
            )
        else:
            # Quiet for unrecognized events to avoid noise.
            return

    # ------------------------------------------------------------------
    # tables
    # ------------------------------------------------------------------

    def members_table(self, members: list[dict[str, Any]]) -> None:
        table = Table(title="Team members", border_style="cyan")
        table.add_column("name", style="bold")
        table.add_column("role")
        table.add_column("state")
        table.add_column("model")
        table.add_column("last_heartbeat", style="dim")
        for m in members:
            state = m.get("state", "?")
            style = {
                "alive": "green",
                "idle": "yellow",
                "stopped": "dim",
                "orphan": "red",
                "spawning": "cyan",
            }.get(state, "white")
            table.add_row(
                m.get("agent_name", "?"),
                m.get("role", "?"),
                f"[{style}]{state}[/{style}]",
                m.get("model_id", "?"),
                m.get("last_heartbeat", "-"),
            )
        self.console.print(table)

    def tasks_table(self, tasks: list[dict[str, Any]]) -> None:
        if not tasks:
            self.info("no tasks")
            return
        table = Table(title="Team tasks", border_style="cyan")
        table.add_column("id", style="dim")
        table.add_column("title", style="bold")
        table.add_column("status")
        table.add_column("assignee")
        table.add_column("priority")
        for t in tasks:
            table.add_row(
                t.get("task_id", "?")[:8],
                t.get("title", "?"),
                t.get("status", "?"),
                t.get("assignee") or "-",
                t.get("priority", "-"),
            )
        self.console.print(table)

    def inbox_table(self, entries: list[dict[str, Any]]) -> None:
        if not entries:
            self.info("inbox empty")
            return
        table = Table(title="Your inbox", border_style="magenta")
        table.add_column("kind", style="dim")
        table.add_column("from", style="bold")
        table.add_column("status")
        table.add_column("body")
        for e in entries:
            body = e.get("body", "")
            preview = body if len(body) < 80 else body[:77] + "..."
            table.add_row(
                e.get("kind", "?"),
                e.get("sender", "?"),
                e.get("status", "?"),
                preview,
            )
        self.console.print(table)


__all__ = ["ReplRenderer"]
