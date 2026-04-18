from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Sequence, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from ..config import MODEL_ID, WORKSPACE_DIR
from ..tools import default_tools
from .analyzer import analyze
from .composer import filter_tools, resolve_roles
from .roles import ROLES
from .schemas import RoleDef, TaskSpec


class MetaState(TypedDict, total=False):
    task: str
    spec: dict[str, Any]
    messages: Annotated[list[AnyMessage], operator.add]
    route: str
    turn: int
    max_turns: int
    last_actor: str


def _supervisor_system(members: Sequence[str], max_turns: int) -> str:
    joined = ", ".join(members)
    return (
        "당신은 Meta-Harness의 Supervisor입니다.\n"
        f"팀원: {joined}\n"
        "대화 이력을 읽고 다음에 행동할 팀원 이름 하나만 출력하세요. "
        "모든 성공 지표가 충족되었거나 synthesizer가 최종 답을 낸 직후에는 "
        "FINISH만 출력하세요.\n"
        f"최대 {max_turns}턴 이내에 FINISH에 도달해야 합니다.\n"
        "출력은 오직 한 단어입니다. 설명·마크업 금지."
    )


def _make_supervisor_node(
    members: Sequence[str], model_id: str
) -> Callable[[MetaState], dict[str, Any]]:
    llm = ChatAnthropic(model=model_id, max_tokens=50)
    valid = {*members, "FINISH"}

    def node(state: MetaState) -> dict[str, Any]:
        turn = state.get("turn", 0)
        max_turns = state.get("max_turns", 20)
        if turn >= max_turns:
            return {"route": "FINISH"}

        sys = SystemMessage(content=_supervisor_system(members, max_turns))
        spec_snippet = json.dumps(
            {k: state["spec"][k] for k in ("domain", "complexity", "success_criteria") if k in state.get("spec", {})},
            ensure_ascii=False,
        )
        ctx = HumanMessage(content=f"TaskSpec: {spec_snippet}\nLast actor: {state.get('last_actor', 'none')}")
        reply = llm.invoke([sys, ctx, *state.get("messages", [])]).content
        token = (reply or "").strip().split()[0] if reply else "FINISH"
        if token not in valid:
            token = "FINISH"
        return {"route": token}

    return node


def _make_role_node(
    role: RoleDef, role_tools: list[BaseTool], model_id: str
) -> Callable[[MetaState], dict[str, Any]]:
    """Single-step role execution: one model call + optional tool invocations."""
    base_model = ChatAnthropic(model=model_id, max_tokens=8192)
    model = base_model.bind_tools(role_tools) if role_tools else base_model
    tool_map = {t.name: t for t in role_tools}

    def node(state: MetaState) -> dict[str, Any]:
        sys = SystemMessage(content=role.system_prompt)
        response: AIMessage = model.invoke([sys, *state.get("messages", [])])
        new_msgs: list[AnyMessage] = [response]
        for call in getattr(response, "tool_calls", None) or []:
            tool = tool_map.get(call["name"])
            if tool is None:
                new_msgs.append(
                    ToolMessage(
                        content=f"ERROR: tool '{call['name']}' not available to {role.name}",
                        tool_call_id=call["id"],
                    )
                )
                continue
            try:
                result = tool.invoke(call["args"])
            except Exception as exc:  # tools may fail; surface to the agent
                result = f"TOOL_ERROR: {exc}"
            new_msgs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        return {
            "messages": new_msgs,
            "turn": state.get("turn", 0) + 1,
            "last_actor": role.name,
        }

    return node


def build_graph(
    spec: TaskSpec,
    tools: list[BaseTool],
    model_id: str = MODEL_ID,
):
    members = resolve_roles(spec)
    builder: StateGraph = StateGraph(MetaState)
    builder.add_node("supervisor", _make_supervisor_node(members, model_id))
    for name in members:
        builder.add_node(name, _make_role_node(ROLES[name], filter_tools(tools, name), model_id))

    builder.add_edge(START, "supervisor")
    route_map: dict[str, str] = {name: name for name in members}
    route_map["FINISH"] = END
    builder.add_conditional_edges("supervisor", lambda s: s.get("route", "FINISH"), route_map)
    for name in members:
        builder.add_edge(name, "supervisor")
    return builder.compile()


@dataclass
class MetaHarness:
    model_id: str = MODEL_ID
    workspace: Path = field(default_factory=lambda: WORKSPACE_DIR)
    tools: list[BaseTool] = field(default_factory=default_tools)
    recursion_multiplier: int = 3

    def run(self, task: str) -> dict[str, Any]:
        spec = analyze(task, model_id=self.model_id)
        graph = build_graph(spec, self.tools, self.model_id)

        (self.workspace / "meta").mkdir(parents=True, exist_ok=True)
        (self.workspace / "runs").mkdir(parents=True, exist_ok=True)

        init: MetaState = {
            "task": task,
            "spec": spec.model_dump(mode="json"),
            "messages": [HumanMessage(content=task)],
            "route": "",
            "turn": 0,
            "max_turns": spec.max_turns,
            "last_actor": "none",
        }
        recursion = spec.max_turns * self.recursion_multiplier
        result = graph.invoke(init, config={"recursion_limit": recursion})

        trace_path = self._write_trace(spec, result)
        return {
            "spec": spec,
            "messages": result.get("messages", []),
            "final": result.get("messages", [])[-1] if result.get("messages") else None,
            "trace_path": trace_path,
        }

    def _write_trace(self, spec: TaskSpec, result: dict[str, Any]) -> Path:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.workspace / "runs" / f"meta_{run_id}.jsonl"
        with path.open("w") as f:
            f.write(
                json.dumps({"kind": "spec", "spec": spec.model_dump(mode="json")}, ensure_ascii=False)
                + "\n"
            )
            for msg in result.get("messages", []):
                f.write(
                    json.dumps(
                        {
                            "kind": "message",
                            "type": msg.__class__.__name__,
                            "content": str(getattr(msg, "content", ""))[:4000],
                            "tool_calls": [
                                {"name": c.get("name"), "args": c.get("args")}
                                for c in (getattr(msg, "tool_calls", None) or [])
                            ],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        return path


def run_meta_harness(task: str, **kwargs: Any) -> dict[str, Any]:
    return MetaHarness(**kwargs).run(task)
