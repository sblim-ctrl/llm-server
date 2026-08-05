"""심사 그래프 E2E 스모크 테스트 — 목 모드 2가지.

    uv run python scripts/smoke_review.py          # 무DB (기본)
    docker compose up -d llm-postgres
    uv run python scripts/smoke_review.py --db     # 실DB

기대 판정과 실제를 대조해 PASS/FAIL을 내고, 하나라도 어긋나면 exit 1로 끝난다.

**무DB 모드** — 회칙·판례 검색을 '결과 없음'으로 대체한다. 두 심사관은 pgvector를
조회하는데 DB가 없으면 예외가 나고, 예외 처리가 이를 verdict="error"로 바꾼다.
그러면 가드레일이 전 시나리오를 escalate로 보내버려 **어떤 시나리오도 자기 로직에
도달하지 못한다**(안전장치는 정상 작동이지만 검증되는 건 아무것도 없다).
검색이 빈 결과를 돌려주면 설계된 정상 경로를 탄다 — rule_auditor의 no_rules,
precedent_auditor의 '유사 판례 없음'. 즉 **회칙 미등록 신규 팀**을 검증하게 된다.

**실DB 모드** — 스텁 없이 실제 풀을 연다. 빈 스키마라 검색 결과는 역시 비지만,
벡터 SQL이 예외 없이 실행되고 team_id·version 스코프가 성립하는지까지 확인된다.
기대 판정은 무DB 모드와 같다.

**이 스크립트로 확인할 수 없는 것**: MOCK_LLM 임베딩은 해시 기반이라 의미적
유사도가 없다. "관련 조항이 상위로 오는지"는 실제 임베딩(OPENAI_API_KEY)이 붙어야
확인된다 — app/tools/search_rules.py 모듈 docstring 참조.

무DB 모드에서 persist_precedent의 "skipped (non-fatal)" 경고는 정상이다 —
판례 저장은 DB가 필요하고, 실패해도 심사 결과를 무효화하지 않도록 설계돼 있다.
"""

import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graphs.review.graph import review_graph  # noqa: E402
from app.schemas.common import ExpenseClaim  # noqa: E402

# (설명, 청구, 영수증 URL, 기대 판정) — 기대값은 회칙 미등록 상태 기준
SCENARIOS = [
    (
        "한도 내 정상 지출",
        ExpenseClaim(
            title="스터디 교재 구입",
            amount=32_000,
            category="도서",
            date="2026-07-07",
            description="알고리즘 스터디 교재 2권",
        ),
        "https://example.com/r1",
        "approve",
    ),
    (
        "auto_approve_limit(5만원) 이상",
        ExpenseClaim(
            title="MT 대관료",
            amount=180_000,
            category="행사",
            date="2026-07-07",
            description="여름 MT 펜션 대관",
        ),
        "https://example.com/r2",
        "escalate",
    ),
    # 잔액(mock 18.2만원) 초과라 reject를 기대했던 건이지만, 금액 가드레일에 먼저
    # 걸려서 reject 경로까지 가지 않는다.
    (
        "고액 지출 — 금액 가드레일 두 규칙 동시 발동",
        ExpenseClaim(
            title="회식비",
            amount=250_000,
            category="식비",
            date="2026-07-07",
            description="종강 회식",
        ),
        "https://example.com/r3",
        "escalate",
    ),
    (
        "영수증 미첨부",
        ExpenseClaim(
            title="비품 구입",
            amount=20_000,
            category="비품",
            date="2026-07-07",
            description="화이트보드 마커",
        ),
        None,
        "escalate",
    ),
]


async def main() -> None:
    for i, (label, claim, receipt_url) in enumerate(SCENARIOS, 1):
        state = await review_graph.ainvoke(
            {
                "job_id": f"smoke-{i}",
                "expense_id": i,
                "team_id": 1,
                "claim": claim,
                "receipt_url": receipt_url,
            }
        )


def stub_rag() -> None:
    """회칙·판례 검색을 '결과 없음'으로 대체 (무DB 모드).

    설정 플래그(MOCK_RAG 같은)로 만들지 않은 이유: rule_auditor의 no_rules 경로는
    verdict="pass"다. 운영에서 플래그 끄는 걸 잊으면 회칙 심사관이 조용히 통과로
    빠진다 — 설계서 §8("어떤 실패도 자동 승인으로 이어지지 않는다")과 정면 충돌이다.
    스크립트 안에 가두면 그 위험이 없다.
    """
    from app.graphs.review.nodes import precedent_auditor, rule_auditor

    async def _no_results(*_args, **_kwargs) -> list[dict]:
        return []

    rule_auditor.search_rules = _no_results
    precedent_auditor.search_precedents = _no_results


async def run_scenarios() -> int:
    """시나리오 전체 실행. 반환: 실패 건수."""
    failed = 0
    for i, (label, claim, receipt_url, expected) in enumerate(SCENARIOS, 1):
        state = await review_graph.ainvoke(
            {
                "job_id": f"smoke-{i}",
                "expense_id": i,
                "team_id": 1,
                "claim": claim,
                "receipt_url": receipt_url,
            }
        )
        verdict = state.get("verdict")
        ok = verdict == expected
        if not ok:
            failed += 1

        gate = state.get("gate_result")
        reasons = state.get("reasons")
        print(f"\n[{i}] {'PASS' if ok else 'FAIL'}  {label}")
        print(f"    verdict={verdict} (기대 {expected}) confidence={state.get('confidence')}")
        if gate:
            print(f"    gate={gate.decision} triggered={gate.triggered_rules}")
        if reasons:
            print(f"    admin 사유: {reasons.admin}")
    return failed


async def main() -> None:
    use_db = "--db" in sys.argv

    if use_db:
        from app.db.pool import apply_schema, close_pool, open_pool

        await open_pool()
        await apply_schema()
        print("모드: 실DB — 벡터 SQL 실행 경로까지 검증")
    else:
        stub_rag()
        print("모드: 무DB — 회칙 미등록 신규 팀 시나리오")

    try:
        failed = await run_scenarios()
    finally:
        if use_db:
            await close_pool()

    total = len(SCENARIOS)
    print(f"\n{'=' * 52}")
    print(f"{total - failed}/{total} PASS")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
