"""Multi-DeepAgent Team runtime smoke example.

Exercises the file-backed primitives (team creation, membership, inbox,
task queue) without requiring an LLM. For a full run with LLM invocations
set ANTHROPIC_API_KEY and plug a real agent factory into
``AgentTeamHarness.spawn``.

Usage:
    uv run python examples/team_hello.py
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_harness.team import registry
from langchain_harness.team.mailbox import append_entry, read_entries
from langchain_harness.team.tasks import create_task, list_tasks
from langchain_harness.team.types import MailboxPolicy, TeamFile, TeamMember


def main() -> None:
    workspace = Path("_workspace")
    team_name = "hello_team"
    now = "2026-04-18T00:00:00+00:00"

    registry.ensure_team_dirs(workspace, team_name)
    team_file = TeamFile(
        team_name=team_name,
        created_at=now,
        lead="alice",
        members=[
            TeamMember(
                agent_name="alice",
                agent_id=f"alice@{team_name}",
                role="lead",
                model_id="claude-opus-4-7",
                tools=["send_message", "spawn_teammate", "team_task_create"],
                state="alive",
                spawned_at=now,
                last_heartbeat=now,
            )
        ],
        shared_objective="Greet the user and list project conventions.",
        mailbox_policy=MailboxPolicy(),
        version=0,
    )
    registry.save_team_file(workspace, team_file, expected_version=None)

    append_entry(
        workspace,
        team_name,
        sender="system",
        recipient="alice",
        body="Welcome to the team runtime.",
        kind="plain",
    )

    task = create_task(
        workspace,
        team_name,
        title="Say hello",
        description="Produce a one-line greeting.",
        created_by="alice",
    )

    inbox = read_entries(workspace, team_name, "alice")
    tasks = list_tasks(workspace, team_name)

    print(json.dumps({
        "team_name": team_name,
        "members": [m.agent_id for m in team_file.members],
        "inbox_count": len(inbox),
        "first_inbox_body": inbox[0].body if inbox else None,
        "tasks": [t.task_id for t in tasks],
        "first_task_title": task.title,
    }, indent=2))


if __name__ == "__main__":
    main()
