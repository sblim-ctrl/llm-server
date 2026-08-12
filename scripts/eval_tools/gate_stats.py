"""골든셋 전체에서 가드레일이 실제로 무엇 때문에 발동하는지 집계.

'AI가 어디까지 판단하고 어디부터 사람에게 올리나'를 정하려면, 지금 무엇 때문에
사람에게 올라가고 있는지부터 알아야 한다.
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.eval_support import run_golden_set  # noqa: E402


async def main() -> None:
    await open_pool()
    await apply_schema()
    try:
        summary = await run_golden_set()
    finally:
        await close_pool()

    results = summary["results"]
    rules = Counter()
    per_expected = Counter()
    for r in results:
        per_expected[r["expected"]] += 1
        # run_case 결과의 키는 "gate"다 (eval_support.py run_case 반환 딕셔너리).
        # 한때 "triggered_rules"(final_state 안 GateResult의 속성명)를 읽어 집계가
        # 항상 0이었다 (#93) — 속성명과 결과 키를 혼동하지 말 것.
        for rule in (r.get("gate") or []):
            rules[rule] += 1

    total = len(results)
    auto = sum(1 for r in results if r["actual"] in ("approve", "reject"))
    print(f"골든셋 {total}건 — 자동 종결 {auto}건 ({auto/total:.0%}) / 사람에게 {total-auto}건\n")

    print("기대 판정 분포")
    for k, v in per_expected.most_common():
        print(f"  {k:10} {v:2}건")

    print("\n사람에게 올린 이유 (중복 발동 포함)")
    for rule, n in rules.most_common():
        print(f"  {rule:32} {n:2}회")

    # 금액 규칙만으로 올라간 건 = 다른 문제 없이 '금액이 커서'만인 경우
    only_amount = [
        r for r in results
        if r.get("gate")
        and set(r["gate"]) <= {"over_auto_approve_limit",
                               "over_force_escalation_amount"}
    ]
    print(f"\n금액 때문에만 올라간 건: {len(only_amount)}건")
    for r in only_amount:
        print(f"  {r['id']:28} {','.join(r['gate'])}")


asyncio.run(main())
