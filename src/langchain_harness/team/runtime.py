"""AgentTeamHarness — runtime host for a multi-member team.

Spec §10. Supports three isolation modes: thread (default), sequential
(tests / determinism), and process (opt-in; minimal scaffold).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from ..config import WORKSPACE_DIR
from . import mailbox as mailbox_mod
from . import registry
from .context import (
    TeamContext,
    reset_team_context,
    set_current_team_context,
)
from .types import TeamMember, VersionConflictError

# WHY: O7 resolution — 30s grace for shutdown_request.
DEFAULT_SHUTDOWN_GRACE_SEC = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


AgentFactory = Callable[[TeamContext], Any]
"""Callable that returns a LangChain-compatible agent given a TeamContext.

Must expose an ``.invoke(state: dict) -> dict`` method.
"""


@dataclass
class _MemberRuntime:
    member: TeamMember
    agent: Any
    ctx: TeamContext
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class AgentTeamHarness:
    team_name: str
    workspace: Path = field(default_factory=lambda: WORKSPACE_DIR)
    isolation: Literal["thread", "process", "sequential"] = "thread"
    tick_interval_sec: float = 0.5  # O2
    idle_timeout_sec: int = 300
    heartbeat_ttl_sec: int = 120
    shutdown_grace_sec: int = DEFAULT_SHUTDOWN_GRACE_SEC

    _members: dict[str, _MemberRuntime] = field(default_factory=dict, init=False)
    _started: bool = field(default=False, init=False)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        mailbox_mod.append_log(
            self.workspace,
            self.team_name,
            {"kind": "harness_start", "isolation": self.isolation},
        )

    def spawn(
        self,
        member: TeamMember,
        agent_factory: AgentFactory,
        *,
        is_lead: bool | None = None,
    ) -> None:
        """Attach a running agent to a registered team member."""
        if self.isolation == "process":
            raise NotImplementedError(
                "AgentTeamHarness.isolation='process' is scheduled for v1.1. "
                "Use 'thread' or 'sequential' for now."
            )
        tf = registry.load_team_file(self.workspace, self.team_name)
        if tf.find_member(member.agent_name) is None:
            tf.members.append(member)
            registry.save_team_file(self.workspace, tf, expected_version=tf.version)
        lead_flag = tf.lead == member.agent_name if is_lead is None else is_lead
        ctx = TeamContext.build(
            workspace=self.workspace,
            team_name=self.team_name,
            agent_name=member.agent_name,
            role=member.role,
            is_lead=lead_flag,
        )
        agent = agent_factory(ctx)
        rt = _MemberRuntime(member=member, agent=agent, ctx=ctx)
        self._members[member.agent_name] = rt
        # WHY spec §7: spawn_requested / spawn → alive. Record spawn first so
        # the log order matches lifecycle diagram.
        mailbox_mod.append_log(
            self.workspace,
            self.team_name,
            {
                "kind": "spawn",
                "agent_name": member.agent_name,
                "role": member.role,
                "isolation": self.isolation,
            },
        )
        self._transition(member.agent_name, "alive", log_kind="alive")
        if self.isolation == "thread":
            rt.thread = threading.Thread(
                target=self._thread_loop,
                args=(rt,),
                name=f"teammate-{member.agent_name}",
                daemon=True,
            )
            rt.thread.start()

    def tick(self) -> None:
        """Sequential mode: run one round across every member."""
        if self.isolation != "sequential":
            raise RuntimeError("tick() is only valid in isolation='sequential'")
        for rt in list(self._members.values()):
            if rt.stop_event.is_set():
                continue
            self._run_once(rt)

    def shutdown(self, cascade: bool = True) -> None:
        if not self._started:
            return
        for rt in list(self._members.values()):
            rt.stop_event.set()
        if self.isolation == "thread":
            for rt in list(self._members.values()):
                if rt.thread is not None and rt.thread.is_alive():
                    rt.thread.join(timeout=self.shutdown_grace_sec)
        for rt in list(self._members.values()):
            self._transition(rt.member.agent_name, "stopped", log_kind="stopped")
        mailbox_mod.append_log(
            self.workspace,
            self.team_name,
            {"kind": "harness_shutdown", "cascade": cascade},
        )
        self._started = False

    def status(self) -> dict[str, Any]:
        tf = registry.load_team_file(self.workspace, self.team_name)
        return {
            "team_name": tf.team_name,
            "lead": tf.lead,
            "version": tf.version,
            "members": [m.to_json() for m in tf.members],
            "isolation": self.isolation,
            "started": self._started,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _transition(
        self,
        agent_name: str,
        new_state: str,
        *,
        log_kind: str,
    ) -> None:
        try:
            tf = registry.load_team_file(self.workspace, self.team_name)
        except FileNotFoundError:
            return
        m = tf.find_member(agent_name)
        if m is None:
            return
        prior_state = m.state
        m.state = new_state  # type: ignore[assignment]
        m.last_heartbeat = _now_iso()
        try:
            registry.save_team_file(self.workspace, tf, expected_version=tf.version)
        except VersionConflictError:
            # retry once — transitions are idempotent.
            tf = registry.load_team_file(self.workspace, self.team_name)
            m = tf.find_member(agent_name)
            if m is not None:
                prior_state = m.state
                m.state = new_state  # type: ignore[assignment]
                m.last_heartbeat = _now_iso()
                registry.save_team_file(self.workspace, tf, expected_version=tf.version)
        # WHY: only log on actual state change. Heartbeat refresh still happens
        # above on every tick so orphan detection stays accurate, but logging
        # idle_enter every 0.5s tick floods logs.jsonl and REPL rendering.
        if prior_state != new_state:
            mailbox_mod.append_log(
                self.workspace,
                self.team_name,
                {"kind": log_kind, "agent_name": agent_name},
            )

    def _run_once(self, rt: _MemberRuntime) -> None:
        token = set_current_team_context(rt.ctx)
        try:
            unread = [
                e
                for e in mailbox_mod.read_entries(
                    self.workspace, self.team_name, rt.member.agent_name
                )
                if e.status == "unread"
            ]
            if not unread:
                self._transition(rt.member.agent_name, "idle", log_kind="idle_enter")
                return
            self._transition(rt.member.agent_name, "alive", log_kind="resume")
            # Compose prompt from unread entries.
            prompt = "\n".join(f"[{e.kind}] {e.sender}: {e.body}" for e in unread)
            # WHY: thread_id=agent_id lets agents with a LangGraph checkpointer
            # carry conversational state across ticks. Agents without a
            # checkpointer simply ignore the config.
            invoke_config = {"configurable": {"thread_id": rt.ctx.agent_id}}
            try:
                rt.agent.invoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config=invoke_config,
                )
            except Exception as exc:  # WHY: surface loudly, but keep loop running.
                mailbox_mod.append_log(
                    self.workspace,
                    self.team_name,
                    {
                        "kind": "agent_error",
                        "agent_name": rt.member.agent_name,
                        "error": str(exc),
                    },
                )
            mailbox_mod.mark_status(
                self.workspace,
                self.team_name,
                rt.member.agent_name,
                [e.message_id for e in unread],
                "read",
            )
        finally:
            reset_team_context(token)

    def _thread_loop(self, rt: _MemberRuntime) -> None:
        while not rt.stop_event.is_set():
            self._run_once(rt)
            time.sleep(self.tick_interval_sec)
        self._transition(rt.member.agent_name, "stopped", log_kind="stopped")

    # ------------------------------------------------------------------
    # convenience helpers for the CLI
    # ------------------------------------------------------------------

    def stale_sweep(self) -> list[str]:
        """Return agent_names newly flagged orphan (heartbeat > TTL)."""
        now = datetime.now(timezone.utc)
        tf = registry.load_team_file(self.workspace, self.team_name)
        flagged: list[str] = []
        for m in tf.members:
            if m.state in {"stopped", "orphan"}:
                continue
            try:
                hb = datetime.fromisoformat(m.last_heartbeat)
            except ValueError:
                continue
            if (now - hb).total_seconds() > self.heartbeat_ttl_sec:
                m.state = "orphan"  # type: ignore[assignment]
                flagged.append(m.agent_name)
                mailbox_mod.append_log(
                    self.workspace,
                    self.team_name,
                    {"kind": "orphan_detected", "agent_name": m.agent_name},
                )
        if flagged:
            try:
                registry.save_team_file(self.workspace, tf, expected_version=tf.version)
            except VersionConflictError:
                pass
        return flagged


__all__ = ["AgentTeamHarness", "AgentFactory", "DEFAULT_SHUTDOWN_GRACE_SEC"]
