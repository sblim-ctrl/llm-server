"""골든셋 회귀 평가 러너 (§9.1·9.3의 로컬 버전).

실행: uv run python eval/run_eval.py [golden_path]

- 골든셋 전 케이스를 심사 그래프에 돌려 verdict를 골든 라벨과 대조
- 메트릭: verdict 정확도, 오승인율(false-approve)
- 오승인(must_not_approve 케이스를 approve) > 0 이면 exit 1 — 하드 게이트 (§9.1)
- 정확도 < 90% 여도 exit 1

목 모드(MOCK_LLM/MOCK_BACKEND)에서 실행 가능. search_rules 등이 DB를 쓰므로
llm-postgres는 떠 있어야 한다 (docker compose up -d llm-postgres).
TODO(4주차): LangSmith Dataset 업로드·Experiment 연동, GitHub Actions CI 게이트로 편입.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.graphs.review.graph import review_graph  # noqa: E402
from app.schemas.analyze import AnalyzeRequest  # noqa: E402

ACCURACY_THRESHOLD = 0.90

VERDICT_ICONS = {"approve": "승인", "reject": "반려", "escalate": "보류"}


async def run_case(case: dict) -> dict:
    req = AnalyzeRequest.model_validate(case["input"])
    final_state = await review_graph.ainvoke({
        "job_id": f"eval-{case['id']}",
        "expense_id": req.expense_id,
        "team_id": req.team_id,
        "claim": req.claim,
        "receipt_url": req.receipt_signed_url,
    })
    actual = final_state.get("verdict") or "escalate"
    expected = case["expected_verdict"]
    return {
        "id": case["id"],
        "expected": expected,
        "actual": actual,
        "correct": actual == expected,
        "false_approve": bool(case.get("must_not_approve")) and actual == "approve",
        "gate": (final_state.get("gate_result").triggered_rules
                 if final_state.get("gate_result") else []),
    }


async def main() -> int:
    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval/golden/golden_v1.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]
    print(f"골든셋 {golden['version']} — {len(cases)}건 평가 시작\n")

    await open_pool()
    await apply_schema()
    try:
        results = [await run_case(c) for c in cases]
    finally:
        await close_pool()

    correct = sum(r["correct"] for r in results)
    false_approves = [r for r in results if r["false_approve"]]
    accuracy = correct / len(results)

    for r in results:
        mark = "O" if r["correct"] else "X"
        line = (f" [{mark}] {r['id']:28s} 기대={VERDICT_ICONS[r['expected']]:2s} "
                f"실제={VERDICT_ICONS.get(r['actual'], r['actual']):2s}")
        if not r["correct"]:
            line += f"  gate={r['gate']}"
        print(line)

    print(f"\n정확도: {correct}/{len(results)} = {accuracy:.1%} (기준 ≥ {ACCURACY_THRESHOLD:.0%})")
    print(f"오승인(false-approve): {len(false_approves)}건 (기준 = 0건, 하드 게이트)")

    if false_approves:
        print("\n!! 오승인 발생 — 절대 머지 불가 케이스:")
        for r in false_approves:
            print(f"   - {r['id']}")
        return 1
    if accuracy < ACCURACY_THRESHOLD:
        print("\n!! 정확도 기준 미달")
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
