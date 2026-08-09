"""라이터 골든셋 회귀 평가 CLI — 라이터 7종 전부 (2026-08-07 v6부터).

실행: uv run python eval/run_eval_writers.py [golden_path]

평가 로직은 app/eval_writers.py에 있다 (대시보드 GET /v1/eval/writers와 공유) —
이 파일은 CLI 출력·exit code 처리만 담당. briefing·digest·rule_amendment 케이스가
판례를 DB에 시드하므로 llm-postgres가 떠 있어야 한다 (docker compose up -d llm-postgres).
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
from app.eval_writers import run_writers_golden_set  # noqa: E402


async def main() -> int:
    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    label = golden_path.name if golden_path else "writers_golden_v1.json"

    await open_pool()
    await apply_schema()
    try:
        summary = await run_writers_golden_set(golden_path)
    finally:
        await close_pool()

    print(f"라이터 골든셋 {summary['version']} ({label}) — {summary['total']}건 평가 시작\n")
    for r in summary["results"]:
        mark = "O" if r["passed"] else "X"
        print(f" [{mark}] {r['kind']:12s} {r['id']:18s} {r['scenario']}")
        for fail in r["failures"]:
            print(f"      ! {fail}")

    print(f"\n정확도: {summary['correct']}/{summary['total']} = {summary['accuracy']:.1%} "
          f"(기준 ≥ {summary['accuracy_threshold']:.0%})")
    print(f"검증(verified) 불통과: {summary['unverified_count']}건 (기준 = 0건, 하드 게이트)")
    print(f"결과 CSV: {summary['csv_path']}")

    if summary["unverified_count"]:
        print("\n!! 검증 불통과 산출물 발생 — 절대 머지 불가 케이스:")
        for case_id in summary["unverified_ids"]:
            print(f"   - {case_id}")
        return 1
    if summary["accuracy"] < summary["accuracy_threshold"]:
        print("\n!! 정확도 기준 미달")
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
