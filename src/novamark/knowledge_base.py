"""MCP knowledge base: what the firm wrote about this company before.

A failure is a Gap, not an exception: the run continues and the memo says so.
"""
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import model
from .state import Gap, MemoState


async def history(ticker: str) -> list[dict]:
    """Read `research://memos/{ticker}/history` over stdio. Raises on transport failure."""
    server = StdioServerParameters(command=model.KB_COMMAND[0], args=model.KB_COMMAND[1:])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(f"research://memos/{ticker}/history")
            return json.loads(result.contents[0].text)


async def prior_research(state: MemoState, deps) -> MemoState:
    """Prior memos, or a gap. Never raises, so the pipe cannot die here.

    Runs beside `data_collector.collect`, so it leaves `status` alone; the merge takes the
    collector's.
    """
    try:
        return {**state, "prior_memos": await deps["kb"](state["request"]["ticker"])}
    except Exception as e:
        gap = Gap(source="knowledge_base", reason=str(e) or type(e).__name__)
        return {**state, "gaps": [*state["gaps"], gap]}
