"""Verify the MCP server module imports and registers all tools correctly,
without actually starting the stdio server loop."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.mcp_server import mcp


async def main() -> None:
    tools = await mcp.list_tools()
    print(f"registered {len(tools)} tools:")
    for t in tools:
        print(f"  - {t.name}")
    assert len(tools) >= 30, f"expected >=30 tools, got {len(tools)}"
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
