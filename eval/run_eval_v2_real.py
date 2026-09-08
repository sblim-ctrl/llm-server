"""골든셋 v2(유형별) 실모드 평가 하니스 — eval/run_eval_real.py의 8파일·유형별 집계 버전.

eval/run_eval_real.py와 다른 점:
- golden_v2/*.json 8개 파일을 전부 합쳐 실행하고 유형별(§Phase 4)로 집계한다.
- circumvention 유형 케이스의 "seed_precedents" 필드를 실행 직전 app.eval_writers.
  _seed_briefing_precedents 패턴으로 심는다(케이스마다 조직 1개씩 전용이라 동시 실행에도
  판례 시딩이 서로 충돌하지 않는다 — scripts/golden_v2/gen_circumvention.py 참조).
- rule_conflict 유형의 회칙 충돌 특별 조항은 eval/fixtures/mock_backend.json의
  "policy_documents"[team_id] 오버라이드로 이미 실인덱싱 단계(아래 for문)에서 자동
  반영된다(app/tools/backend_client.py get_policy_document() 패치 참조) — 이 파일에서
  추가로 할 일은 없다.
- 동시성 세마포어(기본 4)로 실행 — 429 백오프는 app.llm.client의 재시도에 위임한다
  (이 하니스에서 별도 백오프를 구현하지 않음 — 재시도 로직 소유가 app.llm.client에 있어
  하니스가 중복 구현하면 정책이 두 벌로 갈릴 위험이 있다).

실행:
    MOCK_LLM=false uv run python eval/run_eval_v2_real.py            # 전체 799건
    MOCK_LLM=false uv run python eval/run_eval_v2_real.py --sample 5 # 스모크(비용·시간 실측)

게이트: 오승인 1건이라도 있으면 exit 1(목 모드와 동일 하드 기준). 정확도는 참고 지표.
"""

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402
from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.eval_metrics import category_metrics, verdict_metrics  # noqa: E402
from app.eval_support import gate_rules_from_state  # noqa: E402
from eval.run_eval_real import GOLDEN_TEAM_ID_RANGE, clean_golden_teams, receipt_text_for  # noqa: E402,F401

GOLDEN_V2_DIR = ROOT / "eval" / "golden" / "golden_v2"
RESULTS_DIR = ROOT / "eval" / "results"
ACCURACY_TARGET = 0.90
CONCURRENCY = 4


def load_all_cases(sample: int | None) -> list[dict]:
    cases: list[dict] = []
    for path in sorted(GOLDEN_V2_DIR.glob("*.json")):
        cases.extend(json.loads(path.read_text(encoding="utf-8"))["cases"])
    if sample is not None:
        cases = cases[:sample]
    return cases


