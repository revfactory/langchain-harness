"""Mailbox JSONL append + read + status updates + audit logging.

Spec §4 append-only rules, §5 O_APPEND strategy, §6 message protocol.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import registry
from .types import MailboxEntry, MessageKind, MessageStatus

# WHY: §4 — payload split threshold. Keeps JSONL lines <= ~PIPE_BUF.
_BODY_REF_THRESHOLD = 4096


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_line(path: Path, line: str) -> None:
    """O_APPEND write of a single newline-terminated line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        payload = line if line.endswith("\n") else line + "\n"
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


def append_log(workspace: Path, team_name: str, event: dict[str, Any]) -> None:
    """Team-wide audit log (logs.jsonl)."""
    event.setdefault("ts", _now_iso())
    _append_line(registry.logs_path(workspace, team_name), json.dumps(event, ensure_ascii=False))


def _resolve_body(
    workspace: Path,
    team_name: str,
    message_id: str,
    body: str,
) -> tuple[str, str | None]:
    """Return (stored_body, body_ref). Large bodies are moved to payloads/."""
    if len(body.encode("utf-8")) <= _BODY_REF_THRESHOLD:
        return body, None
    payload_path = registry.payloads_dir(workspace, team_name) / f"{message_id}.txt"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(body)
    # keep a short preview for at-a-glance auditing
    preview = body[:200]
    return preview, str(payload_path.relative_to(registry.team_dir(workspace, team_name)))


def append_entry(
    workspace: Path,
    team_name: str,
    *,
    sender: str,
    recipient: str,
    body: str,
    kind: MessageKind = "plain",
    reply_to: str | None = None,
    requires_ack: bool = False,
    ttl_seconds: int | None = 60,
) -> MailboxEntry:
    """Append a MailboxEntry to ``mailbox/{recipient}.jsonl`` (or broadcast)."""
    message_id = uuid.uuid4().hex
    stored_body, body_ref = _resolve_body(workspace, team_name, message_id, body)
    entry = MailboxEntry(
        message_id=message_id,
        sender=sender,
        recipient=recipient,
        kind=kind,
        body=stored_body,
        created_at=_now_iso(),
        reply_to=reply_to,
        requires_ack=requires_ack,
        status="unread",
        ttl_seconds=ttl_seconds,
        body_ref=body_ref,
    )
    line = json.dumps(entry.to_json(), ensure_ascii=False)
    if recipient == "*":
        # broadcast: log original + fanout to every existing mailbox.
        _append_line(registry.broadcast_log(workspace, team_name), line)
        mdir = registry.mailbox_dir(workspace, team_name)
        for p in sorted(mdir.glob("*.jsonl")):
            if p.name.startswith("_"):
                continue
            # skip sender's own mailbox — no echo
            if p.stem == sender:
                continue
            _append_line(p, line)
    else:
        registry.validate_name(recipient, "agent_name")
        _append_line(registry.mailbox_file(workspace, team_name, recipient), line)
    append_log(
        workspace,
        team_name,
        {
            "kind": "send",
            "message_id": message_id,
            "sender": sender,
            "recipient": recipient,
            "message_kind": kind,
            "requires_ack": requires_ack,
        },
    )
    return entry


def read_entries(
    workspace: Path,
    team_name: str,
    agent_name: str,
) -> list[MailboxEntry]:
    """Return all parseable entries. Corrupt lines are logged and skipped."""
    path = registry.mailbox_file(workspace, team_name, agent_name)
    if not path.exists():
        return []
    out: list[MailboxEntry] = []
    for idx, raw in enumerate(path.read_text().splitlines()):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
            out.append(MailboxEntry.from_json(data))
        except (json.JSONDecodeError, KeyError) as exc:
            append_log(
                workspace,
                team_name,
                {
                    "kind": "corrupt_line",
                    "recipient": agent_name,
                    "line_index": idx,
                    "error": str(exc),
                },
            )
    return out


def mark_status(
    workspace: Path,
    team_name: str,
    agent_name: str,
    message_ids: list[str],
    new_status: MessageStatus,
) -> int:
    """Rewrite ``mailbox/{agent}.jsonl`` with status transitions applied.

    This is a non-atomic rewrite — acceptable because each mailbox is owned by
    exactly one consumer in normal flow; producers only append. We take an
    exclusive flock on a dedicated lock file to serialize rewrites.
    """
    if not message_ids:
        return 0
    path = registry.mailbox_file(workspace, team_name, agent_name)
    if not path.exists():
        return 0
    lock = registry.locks_dir(workspace, team_name) / f"inbox_{agent_name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch(exist_ok=True)
    import fcntl  # local import: only needed on the slow rewrite path

    updated = 0
    targets = set(message_ids)
    with open(lock, "r+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            entries = read_entries(workspace, team_name, agent_name)
            for e in entries:
                if e.message_id in targets and e.status != new_status:
                    e.status = new_status
                    updated += 1
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w") as f:
                for e in entries:
                    f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
            os.replace(tmp, path)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return updated


def sweep_expired(
    workspace: Path,
    team_name: str,
    agent_name: str,
    now: datetime | None = None,
) -> int:
    """Transition expired entries (requires_ack + ttl exceeded) to ``expired``."""
    entries = read_entries(workspace, team_name, agent_name)
    now = now or datetime.now(timezone.utc)
    expired: list[str] = []
    for e in entries:
        if e.status in {"acked", "expired"}:
            continue
        if not e.requires_ack or e.ttl_seconds is None:
            continue
        try:
            created = datetime.fromisoformat(e.created_at)
        except ValueError:
            continue
        if (now - created).total_seconds() > e.ttl_seconds:
            expired.append(e.message_id)
    if expired:
        mark_status(workspace, team_name, agent_name, expired, "expired")
        for mid in expired:
            append_log(
                workspace,
                team_name,
                {"kind": "ack_timeout", "message_id": mid, "recipient": agent_name},
            )
    return len(expired)


__all__ = [
    "append_entry",
    "read_entries",
    "mark_status",
    "sweep_expired",
    "append_log",
]
