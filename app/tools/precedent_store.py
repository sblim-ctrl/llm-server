"""판례 저장·요약 헬퍼 (REQ-042) — persist_precedent 노드와 /v1/precedents API가 공유.

저장 전 반드시: ① PIIMasker로 실명→역할 치환 ② 임베딩 생성 (이후 유사 검색용).
"""
from app.db.pool import get_pool
from app.llm.client import embed_texts
from app.middleware.pii_masker import mask_names
from app.schemas.common import ExpenseClaim
from app.tools.backend_client import get_team_members
from app.tools.vector_utils import to_vector_literal


def summarize_claim(claim: ExpenseClaim) -> str:
    """판례 요약 포맷 — 저장·검색 양쪽이 동일 포맷을 써야 유사도가 성립한다."""
    return f"[{claim.category}] {claim.title} — {claim.amount:,}원. {claim.description}".strip()


async def masked_claim_summary(team_id: int, claim: ExpenseClaim) -> str:
    """검색 쿼리용 마스킹 요약 — 판례가 마스킹 상태로 저장되므로,
    쿼리도 같은 마스킹을 거쳐야 저장본과 동일 표현 공간에서 유사도가 성립한다."""
    members = await get_team_members(team_id)
    return mask_names(summarize_claim(claim), members)


async def save_precedent(
    team_id: int,
    summary: str,
    decision: str,                  # approve | reject | escalate
    decided_by: str,                # AGENT | ADMIN
    reason: str | None = None,
    is_override: bool = False,
    confidence: float | None = None,
    rule_version: int | None = None,
    model_version: str = "mock",
    prompt_version: str = "review/v1",
    created_at: str | None = None,
) -> str:
    """판례 1건 저장. `created_at`은 **시드 전용**이다.

    심사 경로는 항상 None으로 두어 DB 기본값 `now()`를 쓴다. 데모 시드
    (`scripts/seed_demo.py`)만 값을 준다 — 주간 브리핑이 판례를 `created_at`의 주로
    묶기 때문에, 시드가 전부 실행 시각에 쌓이면 fixture 지출(2026-06)과 시간축이
    어긋나 어떤 주를 골라도 한쪽이 0으로 나온다 (2026-08-07 실측).
    """
    members = await get_team_members(team_id)
    summary = mask_names(summary, members)
    reason = mask_names(reason, members) if reason else None
    embedding = (await embed_texts([summary]))[0]

    async with get_pool().connection() as conn:
        row = await (await conn.execute(
            """INSERT INTO precedents
               (team_id, expense_summary, decision, decided_by, reason, is_override,
                confidence, rule_version, model_version, prompt_version, embedding,
                created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector,
                       COALESCE(%s::timestamptz, now()))
               RETURNING id""",
            (team_id, summary, decision, decided_by, reason, is_override,
             confidence, rule_version, model_version, prompt_version,
             to_vector_literal(embedding), created_at),
        )).fetchone()
    return str(row["id"])
