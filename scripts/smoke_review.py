"""심사 그래프 E2E 스모크 테스트 — DB·OpenAI·백엔드 없이 목 모드로 실행.

실행: uv run python scripts/smoke_review.py
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graphs.review.graph import review_graph  # noqa: E402
from app.schemas.common import ExpenseClaim  # noqa: E402

SCENARIOS = [
    ("한도 내 정상 지출 → approve 기대", ExpenseClaim(
        title="스터디 교재 구입", amount=32_000, category="도서",
        date="2026-07-07", description="알고리즘 스터디 교재 2권"), "https://example.com/r1"),
    ("auto_approve_limit(5만원) 초과 → escalate 기대", ExpenseClaim(
        title="MT 대관료", amount=180_000, category="행사",
        date="2026-07-07", description="여름 MT 펜션 대관"), "https://example.com/r2"),
    ("잔액(mock 18.2만원) 초과 → reject 기대... 는 한도 초과라 escalate", ExpenseClaim(
        title="회식비", amount=250_000, category="식비",
        date="2026-07-07", description="종강 회식"), "https://example.com/r3"),
    ("영수증 미첨부 → escalate 기대", ExpenseClaim(
        title="비품 구입", amount=20_000, category="비품",
        date="2026-07-07", description="화이트보드 마커"), None),
]


async def main() -> None:
    for i, (label, claim, receipt_url) in enumerate(SCENARIOS, 1):
        state = await review_graph.ainvoke({
            "job_id": f"smoke-{i}",
            "expense_id": i,
            "team_id": 1,
            "claim": claim,
            "receipt_url": receipt_url,
        })
        gate = state.get("gate_result")
        reasons = state.get("reasons")
        print(f"\n[{i}] {label}")
        print(f"    verdict={state.get('verdict')} confidence={state.get('confidence')}")
        if gate:
            print(f"    gate={gate.decision} triggered={gate.triggered_rules}")
        if reasons:
            print(f"    admin 사유: {reasons.admin}")


if __name__ == "__main__":
    asyncio.run(main())
