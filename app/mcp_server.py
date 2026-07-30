"""FastMCP 서버 — 읽기 툴 4종 이중 노출 (§5.2).

내부: LangGraph 노드가 동일 툴 구현을 프로세스 내에서 직접 호출.
외부(MCP): 운영자·개발자가 MCP Inspector / Claude Desktop에서 같은 툴로 질의
— 디버깅·데모·심사위원 시연용. Streamable HTTP로 llm-api에 /mcp 마운트.

쓰기 툴(approve/reject_expense)은 절대 노출하지 않는다 —
그래프의 가드레일을 우회한 상태 변경 차단 (§5.2).
"""
from mcp.server.fastmcp import FastMCP

from app.tools.backend_client import get_budget_status as _get_budget_status
from app.tools.backend_client import get_expense_history as _get_expense_history
from app.tools.search_precedents import search_precedents as _search_precedents
from app.tools.search_rules import search_rules as _search_rules

mcp = FastMCP(
    "budgetops-llm",
    instructions="BudgetOps LLM 서버의 읽기 전용 툴. 회칙·판례 검색과 예산·지출 조회만 가능하며 상태 변경은 불가능합니다.",
    stateless_http=True,
)
# 마운트 지점(/mcp)이 곧 엔드포인트가 되도록 내부 경로는 루트로
mcp.settings.streamable_http_path = "/"


@mcp.tool()
async def search_rules(team_id: int, query: str, version: int) -> list[dict]:
    """팀 회칙 조항을 유사도 검색한다 (pgvector, 버전 고정). RuleAuditor와 동일 구현."""
    return await _search_rules(team_id, query, version)


@mcp.tool()
async def search_precedents(team_id: int, query: str) -> list[dict]:
    """과거 판정 판례를 유사도 검색한다 (익명화 저장본). PrecedentAuditor와 동일 구현."""
    return await _search_precedents(team_id, query)


@mcp.tool()
async def get_budget_status(team_id: int) -> dict:
    """총예산·승인 지출 합계를 조회한다 — 잔액 = 총예산 − 지출 (백엔드 읽기 API 경유)."""
    return await _get_budget_status(team_id)


@mcp.tool()
async def get_expense_history(team_id: int) -> list[dict]:
    """팀 지출 이력을 조회한다 (백엔드 읽기 API 경유)."""
    return await _get_expense_history(team_id)


# FastAPI가 마운트할 ASGI 앱 + lifespan에서 돌릴 세션 매니저
mcp_app = mcp.streamable_http_app()


def mcp_session_manager():
    """main.py lifespan에서 `async with` 로 감싼다 (Streamable HTTP 세션 관리)."""
    return mcp.session_manager.run()
