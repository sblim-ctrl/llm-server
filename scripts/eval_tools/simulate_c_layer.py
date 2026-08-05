"""C층 개방 시뮬레이션 — 코드는 안 고치고 골든셋 영향만 측정.

바꾸려는 것: 지금은 '금액 > 자동승인 한도'면 무조건 사람에게 올린다. 이걸
'자동승인 한도 < 금액 <= 절대 상한' 구간은 adjudicate로 보내 확신도로 판단하게 한다.

절대 상한(force_escalation_amount) 초과는 그대로 무조건 사람이다. 다른 규칙이 하나라도
함께 걸리면 역시 그대로 사람이다 — 순수하게 금액만 걸린 건만 연다.
"""
import asyncio
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.graphs.review.nodes import guardrail_gate as gg  # noqa: E402
from app.schemas.common import GateResult  # noqa: E402

_original = gg.evaluate_guardrails
OPEN_RULE = "over_auto_approve_limit"


def patched(**kwargs) -> GateResult:
    """금액 한도 하나만 걸린 건을 adjudicate로 넘긴다."""
    result = _original(**kwargs)
    if result.decision == "escalate" and result.triggered_rules == [OPEN_RULE]:
        return GateResult(decision="proceed", triggered_rules=[])
    return result


async def main() -> None:
    gg.evaluate_guardrails = patched
    from app.eval_support import run_golden_set  # 패치 후 임포트

    await open_pool()
    await apply_schema()
    try:
        summary = await run_golden_set()
    finally:
        await close_pool()

    base = {r["id"]: r for r in csv.DictReader(
        io.open(ROOT / "eval" / "results" / "golden_run.csv", encoding="utf-8-sig"))}

    results = summary["results"]
    total = len(results)
    auto = sum(1 for r in results if r["actual"] in ("approve", "reject"))
    fa = [r for r in results if r.get("false_approve")]

    print("=" * 72)
    print("C층 개방 시뮬레이션 결과")
    print("=" * 72)
    print(f"정확도       {summary['correct']}/{total} = {summary['accuracy']:.1%}   (기준선 42/42 = 100%)")
    print(f"오승인       {len(fa)}건   (하드 게이트 = 0건)")
    print(f"자동 종결    {auto}/{total} = {auto/total:.0%}   (기준선 17/42 = 40%)")

    changed = []
    for r in results:
        b = base.get(r["id"])
        if b and b["actual"] != r["actual"]:
            changed.append((r["id"], b["actual"], r["actual"], r["expected"],
                            "OK" if r["actual"] == r["expected"] else "틀림"))
    print(f"\n판정이 바뀐 건: {len(changed)}건")
    print(f"{'id':30} {'기준선':>9} → {'변경후':<9} {'기대':<9} 결과")
    print("-" * 72)
    for cid, before, after, exp, ok in changed:
        print(f"{cid:30} {before:>9} → {after:<9} {exp:<9} {ok}")

    if fa:
        print("\n!! 오승인 발생 — 하드 게이트 위반")
        for r in fa:
            print(f"   {r['id']}  기대={r['expected']} 실제={r['actual']}")


asyncio.run(main())
