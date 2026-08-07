"""LLM-as-Judge 하니스 — 골든셋 승인·반려 케이스의 '사유 품질'을 채점 (§4 Sprint 2).

실행:  $env:MOCK_LLM="false"; uv run python eval/run_eval_judge.py
       (목 모드에서도 구조는 돌지만 사유·채점이 전부 목이라 품질 의미는 실모드에서)

절차: run_eval_real과 동일(골든 팀 회칙 실인덱싱·전후 정리)로 각 케이스를 심사한 뒤,
verdict가 approve/reject인 건(사유가 실제 생성된 건)의 reason_requester·reason_admin을
judge_reasons로 채점한다. escalate는 사유가 fail-safe 문구라 대상 제외.

게이트: judge 불합격(요청자 무례/내부노출 or 관리자 근거없음 or 점수<0.7)이 있으면
목록 출력. 정확도 게이트(run_eval_real)와 별개의 '사유 품질' 축.
비용: 승인·반려 ~17건 × (심사 gpt-4o + judge gpt-4o-mini) ≈ $0.15.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json  # noqa: E402

from app.config import get_settings                                     # noqa: E402
from app.db.pool import apply_schema, close_pool, open_pool             # noqa: E402
from app.eval_judge import judge_reasons, passes                        # noqa: E402
from eval.run_eval_real import clean_golden_teams, receipt_text_for     # noqa: E402

DEFAULT_GOLDEN = ROOT / "eval" / "golden" / "golden_v1.json"


async def main() -> int:
    s = get_settings()
    if s.mock_llm:
        print("주의: 목 모드 — 사유·채점이 전부 목입니다(구조 스모크만). "
              "품질 측정은 MOCK_LLM=false로 실행하세요.\n")

    golden = json.loads(DEFAULT_GOLDEN.read_text(encoding="utf-8"))
    cases = golden["cases"]

    await open_pool()
    try:
        from app.graphs.indexing.graph import indexing_graph
        from app.graphs.review.graph import review_graph
        from app.schemas.analyze import AnalyzeRequest

        await apply_schema()
        await clean_golden_teams()
        teams = sorted({c["input"]["organizationId"] for c in cases})
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule"})

        judged, fails, score_sum, cost = 0, [], 0.0, 0.0
        for case in cases:
            req = AnalyzeRequest.model_validate(case["input"])
            final = await review_graph.ainvoke({
                "job_id": f"judge-{case['id']}",
                "external_job_id": req.job_id,
                "expense_id": req.expense_id,
                "team_id": req.organization_id,
                "receipt_text": receipt_text_for(case["input"]),
            })
            verdict = final.get("verdict")
            reasons = final.get("reasons")
            if verdict not in ("approve", "reject") or reasons is None:
                continue  # 사유가 생성된 승인·반려만 채점 (escalate 제외)

            # judge v3(근거 충실성)부터는 심사관 소견을 대조 자료로 전달 —
            # v1·v2는 소견을 채점하지 않으므로 입력을 기존과 동일하게 유지(A/B 순수성)
            from app.llm.prompts import load_prompt
            use_opinions = load_prompt("judge").version not in ("judge/v1", "judge/v2")
            result, meta = await judge_reasons(
                verdict, reasons.requester, reasons.admin,
                opinions=(final.get("opinions") or {}) if use_opinions else None)
            cost += meta.cost_usd
            judged += 1
            score_sum += result.overall_score
            ok = passes(result)
            mark = "O" if ok else "X"
            print(f" [{mark}] {case['id']:30s} {verdict:7s} score={result.overall_score:.2f}"
                  + (f"  ← {result.notes}" if not ok else ""))
            if not ok:
                fails.append(case["id"])

        await clean_golden_teams()
        if not judged:
            print("채점 대상(승인·반려) 케이스 없음")
            return 0
        print(f"\n사유 품질: {judged}건 채점 · 평균 {score_sum / judged:.2f} · "
              f"합격 {judged - len(fails)}/{judged} · judge 비용 ${cost:.4f}")
        if fails:
            print(f"불합격(사유 품질): {fails}")
            return 1
        print("전건 사유 품질 합격")
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
