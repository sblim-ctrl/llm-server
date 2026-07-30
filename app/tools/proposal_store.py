"""제안 저장 계층 (§6, C2) — BudgetPlanner·PolicyDrafter 개정 모드와 /v1/proposals API가 공유."""

import json
from typing import Any, Literal

from app.db.pool import get_pool


async def save_proposal(team_id: int, proposal_type: str, payload: dict[str, Any]) -> str:
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """INSERT INTO proposals (team_id, type, payload)
               VALUES (%s, %s, %s)
               RETURNING id""",
                (team_id, proposal_type, json.dumps(payload)),
            )
        ).fetchone()
    return str(row["id"])


async def update_proposal_status(
    proposal_id: str,
    status: str,
    decided_by: str,
) -> Literal["ok", "not_found", "already_decided"]:
    """proposed 상태에서만 결정 가능 — 404(없음)/409(이미 결정됨) 구분을 위한 tri-state."""
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            """UPDATE proposals
               SET status = %s, decided_by = %s, decided_at = now()
               WHERE id = %s AND status = 'proposed'""",
            (status, decided_by, proposal_id),
        )
        if cur.rowcount == 1:
            return "ok"
        row = await (
            await conn.execute(
                "SELECT 1 FROM proposals WHERE id = %s",
                (proposal_id,),
            )
        ).fetchone()
    return "already_decided" if row else "not_found"


async def list_proposals(team_id: int, proposal_type: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM proposals WHERE team_id = %s"
    params: list[Any] = [team_id]
    if proposal_type is not None:
        sql += " AND type = %s"
        params.append(proposal_type)
    sql += " ORDER BY created_at DESC"
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return [dict(r) for r in rows]
