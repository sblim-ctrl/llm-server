"""judge 프롬프트 A/B + 환각 탐지 프로브 — 사유 채점기의 채점기 (§4 Sprint 2).

judge 자신도 검증·보정이 필요하다(v1→v2 캘리브레이션 교훈)의 정식 도구화.
run_eval_judge가 '현행 judge로 사유를 채점'한다면, 이 러너는 'judge 버전끼리'를
비교한다:

1) 골든셋 승인·반려 케이스를 실모드 심사(1회) → 사유 2종·심사관 소견 수집
   (eval/results/judge_ab_samples.json 캐시 — 재실행 시 심사비 절약, gitignored)
2) 같은 사유를 베이스라인(v2, 소견 미제공)과 오버라이드(v3, 소견 제공)로 채점
   → 정상 사유를 과잉 불합격시키지 않는지(회귀) 확인
3) 환각 프로브: 관리자 사유의 인용 수치를 자릿수 유지 시프트로 '그럴듯하게' 조작
   → 근거 충실성(faithfulness) 차원이 실제로 잡아내는지 측정

judge v3 승격 실측(2026-07-29): 정상 17/17 v2와 일치 + 프로브 v2 0/6 vs v3 6/6.
전제: judge 모델 gpt-4o (mini는 다중 필드 대조에서 few_shot 앵무새·필드 혼동 —
프롬프트 교정 2회로도 해소 안 됨, models.yaml 주석 참조).

실행: MOCK_LLM=false uv run python eval/compare_judge.py [base_ver] [exp_ver]
      (기본 v2 v3 · 비용: 최초 ~$0.55, 캐시 재사용 시 ~$0.25)
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json  # noqa: E402

from app.config import get_settings                                  # noqa: E402
from app.db.pool import apply_schema, close_pool, open_pool          # noqa: E402
from app.eval_judge import judge_reasons, passes                     # noqa: E402
from app.schemas.common import Opinion                               # noqa: E402
from eval.run_eval_real import clean_golden_teams, receipt_text_for  # noqa: E402

ENV_KEY = "PROMPT_VERSION_JUDGE"
CACHE = ROOT / "eval" / "results" / "judge_ab_samples.json"
PROBE_LIMIT = 6   # 환각 프로브 표본 수 (비용 상한)
# 소견을 넘기지 않는 버전(faithfulness 미지원) — A/B 입력 순수성 유지
NO_OPINIONS_VERSIONS = {"v1", "v2"}


def corrupt_numbers(text: str) -> str:
    """인용 수치를 '그럴듯하게' 조작 — 2자리 이상 숫자 뭉치의 자릿수를 시프트.

    형식(콤마·원 단위)을 유지해 '근거 수치 존재' 판단은 통과할 수준으로.
    예: 182,000 → 415,333 스타일 (같은 자릿수, 다른 값)."""
    def shift(m: re.Match) -> str:
        return "".join(str((int(d) + 3) % 10) for d in m.group(0))
    return re.sub(r"\d{2,}", shift, text)


async def judge_with(version: str, verdict: str, req: str, adm: str, opinions):
    os.environ[ENV_KEY] = version
    try:
        return await judge_reasons(
            verdict, req, adm,
            opinions=None if version in NO_OPINIONS_VERSIONS else opinions)
    finally:
        os.environ.pop(ENV_KEY, None)


async def collect_samples(cases) -> tuple[list[dict], float]:
    """골든셋 승인·반려 사유 수집 (실모드 심사 1회) — 캐시 우선."""
    if CACHE.exists():
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
        samples = [{**s, "opinions": {k: Opinion(**v)
                                      for k, v in s["opinions"].items()}}
                   for s in raw]
        print(f"캐시 재사용: 사유 {len(samples)}건 (심사 재실행 생략)\n")
        return samples, 0.0

    from app.graphs.indexing.graph import indexing_graph
    from app.graphs.review.graph import review_graph
    from app.schemas.analyze import AnalyzeRequest

    await apply_schema()
    await clean_golden_teams()
    teams = sorted({c["input"]["organizationId"] for c in cases})
    for t in teams:
        await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule", "version": 1})
    print(f"팀 {len(teams)}개 실인덱싱 — 심사 실행(사유 수집)…")

    samples, cost = [], 0.0
    for case in cases:
        req = AnalyzeRequest.model_validate(case["input"])
        final = await review_graph.ainvoke({
            "job_id": f"jab-{case['id']}",
            "external_job_id": req.job_id,
            "expense_id": req.expense_id,
            "team_id": req.organization_id,
            "receipt_text": receipt_text_for(case["input"]),
        })
        cost += sum(m.cost_usd for m in (final.get("llm_meta") or {}).values())
        verdict, reasons = final.get("verdict"), final.get("reasons")
        if verdict in ("approve", "reject") and reasons is not None:
            samples.append({"id": case["id"], "verdict": verdict,
                            "req": reasons.requester, "adm": reasons.admin,
                            "opinions": final.get("opinions") or {}})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(
        [{**s, "opinions": {k: v.model_dump() for k, v in s["opinions"].items()}}
         for s in samples], ensure_ascii=False), encoding="utf-8")
    await clean_golden_teams()
    print(f"사유 수집 {len(samples)}건 (심사 비용 ${cost:.3f}) — 캐시 저장\n")
    return samples, cost


async def main() -> int:
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드 필요: MOCK_LLM=false + OPENAI_API_KEY")
        return 2
    base_ver = sys.argv[1] if len(sys.argv) > 1 else "v2"
    exp_ver = sys.argv[2] if len(sys.argv) > 2 else "v3"

    golden = json.loads((ROOT / "eval/golden/golden_v1.json").read_text(encoding="utf-8"))

    await open_pool()
    try:
        samples, review_cost = await collect_samples(golden["cases"])

        # ── A/B: 같은 사유를 두 버전으로 채점 ──
        rows, jcost = [], 0.0
        for smp in samples:
            rb, mb = await judge_with(base_ver, smp["verdict"], smp["req"],
                                      smp["adm"], smp["opinions"])
            rx, mx = await judge_with(exp_ver, smp["verdict"], smp["req"],
                                      smp["adm"], smp["opinions"])
            jcost += mb.cost_usd + mx.cost_usd
            rows.append((smp["id"], smp["verdict"], rb, rx))

        print(f"{'케이스':28s} {'판정':7s} {base_ver:>10s} {exp_ver:>10s}  faithful({exp_ver})")
        print("-" * 78)
        agree = 0
        for cid, v, rb, rx in rows:
            pb, px = passes(rb), passes(rx)
            agree += pb == px
            print(f"{cid:28s} {v:7s} {('합격' if pb else '불합격'):>8s}"
                  f" {('합격' if px else '불합격'):>8s}"
                  f"  {'OK' if rx.admin_grounds_faithful else '⚠️환각판정'}")
            if pb and not px:
                print(f"    └ {exp_ver} 진단: polite={rx.requester_polite} "
                      f"leak={rx.requester_leaks_internal} grounds={rx.admin_has_grounds} "
                      f"faithful={rx.admin_grounds_faithful} score={rx.overall_score:.2f}")
                print(f"      notes: {rx.notes[:90]}")
        n = len(rows)
        print(f"\n[정상 사유] {base_ver}·{exp_ver} 판정 일치 {agree}/{n} — "
              f"{exp_ver}가 정상 사유를 과잉 불합격시키지 않는지 (회귀 방지)")

        # ── 환각 프로브 ──
        probes = [s0 for s0 in samples if re.search(r"\d{2,}", s0["adm"])][:PROBE_LIMIT]
        print(f"\n=== 환각 프로브 ({len(probes)}건 — 관리자 사유 수치 조작) ===")
        base_caught = exp_caught = 0
        for smp in probes:
            bad = corrupt_numbers(smp["adm"])
            rb, mb = await judge_with(base_ver, smp["verdict"], smp["req"], bad,
                                      smp["opinions"])
            rx, mx = await judge_with(exp_ver, smp["verdict"], smp["req"], bad,
                                      smp["opinions"])
            jcost += mb.cost_usd + mx.cost_usd
            cb, cx = not passes(rb), (not passes(rx)) and not rx.admin_grounds_faithful
            base_caught += cb
            exp_caught += cx
            print(f"  {smp['id']:28s} {base_ver} {'잡음' if cb else '통과(놓침)'} / "
                  f"{exp_ver} {'잡음(faithful=False)' if cx else '놓침'}")
            if not cx:
                print(f"    └ {exp_ver} notes: {rx.notes[:70]}")
        print(f"\n[환각 탐지] {base_ver} {base_caught}/{len(probes)} vs "
              f"{exp_ver} {exp_caught}/{len(probes)}")
        print(f"judge 비용 ${jcost:.4f} · 총 비용 ${review_cost + jcost:.3f}")
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
