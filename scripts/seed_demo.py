"""데모 시드 — '판례 축적 → 에스컬레이션 비율 감소' 그래프 데이터 생성 (§4.4-b 데모 핵심).

시나리오: 회칙이 인덱싱된 팀에서 4주간 지출이 발생한다.
- 처음 보는 유형의 지출은 회칙 해석이 애매해(rule_ambiguous) 에스컬레이션된다
- 관리자가 에스컬레이션 건을 승인하면 판례로 저장된다 (학습 루프)
- 다음 주에 같은 유형의 지출이 오면 관리자 승인 판례가 회칙 공백을 메워 자동 승인된다

실행: uv run python scripts/seed_demo.py  (llm-postgres만 떠 있으면 됨)
출력: 주차별 에스컬레이션 비율 표 + eval/results/demo_weeks.csv (PPT 그래프용)
실행 후 판례가 DB에 남으므로 /ui 대시보드·브리핑 데모에도 그대로 사용 가능 (팀: 9001).
"""

import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, get_pool, open_pool  # noqa: E402
from app.graphs.indexing.graph import indexing_graph  # noqa: E402
from app.graphs.review.graph import review_graph  # noqa: E402
from app.schemas.common import ExpenseClaim  # noqa: E402
from app.tools.precedent_store import save_precedent, summarize_claim  # noqa: E402

TEAM = 9001

# 지출 템플릿 풀 — 주차가 지날수록 이전 주 유형이 반복되고 새 유형이 조금씩 추가된다
CLAIMS = [
    ("정기 회식", 45_000, "식비", "월례 정기 회식 비용"),
    ("스터디룸 대관", 30_000, "대관", "주말 스터디룸 3시간"),
    ("교재 구입", 28_000, "도서", "공용 교재 2권"),
    ("간식 구입", 12_000, "다과", "모임 간식·음료"),
    ("프린트 제본", 9_000, "비품", "발표자료 인쇄·제본"),
    ("온라인 강의", 33_000, "교육", "공용 계정 월 구독"),
    ("교통비 정산", 15_000, "교통", "외부 행사 이동"),
    ("현수막 제작", 40_000, "홍보", "신입 모집 현수막"),
    ("보드게임 카페", 24_000, "여가", "친목 모임"),
    ("공용 장비", 47_000, "용품", "촬영용 삼각대"),
    ("워크숍 참가비", 35_000, "행사", "외부 워크숍 1인"),
    ("다과회 케이크", 18_000, "다과", "분기 다과회"),
]
# 주차별로 사용할 템플릿 인덱스 (이전 주 유형 반복 + 신규 유입)
WEEK_PLAN = {
    1: list(range(0, 6)),  # 전부 처음 보는 유형
    2: list(range(0, 9)),  # 6개 반복 + 3개 신규
    3: list(range(0, 12)),  # 9개 반복 + 3개 신규
    4: list(range(0, 12)),  # 전부 기존 유형
}


# 데모 기준 달 — fixture 지출 이력(`eval/fixtures/mock_backend.json`)과 **같은 달**이어야
# 한다. 주간 브리핑은 판례를 `created_at`의 주로, 주간 지출을 지출 날짜의 주로 묶으므로
# 둘이 다른 달이면 어떤 주를 골라도 한쪽이 0이 된다 — 2026-08-07에 실제로 그랬다
# (판례는 실행 시각인 8월, 지출은 fixture의 6월, 시드 청구는 7월로 셋이 갈려 있었다).
DEMO_MONTH = "2026-06"


def _week_date(week: int) -> str:
    """주차 → 그 주의 대표 날짜 (1주차 07일 … 4주차 28일)."""
    return f"{DEMO_MONTH}-{week * 7:02d}"


async def _restamp_new_precedents(day: str) -> int:
    """이번 실행에서 새로 생긴 판례(=오늘 날짜)를 데모 주차 날짜로 옮긴다.

    `save_precedent(created_at=...)`로 직접 넣는 것과 달리, 심사 그래프가 내부에서
    저장하는 판례는 시각을 지정할 수 없어 사후에 옮긴다. 조건을 `created_at::date =
    CURRENT_DATE`로 좁혀 **이전 주차에 이미 옮겨 둔 행은 건드리지 않는다.**
    """
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            """UPDATE precedents SET created_at = %s::timestamptz
               WHERE team_id = %s AND created_at::date = CURRENT_DATE
               RETURNING id""",
            (day, TEAM),
        )).fetchall()
    return len(rows)


