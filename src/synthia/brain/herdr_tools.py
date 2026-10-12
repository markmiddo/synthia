"""In-process MCP server `herdr`: the brain opens, talks to and closes agents, and runs squads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, TypeVar

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from synthia.herdr import HerdrError
from synthia.squads.engine import Engine
from synthia.squads.model import SquadError

T = TypeVar("T")


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


async def _call(fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


def fleet_lines(engine: Engine) -> str:
    """One line per live agent: name, title, repo, state, squad role if any."""
    registry = {m.pane_id: m for m in engine.registry.live()}
    lines: list[str] = []
    for agent in engine.herdr.agent_list():
        pane = str(agent.get("pane_id", ""))
        member = registry.get(pane)
        name = agent.get("name") or agent.get("agent_name") or (member and member.agent_name)
        title = (
            member.title
            if member
            else str(agent.get("terminal_title_stripped") or agent.get("agent") or "agent")
        )
        repo = Path(str(agent.get("cwd") or "")).name or "?"
        state = str(agent.get("agent_status") or "unknown")
        role = f", {member.squad} squad {member.role}" if member and member.squad else ""
        lines.append(f"{name or pane}: {title} in {repo}, {state}{role}")
    return "\n".join(lines) if lines else "No agents are running."


def make_tools(engine: Engine) -> list[SdkMcpTool[Any]]:
    @tool("fleet", "Compact list of every live agent: who, what, where, state.", {})
    async def fleet(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _text(await _call(lambda: fleet_lines(engine)))
        except HerdrError as exc:
            return _text(f"Could not list agents: {exc}", is_error=True)

    @tool(
        "open_agent",
        "Open a plain Claude Code agent in the squads workspace, in the given folder, and give "
        "it a first prompt. Use for a one-off helper. Name: lowercase letters, digits, dashes.",
        {"name": str, "cwd": str, "prompt": str, "model": str},
    )
    async def open_agent(args: dict[str, Any]) -> dict[str, Any]:
        try:
            name = await _call(
                lambda: engine.open_agent(
                    args["name"], args["cwd"], args["prompt"], args.get("model") or None
                )
            )
        except (SquadError, HerdrError) as exc:
            return _text(f"Could not open the agent: {exc}", is_error=True)
        return _text(f"{name} is open and working on it.")

    @tool("prompt_agent", "Send a prompt to a running agent.", {"name": str, "text": str})
    async def prompt_agent(args: dict[str, Any]) -> dict[str, Any]:
        try:
            await _call(lambda: engine.herdr.agent_prompt(args["name"], args["text"]))
        except HerdrError as exc:
            return _text(f"Could not prompt {args['name']}: {exc}", is_error=True)
        return _text(f"Sent to {args['name']}.")

    @tool(
        "read_agent",
        "Read the recent output of an agent. Lines defaults to eighty.",
        {"name": str, "lines": int},
    )
    async def read_agent(args: dict[str, Any]) -> dict[str, Any]:
        try:
            out = await _call(
                lambda: engine.herdr.agent_read(args["name"], int(args.get("lines") or 80))
            )
        except HerdrError as exc:
            return _text(f"Could not read {args['name']}: {exc}", is_error=True)
        return _text(out)

    @tool(
        "close_agent",
        "Close an agent Synthia opened. Refuses any agent that is not hers.",
        {"name": str},
    )
    async def close_agent(args: dict[str, Any]) -> dict[str, Any]:
        try:
            await _call(lambda: engine.close_agent(args["name"]))
        except (SquadError, HerdrError) as exc:
            return _text(f"I won't close that: {exc}", is_error=True)
        return _text(f"{args['name']} closed.")

    @tool(
        "start_squad",
        "Start a squad on a job. Give a one-paragraph brief for its director; the director "
        "hires the specialists. Returns at once; you are told when the work is ready.",
        {"squad": str, "brief": str, "slug": str},
    )
    async def start_squad(args: dict[str, Any]) -> dict[str, Any]:
        try:
            info = await _call(
                lambda: engine.start_job(args["squad"], args["brief"], args.get("slug") or None)
            )
        except (SquadError, HerdrError) as exc:
            return _text(f"Could not start the squad: {exc}", is_error=True)
        return _text(f"Job {info.job} started; {info.agent_name} is briefed.")

    @tool(
        "squad_status",
        "State of squad jobs and who is live in each. Give a job id for one, or none for all.",
        {"job": str},
    )
    async def squad_status(args: dict[str, Any]) -> dict[str, Any]:
        rows = await _call(lambda: engine.status(args.get("job") or None))
        if not rows:
            return _text("No squad jobs.")
        return _text(
            "\n".join(
                f"{r['squad']} {r['job']}: {r['state']}; live {', '.join(r['live']) or 'none'}; "
                f"{r['last']}"
                for r in rows
            )
        )

    @tool("stop_squad", "Stop a squad job: close all its agents.", {"job": str})
    async def stop_squad(args: dict[str, Any]) -> dict[str, Any]:
        try:
            names = await _call(lambda: engine.stop_job(args["job"]))
        except (SquadError, HerdrError) as exc:
            return _text(f"Could not stop it: {exc}", is_error=True)
        return _text("Stopped " + ", ".join(names) + ".")

    return [
        fleet,
        open_agent,
        prompt_agent,
        read_agent,
        close_agent,
        start_squad,
        squad_status,
        stop_squad,
    ]


def build_herdr_server(engine: Engine) -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="herdr", version="1.0.0", tools=make_tools(engine))
