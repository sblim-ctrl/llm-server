"""골든셋 회귀 평가 CLI (§9.1·9.3의 로컬 버전).

실행: uv run python eval/run_eval.py [golden_path]

평가 로직 자체는 app/eval_support.py에 있다 (대시보드 GET /v1/eval/golden과 공유) —
이 파일은 CLI 출력·exit code 처리만 담당.

목 모드(MOCK_LLM/MOCK_BACKEND)에서 실행 가능. search_rules 등이 DB를 쓰므로
llm-postgres는 떠 있어야 한다 (docker compose up -d llm-postgres).
TODO(4주차): LangSmith Dataset 업로드·Experiment 연동, GitHub Actions CI 게이트로 편입.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.eval_support import VERDICT_LABELS, run_golden_set  # noqa: E402


async def main() -> int:
    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    label = golden_path.name if golden_path else "golden_v1.json"

    await open_pool()
    await apply_schema()
    try:
        summary = await run_golden_set(golden_path)
    finally:
        await close_pool()

    print(f"골든셋 {summary['version']} ({label}) — {summary['total']}건 평가 시작\n")
    for r in summary["results"]:
        mark = "O" if r["correct"] else "X"
        line = (f" [{mark}] {r['id']:28s} 기대={VERDICT_LABELS[r['expected']]:2s} "
                f"실제={VERDICT_LABELS.get(r['actual'], r['actual']):2s}")
        if not r["correct"]:
            line += f"  gate={r['gate']}"
        print(line)

    print(f"\n정확도: {summary['correct']}/{summary['total']} = {summary['accuracy']:.1%} "
          f"(기준 ≥ {summary['accuracy_threshold']:.0%})")
    print(f"오승인(false-approve): {summary['false_approve_count']}건 (기준 = 0건, 하드 게이트)")
    if summary["trajectory_total"]:
        print(f"Trajectory(가드레일 발동 일치): {summary['trajectory_correct']}"
              f"/{summary['trajectory_total']} = {summary['trajectory_accuracy']:.1%}")

    m = summary["metrics"]
    def _pct(v: float | None) -> str:
        return "N/A" if v is None else f"{v:.0%}"
    print(f"\n자동 처리율: {m['automation_rate']:.0%} (승인·반려로 자동 종결)")
    print("판정별 Precision/Recall/F1:")
    for label in ("approve", "reject", "escalate"):
        p = m["per_class"][label]
        print(f"  {VERDICT_LABELS[label]:2s}(n={p['support']:2d}): "
              f"P={_pct(p['precision'])} R={_pct(p['recall'])} F1={_pct(p['f1'])}")
    print(f"  → 에스컬레이션 Recall(놓침 없음) = {_pct(m['escalation_recall'])} "
          "(안전 핵심 지표)")

    # 분류 정확도 — 판정과 독립된 관측 지표. 게이트가 아니다(아래 주석 참조).
    if summary["category_total"]:
        print(f"\n분류 정확도: {summary['category_correct']}/{summary['category_total']} "
              f"= {summary['category_accuracy']:.1%}  (관측 지표 — 게이트 아님)")
        if summary["category_misses"]:
            print("  오분류:")
            for miss in summary["category_misses"]:
                print(f"    {miss['id']:28s} 기대={miss['expected']:8s} 실제={miss['actual']}")
        # 목 모드에서는 classify_category가 실LLM을 안 부르고 키워드 규칙으로 답한다 —
        # 이 숫자는 '키워드 규칙의 정확도'이지 실서비스 분류 품질이 아니다. 실모드
        # 측정(eval/run_eval_real.py) 후에 임계값을 정하는 것이 맞다.
        print("  ※ 목 모드 숫자는 키워드 규칙 정확도다 — 실서비스 품질은 실모드에서만 나온다")

    print(f"\n결과 CSV: {summary['csv_path']}")

    if summary["false_approve_count"]:
        print("\n!! 오승인 발생 — 절대 머지 불가 케이스:")
        for case_id in summary["false_approve_ids"]:
            print(f"   - {case_id}")
        return 1
    if summary["accuracy"] < summary["accuracy_threshold"]:
        print("\n!! 정확도 기준 미달")
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