async def submit(week: int, idx: int) -> dict:
    title, amount, category, desc = CLAIMS[idx]
    claim = ExpenseClaim(
        title=title,
        amount=amount,
        category=category,
        date=_week_date(week),
        description=desc,
    )
    state = await review_graph.ainvoke(
        {
            "job_id": f"demo-w{week}-{idx}",
            "expense_id": 900_000 + week * 100 + idx,
            "team_id": TEAM,
            "claim": claim,
            "receipt_url": f"https://example.com/r/demo-{week}-{idx}",
        }
    )
    return {"claim": claim, "verdict": state["verdict"]}


async def main() -> None:
    await open_pool()
    await apply_schema()
    try:
        # 초기화: 데모 팀의 이전 실행 데이터 제거 (재실행 가능)
        async with get_pool().connection() as conn:
            await conn.execute("DELETE FROM precedents WHERE team_id = %s", (TEAM,))
            await conn.execute("DELETE FROM context_chunks WHERE team_id = %s", (TEAM,))

        # 회칙 인덱싱 (v1) — 회칙이 있는 팀이어야 '해석 애매' 시나리오가 성립
        await indexing_graph.ainvoke({"team_id": TEAM, "doc_type": "rule", "version": 1})
        print(f"팀 '{TEAM}' 회칙 인덱싱 완료. 4주 시뮬레이션 시작\n")

        rows = []
        for week, plan in WEEK_PLAN.items():
            results = [await submit(week, i) for i in plan]
            # 심사 그래프의 `persist_precedent`는 **모든 판정**(approve/reject/escalate)을
            # 실행 시각으로 저장한다(실서비스에선 그게 맞다). 시드에서는 그 주에 있었던
            # 일로 보여야 하므로, 이번 주차에 새로 생긴 행만 골라 날짜를 옮긴다 —
            # 브리핑의 자동 승인·반려·에스컬레이션 건수가 전부 이 행들에서 나온다.
            # 여기서 save_precedent를 또 부르면 이중 계상이다(2026-08-09에 실제로 2배였다).
            await _restamp_new_precedents(_week_date(week))
            escalated = [r for r in results if r["verdict"] == "escalate"]
            rate = len(escalated) / len(results)
            rows.append(
                {"week": week, "total": len(results), "escalated": len(escalated), "rate": rate}
            )
            print(f"{week}주차: {len(results)}건 중 에스컬레이션 {len(escalated)}건 ({rate:.0%})")

            # 관리자가 에스컬레이션 건을 전부 승인 → 판례 축적 (학습 루프)
            for r in escalated:
                await save_precedent(
                    team_id=TEAM,
                    summary=summarize_claim(r["claim"]),
                    decision="approve",
                    decided_by="ADMIN",
                    reason="정상적인 모임 활동 지출로 확인 — 승인",
                    created_at=_week_date(week),   # 그 주에 결정된 것으로 기록
                )
        # B-6 시드 확장 (append-only — 기존 시드는 A-4 anomalies 테스트·골든셋이 의존, C10)
        # 동일 청구 반복 → summarize_claim이 날짜를 제외하므로 바이트 동일 요약
        # → 목 해시 임베딩 distance 0 → detect_repeated_overrides 군집 성립 (임계 3 충족)
        override_claim = ExpenseClaim(
            title="정기 회식",
            amount=35_000,
            category="식비",
            date=f"{DEMO_MONTH}-05",
            description="회식비 3.5만원 — 한도 초과분 재량 승인",
        )
        for _ in range(3):
            await save_precedent(
                team_id=TEAM,
                summary=summarize_claim(override_claim),
                decision="approve",
                decided_by="ADMIN",
                is_override=True,
                reason="관리자 재량으로 한도 초과 승인",
                created_at=f"{DEMO_MONTH}-05",
            )
        print("\nB-6 시드: 동일 패턴 ADMIN override 판례 3건 추가 (회칙 개정 제안 데모용)")

        out = ROOT / "eval" / "results" / "demo_weeks.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["week", "total", "escalated", "rate"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n주차별 데이터 저장: {out}")
        print("→ 이 CSV로 PPT '에스컬레이션 비율 감소' 그래프를 그리면 됩니다.")
        print(f"→ /ui 대시보드에서 팀 ID '{TEAM}'으로 브리핑·심사 데모도 가능.")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
