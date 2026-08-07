"""MCP 서버 스모크 — Streamable HTTP 클라이언트로 접속해 툴 목록·호출 확인.

실행: uv run python scripts/smoke_mcp.py  (llm-api가 떠 있어야 함)
"""

import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from app.config import get_settings  # noqa: E402

URL = "http://localhost:8000/mcp"
# /mcp도 서비스 토큰이 필요하다(AuthMiddleware) — MCP Inspector·Claude Desktop도 동일.
HEADERS = {"Authorization": f"Bearer {get_settings().service_token}"}


async def main() -> None:
    async with streamablehttp_client(URL, headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("툴 목록:", [t.name for t in tools.tools])

            result = await session.call_tool(
                "search_rules", {"team_id": 9001, "query": "회식비 한도"}
            )
            print("\nsearch_rules(9001, '회식비 한도') 결과:")
            for block in result.content[:2]:
                print(" ", getattr(block, "text", block)[:120])

            result2 = await session.call_tool("get_budget_status", {"team_id": 9001})
            print("\nget_budget_status:", getattr(result2.content[0], "text", "")[:100])


if __name__ == "__main__":
    asyncio.run(main())