async def _run_one(case: dict, sem: asyncio.Semaphore) -> dict:
    from app.eval_writers import _seed_briefing_precedents
    from app.graphs.review.graph import review_graph
    from app.schemas.analyze import AnalyzeRequest

    async with sem:
        req = AnalyzeRequest.model_validate(case["input"])
        if case.get("seed_precedents"):
            await _seed_briefing_precedents(req.organization_id, case["seed_precedents"])

        final = await review_graph.ainvoke(
            {
                "job_id": f"eval-v2-real-{case['id']}",
                "external_job_id": req.job_id,
                "expense_id": req.expense_id,
                "team_id": req.organization_id,
                "receipt_text": receipt_text_for(case["input"]),
            }
        )
        actual = final.get("verdict") or "escalate"
        expected = case["expected_verdict"]
        cost = sum(m.cost_usd for m in (final.get("llm_meta") or {}).values())
        claim = final.get("claim")
        return {
            "id": case["id"],
            "type": case.get("type", "unknown"),
            "expected": expected,
            "actual": actual,
            "correct": actual == expected,
            "false_approve": bool(case.get("must_not_approve")) and actual == "approve",
            "gate": "|".join(gate_rules_from_state(final)),
            "cost_usd": cost,
            "expected_category": case.get("expected_category") or "",
            "actual_category": (claim.category if claim else "") or "",
        }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=None, help="처음 N건만 실행(스모크용)")
    args = parser.parse_args()

    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드가 아닙니다 — MOCK_LLM=false 환경변수와 OPENAI_API_KEY가 필요합니다.")
        return 2

    cases = load_all_cases(args.sample)
    if not cases:
        print(f"golden_v2 케이스가 없습니다: {GOLDEN_V2_DIR}")
        return 2

    await open_pool()
    started = time.time()
    try:
        from app.graphs.indexing.graph import indexing_graph

        await apply_schema()
        teams = sorted({c["input"]["organizationId"] for c in cases})
        await clean_golden_teams()
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule"})
        print(
            f"골든 v2 팀 {len(teams)}개 회칙 실인덱싱 완료 — {len(cases)}건 실행 시작"
            f" (동시성 {CONCURRENCY})\n"
        )

        sem = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(*(_run_one(c, sem) for c in cases))

        n = len(results)
        correct = sum(r["correct"] for r in results)
        false_appr = [r["id"] for r in results if r["false_approve"]]
        cost_total = sum(r["cost_usd"] for r in results)

        by_type: dict[str, list[dict]] = {}
        for r in results:
            by_type.setdefault(r["type"], []).append(r)

        print(
            f"{'유형':20s} {'n':>4s} {'정확도':>8s} {'오승인':>6s} {'에스컬 R':>9s} {'분류 정확도':>10s}"
        )
        for type_key in sorted(by_type):
            rows = by_type[type_key]
            t_correct = sum(r["correct"] for r in rows)
            t_fa = sum(r["false_approve"] for r in rows)
            vm = verdict_metrics([{"expected": r["expected"], "actual": r["actual"]} for r in rows])
            cat = category_metrics(
                [
                    {
                        "id": r["id"],
                        "expected_category": r["expected_category"],
                        "category_ok": (r["actual_category"] == r["expected_category"])
                        if r["expected_category"]
                        else None,
                    }
                    for r in rows
                ]
            )
            esc_r = vm["escalation_recall"]
            esc_r_s = f"{esc_r:.0%}" if esc_r is not None else "N/A"
            cat_acc = cat["category_accuracy"]
            cat_acc_s = f"{cat_acc:.1%}" if cat_acc is not None else "N/A"
            print(
                f"{type_key:20s} {len(rows):4d} {t_correct / len(rows):7.1%} "
                f"{t_fa:6d} {esc_r_s:>9s} {cat_acc_s:>10s}"
            )

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"golden_v2_realmode_{date.today().isoformat()}.csv"
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "id",
                    "type",
                    "expected",
                    "actual",
                    "correct",
                    "false_approve",
                    "gate",
                    "cost_usd",
                    "expected_category",
                    "actual_category",
                ]
            )
            for r in results:
                w.writerow(
                    [
                        r["id"],
                        r["type"],
                        r["expected"],
                        r["actual"],
                        r["correct"],
                        r["false_approve"],
                        r["gate"],
                        f"{r['cost_usd']:.5f}",
                        r["expected_category"],
                        r["actual_category"],
                    ]
                )

        acc = correct / n if n else 0.0
        elapsed = time.time() - started
        print(f"\n전체 정확도: {correct}/{n} = {acc:.1%} (목표 ≥ {ACCURACY_TARGET:.0%})")
        print(f"전체 오승인: {len(false_appr)}건 {false_appr[:10] if false_appr else ''}")
        print(f"총 비용 ${cost_total:.4f} (건당 평균 ${cost_total / n:.4f}) · 소요 {elapsed:.0f}s")
        print(f"결과 CSV: {out}")

        if false_appr:
            print("\n!! 오승인 발생")
            return 1
        return 0
    finally:
        try:
            await clean_golden_teams()
            print("골든 팀 데이터 사후 정리 완료")
        except Exception:
            import logging

            logging.exception("골든 팀 데이터 사후 정리 실패 — 수동 정리 필요")
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
