"""REPL main loop — prompt_toolkit front end, mailbox-backed conversation."""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console

from ..config import WORKSPACE_DIR
from ..team import registry
from .commands import dispatch
from .renderer import ReplRenderer
from .session import (
    DEFAULT_LEAD_NAME,
    DEFAULT_TEAM_NAME,
    USER_AGENT_NAME,
    ReplSession,
    resolve_team_name,
)

HISTORY_FILENAME = ".repl_history"
STREAM_IDLE_SLEEP = 0.1
TURN_IDLE_GRACE_SEC = 1.2
TURN_MAX_WAIT_SEC = 300.0


def _prompt(team: str) -> HTML:
    return HTML(f"<ansimagenta><b>{team}</b></ansimagenta> <ansicyan>▸</ansicyan> ")


def _spawn_stream_thread(
    session: ReplSession,
    renderer: ReplRenderer,
    stop_event: threading.Event,
    activity: threading.Event,
) -> threading.Thread:
    """Background thread that tails mailbox + logs and renders events.

    ``activity`` is set whenever we render a user-visible reply, letting the
    main loop decide when the turn has quieted down.
    """

    def _loop() -> None:
        while not stop_event.is_set():
            printed = False
            # Mailbox entries addressed to the user = lead's natural-language replies.
            for entry in session.drain_user_inbox():
                sender = entry.get("sender", "?")
                body = entry.get("body", "")
                if sender == USER_AGENT_NAME:
                    # self-echoes can show up if a user tool appended to their own mbox
                    continue
                renderer.lead_reply(body, sender=sender)
                activity.set()
                printed = True
            # Team log events (spawns, sends to other members, errors, ...).
            for event in session.drain_team_logs():
                renderer.log_event(event, lead_name=session.lead_name)
                # Don't set activity for log noise — only lead replies count as "turn done".
            if not printed:
                time.sleep(STREAM_IDLE_SLEEP)

    t = threading.Thread(target=_loop, name="repl-stream", daemon=True)
    t.start()
    return t


def _wait_for_turn(
    session: ReplSession, activity: threading.Event, deadline: float
) -> None:
    """Block until the lead has finished (went idle) and the stream has been
    quiet for ``TURN_IDLE_GRACE_SEC``, or ``deadline`` is reached.
    """
    # Reset at the start of the wait so late-arriving replies reset the idle clock.
    activity.clear()
    last_activity = time.monotonic()
    while time.monotonic() < deadline:
        if activity.is_set():
            activity.clear()
            last_activity = time.monotonic()
        state = session.lead_state()
        quiet_for = time.monotonic() - last_activity
        # Condition: lead has drained its inbox (state in {idle, alive}) AND
        # the stream has been quiet for the grace window.
        if state in {"idle", "stopped"} and quiet_for >= TURN_IDLE_GRACE_SEC:
            return
        time.sleep(STREAM_IDLE_SLEEP)


def run_repl(
    *,
    workspace: Path | None = None,
    team: str | None = None,
    objective: str | None = None,
    console: Console | None = None,
) -> int:
    """Entry point used by ``cli.py`` when no subcommand is given."""
    workspace = Path(workspace) if workspace is not None else WORKSPACE_DIR
    workspace.mkdir(parents=True, exist_ok=True)
    team_name = resolve_team_name(workspace, team)

    renderer = ReplRenderer(console=console)

    if not os.getenv("ANTHROPIC_API_KEY"):
        renderer.warn(
            "ANTHROPIC_API_KEY not set — the lead will fail on its first turn. "
            "Slash commands (/team, /status, ...) still work."
        )

    session = ReplSession(
        workspace=workspace,
        team_name=team_name,
        lead_name=DEFAULT_LEAD_NAME,
        shared_objective=objective
        or "Assist the user via natural-language conversation.",
    )

    try:
        session.start()
    except Exception as exc:  # bootstrap failure is fatal
        renderer.error(f"failed to start team: {exc}")
        return 2

    renderer.banner(
        team_name=session.team_name,
        lead_name=session.lead_name,
        workspace=str(workspace.resolve()),
    )

    history_path = workspace / HISTORY_FILENAME
    pt_session = PromptSession(history=FileHistory(str(history_path)))

    stop_event = threading.Event()
    activity = threading.Event()
    stream_thread = _spawn_stream_thread(session, renderer, stop_event, activity)

    # Graceful Ctrl-C: cancel current input without killing the process.
    def _sigint_handler(signum, frame):  # pragma: no cover - signal plumbing
        renderer.warn("interrupt — type /exit to quit")

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except ValueError:
        # Not the main thread — ignore.
        pass

    exit_code = 0
    try:
        while True:
            try:
                with patch_stdout(raw=True):
                    line = pt_session.prompt(_prompt(session.team_name))
            except EOFError:
                renderer.info("bye")
                break
            except KeyboardInterrupt:
                continue
            if not line.strip():
                continue

            if line.startswith("/"):
                result = dispatch(line, session, renderer)
                if result is None:
                    continue
                if result.error:
                    renderer.error(result.error)
                if result.exit:
                    break
                if result.switch_team:
                    new_team = result.switch_team
                    renderer.info(f"switching to team [bold]{new_team}[/bold]")
                    # Tear down the current harness and restart on the new team.
                    stop_event.set()
                    stream_thread.join(timeout=2.0)
                    session.shutdown()
                    session = ReplSession(
                        workspace=workspace,
                        team_name=new_team,
                        lead_name=DEFAULT_LEAD_NAME,
                    )
                    try:
                        session.start()
                    except Exception as exc:
                        renderer.error(f"failed to switch: {exc}")
                        exit_code = 2
                        break
                    renderer.banner(
                        team_name=session.team_name,
                        lead_name=session.lead_name,
                        workspace=str(workspace.resolve()),
                    )
                    stop_event = threading.Event()
                    activity = threading.Event()
                    stream_thread = _spawn_stream_thread(
                        session, renderer, stop_event, activity
                    )
                continue

            # Natural language → lead
            try:
                session.send_to_lead(line)
            except Exception as exc:
                renderer.error(f"send failed: {exc}")
                continue
            renderer.user_echo(line)
            deadline = time.monotonic() + TURN_MAX_WAIT_SEC
            try:
                _wait_for_turn(session, activity, deadline)
            except KeyboardInterrupt:
                renderer.warn("waiting interrupted — lead may still be working")
    finally:
        stop_event.set()
        stream_thread.join(timeout=2.0)
        try:
            session.shutdown()
        except Exception as exc:
            renderer.warn(f"shutdown error: {exc}")
    return exit_code


__all__ = ["run_repl"]
