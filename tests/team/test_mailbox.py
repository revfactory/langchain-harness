"""H3: mailbox line atomicity under concurrent senders."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from langchain_harness.team import mailbox, registry


def test_append_entry_basic(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="t1",
        lead_name="lead",
        shared_objective="",
    )
    registry.mailbox_file(workspace, "t1", "alice").touch()
    entry = mailbox.append_entry(
        workspace,
        "t1",
        sender="lead",
        recipient="alice",
        body="hello",
    )
    entries = mailbox.read_entries(workspace, "t1", "alice")
    assert len(entries) == 1
    assert entries[0].message_id == entry.message_id
    assert entries[0].body == "hello"


def test_concurrent_append_line_atomic(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="t2",
        lead_name="lead",
        shared_objective="",
    )
    registry.mailbox_file(workspace, "t2", "bob").touch()
    N_THREADS = 5
    N_MSGS = 200

    def worker(idx: int) -> None:
        for i in range(N_MSGS):
            mailbox.append_entry(
                workspace,
                "t2",
                sender=f"sender_{idx}",
                recipient="bob",
                body=f"msg-{idx}-{i}",
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    path = registry.mailbox_file(workspace, "t2", "bob")
    raw_lines = path.read_text().splitlines()
    assert len(raw_lines) == N_THREADS * N_MSGS
    for line in raw_lines:
        data = json.loads(line)  # every line must be valid json
        assert "message_id" in data
        assert data["recipient"] == "bob"


def test_body_ref_for_large_payload(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="t3",
        lead_name="lead",
        shared_objective="",
    )
    registry.mailbox_file(workspace, "t3", "alice").touch()
    huge = "x" * 8000
    entry = mailbox.append_entry(
        workspace,
        "t3",
        sender="lead",
        recipient="alice",
        body=huge,
    )
    assert entry.body_ref is not None
    assert (registry.payloads_dir(workspace, "t3") / f"{entry.message_id}.txt").exists()


def test_mark_status_transitions_unread_to_read(workspace: Path) -> None:
    registry.team_create(
        workspace,
        team_name="t4",
        lead_name="lead",
        shared_objective="",
    )
    registry.mailbox_file(workspace, "t4", "carol").touch()
    m1 = mailbox.append_entry(
        workspace, "t4", sender="lead", recipient="carol", body="first"
    )
    mailbox.append_entry(workspace, "t4", sender="lead", recipient="carol", body="second")
    updated = mailbox.mark_status(workspace, "t4", "carol", [m1.message_id], "read")
    assert updated == 1
    entries = mailbox.read_entries(workspace, "t4", "carol")
    statuses = [e.status for e in entries]
    assert statuses.count("read") == 1
    assert statuses.count("unread") == 1
