"""In-process MCP tools the concierge uses to run and track background jobs."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from synthia import inbox
from synthia.brain.jobs import JobManager, JobRecord


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


def _line(rec: JobRecord) -> str:
    tail = f": {rec.summary}" if rec.summary else ""
    return f"{rec.name} (id {rec.id}) {rec.status}{tail}"


def make_tools(
    manager: JobManager, on_dispatch: Callable[[str, str], None] | None = None
) -> list[SdkMcpTool[Any]]:
    @tool(
        "dispatch_job",
        "Run a long task in the background as a headless Claude Code worker in the eventflo "
        "folder. Use for anything over about thirty seconds (morning briefing, builds, audits). "
        "The prompt can be a skill like '/morning' or plain instructions. Code-changing jobs go "
        "through /build, which works in its own worktree. Returns immediately; you will be told "
        "when it finishes.",
        {"name": str, "prompt": str},
    )
    async def dispatch_job(args: dict[str, Any]) -> dict[str, Any]:
        rec = await manager.dispatch(args["name"], args["prompt"])
        if on_dispatch is not None:
            on_dispatch(rec.name, rec.prompt)
        return _text(f"{rec.name} dispatched, id {rec.id} starting. I'll report when it finishes.")

    @tool("job_status", "Status and summary of one background job.", {"job_id": str})
    async def job_status(args: dict[str, Any]) -> dict[str, Any]:
        rec = manager.status(args["job_id"])
        if rec is None:
            return _text(f"No job with id {args['job_id']}.", is_error=True)
        return _text(_line(rec))

    @tool("list_jobs", "List background jobs from this session with their status.", {})
    async def list_jobs(args: dict[str, Any]) -> dict[str, Any]:
        jobs = manager.list_jobs()
        if not jobs:
            return _text("No jobs yet.")
        return _text("\n".join(_line(r) for r in jobs))

    @tool("cancel_job", "Cancel a queued or running background job.", {"job_id": str})
    async def cancel_job(args: dict[str, Any]) -> dict[str, Any]:
        if await manager.cancel(args["job_id"]):
            return _text(f"Job {args['job_id']} cancelled.")
        return _text(f"Job {args['job_id']} is not running.", is_error=True)

    @tool(
        "list_inbox",
        "List the newest items in Mark's Inbox (finished squad and job work) with their ids "
        "and states. Use it to answer what is waiting, or to find an id.",
        {},
    )
    async def list_inbox(args: dict[str, Any]) -> dict[str, Any]:
        items = inbox.list_items()[:10]
        if not items:
            return _text("The inbox is empty.")
        return _text("\n".join(f"{i['id']}: {i['title']} ({i['state']})" for i in items))

    @tool(
        "email_inbox_item",
        "Email one inbox item to Mark as a formatted HTML email (summary, drafts, images), "
        "for when he wants to read it on his phone. Pass the item id, or 'latest' for the "
        "newest item. It only ever goes to Mark's own address. Never paste the content into "
        "an email or message yourself.",
        {"id": str},
    )
    async def email_inbox_item(args: dict[str, Any]) -> dict[str, Any]:
        from synthia.brain import inbox_email

        item_id = str(args.get("id") or "latest").strip()
        if item_id == "latest":
            items = inbox.list_items()
            if not items:
                return _text("The inbox is empty.", is_error=True)
            item_id = items[0]["id"]
        try:
            msg = await asyncio.to_thread(inbox_email.send_item, item_id)
        except inbox_email.EmailError as exc:
            return _text(str(exc), is_error=True)
        return _text(msg)

    return [dispatch_job, job_status, list_jobs, cancel_job, list_inbox, email_inbox_item]


def build_jobs_server(
    manager: JobManager, on_dispatch: Callable[[str, str], None] | None = None
) -> McpSdkServerConfig:
    return create_sdk_mcp_server(
        name="jobs", version="1.0.0", tools=make_tools(manager, on_dispatch)
    )
