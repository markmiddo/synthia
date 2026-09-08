#!/usr/bin/env python3
"""Throwaway: does claude-agent-sdk authenticate on this box, and with what?

Run on middo247 after `pip install claude-agent-sdk` and `claude login`:
    python scripts/brain_auth_spike.py
"""

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage


async def main() -> None:
    print("ANTHROPIC_API_KEY set:", bool(os.environ.get("ANTHROPIC_API_KEY")))
    options = ClaudeAgentOptions(
        cwd=os.path.expanduser("~/dev/eventflo"),
        setting_sources=["user", "project", "local"],
        max_turns=1,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Reply with one line: which model are you and what is today's date?")
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                print("subtype:", message.subtype)
                print("is_error:", message.is_error)
                print("result:", message.result)
                print("total_cost_usd:", message.total_cost_usd)
                print("model_usage:", message.model_usage)


if __name__ == "__main__":
    asyncio.run(main())
