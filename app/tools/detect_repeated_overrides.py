"""반복 관리자 개입 군집 탐지 (§4.4-e, B-6) — PolicyDrafter 개정 모드의 입력 신호.

필터 기준: decided_by='ADMIN' AND active AND (is_override OR decision='reject')
— 관리자가 AI 판단을 뒤집었거나(override) 직접 반려한 판례만이
'현행 회칙과 실운영의 갭' 신호다. AGENT 자체 판례·일반 승인 판례는 제외.

[C10] 목 임베딩은 해시 기반이라 의미 유사도가 없음 — 바이트 동일 요약만
distance 0으로 군집된다. summarize_claim이 날짜를 제외하므로 동일 청구의
반복은 동일 요약이 되고, 목 E2E는 이 성질에 의존한다 (client.py의
_mock_embedding 변경은 상호 리뷰). 의미 유사 군집 검증은 실키 연결 후(B-8).
"""

from typing import Any

from app.db.pool import get_pool

SIMILARITY_THRESHOLD = 0.3  # cosine distance — 이내면 같은 패턴으로 간주


def _group_clusters(rows: list[dict], edges: list[tuple[str, str]], threshold: int) -> list[dict]:
    """유사 쌍(간선)으로 연결 요소를 묶는다 — 순수 함수 (단위 테스트 대상).

    반환은 count 내림차순, 같은 count면 rows(created_at) 순 — 결정적 순서.
    """
    adj: dict[str, set[str]] = {str(r["id"]): set() for r in rows}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    by_id = {str(r["id"]): r for r in rows}

    clusters: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        rid = str(r["id"])
        if rid in seen:
            continue
        comp = [rid]
        seen.add(rid)
        queue = [rid]
        while queue:
            for nxt in adj[queue.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    comp.append(nxt)
                    queue.append(nxt)
        if len(comp) >= threshold:
            comp_rows = [by_id[i] for i in comp]
            clusters.append(
                {
                    "cluster_summary": comp_rows[0]["expense_summary"],
                    "count": len(comp),
                    "precedent_ids": sorted(comp),
                    "decisions": [cr["decision"] for cr in comp_rows],
                }
            )
    clusters.sort(key=lambda c: -c["count"])
    return clusters


async def detect_repeated_overrides(team_id: int, threshold: int = 3) -> list[dict[str, Any]]:
    """관리자 개입 판례를 임베딩 유사도로 군집 — count >= threshold만 반환.

    노드 쿼리와 간선 쿼리를 REPEATABLE READ 트랜잭션으로 묶는다 — 기본
    READ COMMITTED에서 두 쿼리 사이에 판례가 새로 커밋되면 간선이 노드
    쿼리에 없는 id를 참조해 _group_clusters에서 KeyError가 날 수 있다.
    """
    async with get_pool().connection() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        rows = await (
            await conn.execute(
                """SELECT id, expense_summary, decision
               FROM precedents
               WHERE team_id = %s AND decided_by = 'ADMIN' AND active
                 AND (is_override OR decision = 'reject')
                 AND embedding IS NOT NULL
               ORDER BY created_at""",
                (team_id,),
            )
        ).fetchall()
        edge_rows = await (
            await conn.execute(
                """SELECT a.id AS id_a, b.id AS id_b
               FROM precedents a
               JOIN precedents b
                 ON b.team_id = a.team_id AND a.id < b.id
                AND (a.embedding <=> b.embedding) < %s
               WHERE a.team_id = %s
                 AND a.decided_by = 'ADMIN' AND a.active
                 AND (a.is_override OR a.decision = 'reject')
                 AND a.embedding IS NOT NULL
                 AND b.decided_by = 'ADMIN' AND b.active
                 AND (b.is_override OR b.decision = 'reject')
                 AND b.embedding IS NOT NULL""",
                (SIMILARITY_THRESHOLD, team_id),
            )
        ).fetchall()
    edges = [(str(e["id_a"]), str(e["id_b"])) for e in edge_rows]
    return _group_clusters([dict(r) for r in rows], edges, threshold)
