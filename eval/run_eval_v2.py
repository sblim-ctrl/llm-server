"""골든셋 v2(유형별) 목 모드 평가 CLI — eval/run_eval.py의 v2 버전.

실행: uv run python eval/run_eval_v2.py
CI에는 편입하지 않는다(v1 golden_v1.json만 머지 게이트 — CLAUDE.md 정의 불변).
평가 로직 자체는 app/eval_support.run_typed_golden_set이 담당(대시보드 없이 CLI 전용).
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
from app.eval_support import run_typed_golden_set  # noqa: E402

GOLDEN_V2_DIR = ROOT / "eval" / "golden" / "golden_v2"


async def main() -> int:
    paths = sorted(GOLDEN_V2_DIR.glob("*.json"))
    if not paths:
        print(f"golden_v2 파일이 없습니다: {GOLDEN_V2_DIR}")
        return 2

    await open_pool()
    await apply_schema()
    try:
        summary = await run_typed_golden_set(paths)
    finally:
        await close_pool()

    print(f"골든셋 v2 — {len(paths)}개 유형 파일, {summary['total']}건 평가 (목 모드)\n")
    print(
        f"{'유형':20s} {'n':>4s} {'정확도':>8s} {'오승인':>6s} {'에스컬 R':>9s} {'분류 정확도':>10s}"
    )
    for type_key, t in summary["by_type"].items():
        cat_acc = f"{t['category_accuracy']:.1%}" if t["category_accuracy"] is not None else "N/A"
        esc_r = f"{t['escalation_recall']:.0%}" if t["escalation_recall"] is not None else "N/A"
        print(
            f"{type_key:20s} {t['n']:4d} {t['accuracy']:7.1%} "
            f"{t['false_approve_count']:6d} {esc_r:>9s} {cat_acc:>10s}"
        )

    print(f"\n전체 정확도: {summary['correct']}/{summary['total']} = {summary['accuracy']:.1%}")
    print(f"전체 오승인: {summary['false_approve_count']}건")
    print(f"결과 CSV: {summary['csv_path']}")

    if summary["false_approve_count"]:
        print("\n!! 오승인 발생:")
        for case_id in summary["false_approve_ids"]:
            print(f"   - {case_id}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
