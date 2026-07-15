"""프롬프트 A/B 비교 러너 (P2 — 프롬프트·평가·관측 축).

같은 골든셋을 [베이스라인]과 [오버라이드 버전]으로 두 번 돌려 케이스별 판정
변화·정확도·오승인 차이를 보여준다. 프롬프트 튜닝 사이클의 기본 도구:

  1) prompts/adjudicator/v2.yaml 을 만들고 (version: adjudicator/v2)
  2) uv run python eval/compare_prompts.py adjudicator=v2
  3) 판정이 바뀐 케이스를 보고 v2를 다듬는다 — 오승인이 늘면 즉시 기각

여러 에이전트 동시 오버라이드 가능: adjudicator=v2 rule_auditor=v3
전제: llm-postgres 기동. ⚠️ MOCK_LLM=true면 두 실행이 동일할 수밖에 없다
(목은 프롬프트를 안 읽음) — 실키 연결 후에만 의미 있는 비교가 된다.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402
from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from app.eval_support import VERDICT_LABELS, run_golden_set  # noqa: E402
from app.llm.prompts import _ENV_PREFIX  # noqa: E402


def parse_overrides(args: list[str]) -> dict[str, str]:
    overrides = {}
    for arg in args:
        if "=" not in arg:
            print(f"무시: '{arg}' (형식: agent=version, 예: adjudicator=v2)")
            continue
        agent, version = arg.split("=", 1)
        overrides[agent.strip()] = version.strip()
    return overrides


async def main() -> int:
    overrides = parse_overrides(sys.argv[1:])
    if not overrides:
        print(__doc__)
        return 1

    if get_settings().mock_llm:
        print("⚠️  MOCK_LLM=true — 목 응답은 프롬프트를 읽지 않으므로 두 실행이 동일합니다.")
        print("    (러너 배관 검증용으로만 실행하고, 실측 비교는 실키 연결 후에)\n")

    await open_pool()
    await apply_schema()
    try:
        print("=== [A] 베이스라인 (v1) 실행 중…")
        base = await run_golden_set()

        for agent, version in overrides.items():
            os.environ[f"{_ENV_PREFIX}{agent.upper()}"] = version
        label = ", ".join(f"{a}={v}" for a, v in overrides.items())
        print(f"=== [B] 오버라이드 ({label}) 실행 중…")
        try:
            exp = await run_golden_set()
        finally:
            for agent in overrides:
                os.environ.pop(f"{_ENV_PREFIX}{agent.upper()}", None)
    finally:
        await close_pool()

    changed = []
    for a, b in zip(base["results"], exp["results"]):
        if a["actual"] != b["actual"]:
            changed.append((a["id"], a["expected"], a["actual"], b["actual"]))

    print(f"\n{'=' * 60}")
    print(f"{'':16s}  [A] v1        [B] {label}")
    print(f"{'정확도':14s}  {base['accuracy']:.1%}        {exp['accuracy']:.1%}")
    print(f"{'오승인':14s}  {base['false_approve_count']}건          {exp['false_approve_count']}건")
    if base["trajectory_total"]:
        print(f"{'Trajectory':14s}  {base['trajectory_correct']}/{base['trajectory_total']}"
              f"        {exp['trajectory_correct']}/{exp['trajectory_total']}")

    if changed:
        print(f"\n판정 변화 {len(changed)}건:")
        for case_id, expected, a, b in changed:
            better = ("↑개선" if b == expected else "↓악화" if a == expected else "  변화")
            print(f"  [{better}] {case_id:28s} 기대={VERDICT_LABELS[expected]} "
                  f": {VERDICT_LABELS.get(a, a)} → {VERDICT_LABELS.get(b, b)}")
    else:
        print("\n판정 변화 없음.")

    if exp["false_approve_count"] > base["false_approve_count"]:
        print("\n!! 오버라이드가 오승인을 늘림 — 채택 불가 (§9 하드 게이트)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
