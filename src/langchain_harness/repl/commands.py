"""Slash-command handlers for the REPL.

Every handler receives the active ``ReplSession`` and ``ReplRenderer`` and
returns a ``CommandResult``. A handler that sets ``result.exit`` asks the
REPL loop to shut down; ``result.switch_team`` asks it to re-bootstrap on a
different team.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..team import mailbox as mailbox_mod
from ..team import registry, tasks
from .session import USER_AGENT_NAME, ReplSession


@dataclass
class CommandResult:
    exit: bool = False
    switch_team: str | None = None
    consumed: bool = True
    error: str | None = None


CommandFn = Callable[["CommandContext"], CommandResult]


@dataclass
class CommandContext:
    session: ReplSession
    renderer: "ReplRenderer"  # forward ref — avoid circular import at type time
    args: list[str] = field(default_factory=list)
    raw: str = ""


# ---------- individual handlers ------------------------------------------


def _cmd_help(ctx: CommandContext) -> CommandResult:
    table_rows = [
        ("/help", "Show this help"),
        ("/exit, /quit", "Shut down the lead and leave the REPL"),
        ("/team", "Show current team info and shared objective"),
        ("/status", "Print member states as a table"),
        ("/teams", "List teams in the workspace"),
        ("/new <name> [objective]", "Create a new team and switch to it"),
        ("/resume <name>", "Switch to an existing team"),
        ("/spawn <name> [role]", "Register a teammate (role defaults to engineer)"),
        ("/inbox", "Show your (user) inbox entries"),
        ("/task [list|create <title>]", "Manage the shared task queue"),
        ("/clear", "Clear the terminal"),
        ("/memory", "Print the shared objective / team header"),
        ("<text>", "Anything else is sent to the lead as a user message"),
    ]
    from rich.table import Table

    t = Table(title="REPL commands", border_style="cyan")
    t.add_column("command", style="bold")
    t.add_column("effect")
    for name, desc in table_rows:
        t.add_row(name, desc)
    ctx.renderer.console.print(t)
    return CommandResult()


def _cmd_exit(ctx: CommandContext) -> CommandResult:
    return CommandResult(exit=True)


def _cmd_team(ctx: CommandContext) -> CommandResult:
    tf = registry.load_team_file(ctx.session.workspace, ctx.session.team_name)
    ctx.renderer.info(
        f"team=[bold]{tf.team_name}[/bold] lead=[green]{tf.lead}[/green] "
        f"version={tf.version} members={len(tf.members)}"
    )
    ctx.renderer.console.print(f"[dim]objective[/dim]: {tf.shared_objective}")
    return CommandResult()


def _cmd_status(ctx: CommandContext) -> CommandResult:
    tf = registry.load_team_file(ctx.session.workspace, ctx.session.team_name)
    ctx.renderer.members_table([m.to_json() for m in tf.members])
    return CommandResult()


def _cmd_teams(ctx: CommandContext) -> CommandResult:
    root = registry.teams_root(ctx.session.workspace)
    if not root.exists():
        ctx.renderer.info("no teams yet")
        return CommandResult()
    names = sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "config.json").exists()
    )
    if not names:
        ctx.renderer.info("no teams yet")
        return CommandResult()
    for n in names:
        marker = " [green](active)[/green]" if n == ctx.session.team_name else ""
        ctx.renderer.console.print(f"  • {n}{marker}")
    return CommandResult()


def _cmd_new(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(error="usage: /new <team_name> [objective]")
    team_name = ctx.args[0]
    objective = " ".join(ctx.args[1:]) or "Assist the user via natural-language conversation."
    cfg = registry.config_path(ctx.session.workspace, team_name)
    if cfg.exists():
        return CommandResult(error=f"team {team_name!r} already exists; use /resume")
    registry.team_create(
        ctx.session.workspace,
        team_name=team_name,
        lead_name="lead",
        shared_objective=objective,
    )
    return CommandResult(switch_team=team_name)


def _cmd_resume(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(error="usage: /resume <team_name>")
    team_name = ctx.args[0]
    cfg = registry.config_path(ctx.session.workspace, team_name)
    if not cfg.exists():
        return CommandResult(error=f"team {team_name!r} not found")
    return CommandResult(switch_team=team_name)


def _cmd_spawn(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(error="usage: /spawn <name> [role]")
    name = ctx.args[0]
    role = ctx.args[1] if len(ctx.args) > 1 else "engineer"
    tf = registry.load_team_file(ctx.session.workspace, ctx.session.team_name)
    if tf.find_member(name) is not None:
        return CommandResult(error=f"agent_name {name!r} already exists")

    # Ask the lead to handle the spawn (it owns spawn_teammate policy).
    body = (
        f"SPAWN_REQUEST: please call spawn_teammate with name={name!r} role={role!r}. "
        "After spawning, confirm to the user via send_message(recipient='user', ...)."
    )
    mailbox_mod.append_entry(
        ctx.session.workspace,
        ctx.session.team_name,
        sender=USER_AGENT_NAME,
        recipient=ctx.session.lead_name,
        body=body,
        kind="plain",
        ttl_seconds=None,
    )
    ctx.renderer.info(f"asked lead to spawn [bold]{name}[/bold] ([dim]{role}[/dim])")
    return CommandResult()


def _cmd_inbox(ctx: CommandContext) -> CommandResult:
    entries = mailbox_mod.read_entries(
        ctx.session.workspace, ctx.session.team_name, USER_AGENT_NAME
    )
    ctx.renderer.inbox_table([e.to_json() for e in entries[-20:]])
    return CommandResult()


def _cmd_task(ctx: CommandContext) -> CommandResult:
    sub = ctx.args[0] if ctx.args else "list"
    if sub == "list":
        items = tasks.list_tasks(ctx.session.workspace, ctx.session.team_name, limit=50)
        ctx.renderer.tasks_table([t.to_json() for t in items])
        return CommandResult()
    if sub == "create":
        if len(ctx.args) < 2:
            return CommandResult(error="usage: /task create <title...>")
        title = " ".join(ctx.args[1:])
        t = tasks.create_task(
            ctx.session.workspace,
            ctx.session.team_name,
            title=title,
            description="",
            created_by=USER_AGENT_NAME,
        )
        ctx.renderer.info(f"created task [dim]{t.task_id[:8]}[/dim] · {t.title}")
        return CommandResult()
    return CommandResult(error=f"unknown /task subcommand: {sub}")


def _cmd_clear(ctx: CommandContext) -> CommandResult:
    ctx.renderer.console.clear()
    return CommandResult()


def _cmd_memory(ctx: CommandContext) -> CommandResult:
    tf = registry.load_team_file(ctx.session.workspace, ctx.session.team_name)
    ctx.renderer.info("shared_objective:")
    ctx.renderer.console.print(f"  {tf.shared_objective}")
    claudemd = Path.cwd() / "CLAUDE.md"
    if claudemd.exists():
        ctx.renderer.info(f"project CLAUDE.md: {claudemd}")
    else:
        ctx.renderer.info("no project CLAUDE.md in cwd")
    return CommandResult()


# ---------- registry + dispatch ------------------------------------------


COMMANDS: dict[str, CommandFn] = {
    "/help": _cmd_help,
    "/?": _cmd_help,
    "/exit": _cmd_exit,
    "/quit": _cmd_exit,
    "/team": _cmd_team,
    "/status": _cmd_status,
    "/teams": _cmd_teams,
    "/new": _cmd_new,
    "/resume": _cmd_resume,
    "/spawn": _cmd_spawn,
    "/inbox": _cmd_inbox,
    "/task": _cmd_task,
    "/clear": _cmd_clear,
    "/memory": _cmd_memory,
}


def dispatch(line: str, session: ReplSession, renderer: "ReplRenderer") -> CommandResult | None:
    """Try to interpret ``line`` as a slash command. Returns None if not a command."""
    if not line.startswith("/"):
        return None
    parts = line.strip().split()
    name = parts[0].lower()
    handler = COMMANDS.get(name)
    if handler is None:
        return CommandResult(error=f"unknown command: {name} (try /help)")
    ctx = CommandContext(
        session=session, renderer=renderer, args=parts[1:], raw=line
    )
    return handler(ctx)


__all__ = ["dispatch", "CommandResult", "CommandContext", "COMMANDS"]
