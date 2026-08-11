"""LangSmith Experiment — budgetops-golden 데이터셋 위에서 심사 그래프 실측 실행.

실행:  $env:MOCK_LLM="false"; $env:LANGSMITH_TRACING="true"; \
       uv run python eval/run_eval_langsmith.py
       (프롬프트 A/B: PROMPT_VERSION_{AGENT}=vN 을 함께 주면 그 버전으로 실험 —
        experiment_prefix에 버전이 박혀 웹에서 버전 간 비교 가능)

어제 업로드한 Dataset(eval/upload_langsmith_dataset.py)을 기준으로 aevaluate를
돌린다. 각 example마다 심사 그래프를 실 LLM으로 실행하고, verdict 일치·오승인
금지를 evaluator로 채점 → LangSmith 웹에 Experiment로 기록된다(프롬프트 버전·비용·
노드 트레이스까지). CSV 하니스(run_eval_real.py)의 웹 버전 — 팀 공유·발표용.

비용: 데이터셋 건수만큼 실 LLM 호출(건당 ≈ $0.006~0.01). 실행 전 골든 팀 회칙
실인덱싱, 실행 후 정리(목 골든셋 게이트 무오염) — run_eval_real.py와 동일 절차.

주의(T9): golden_v1.json의 organizationId·expenseId가 문자열→정수로 바뀌었다
(fixture 기반 재설계). 이 스크립트가 읽는 LangSmith 데이터셋은 구 문자열 값으로
업로드돼 있으므로, 실행 전 upload_langsmith_dataset.py로 재업로드해야 한다.

주의(무료/저티어 계정): 심사 1건이 gpt-4o를 3회 호출하고 프롬프트가 커서,
TPM 30k/min 한도에서는 순차 실행이어도 후반부 1~2건이 429를 맞을 수 있다.
그 경우 해당 심사관 노드가 error 소견을 내고 guardrail_gate가 무조건 escalate로
넘긴다(fail-safe) — 정확도 지표엔 1~2건 반영되지만 **오승인은 절대 발생하지
않는다**(안전 원칙 유지). 근본 회피는 계정 티어 상향 몫.
"""

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402
from app.db.pool import apply_schema, close_pool, open_pool  # noqa: E402
from eval.run_eval_real import clean_golden_teams  # noqa: E402

DATASET_NAME = "budgetops-golden"


def verdict_correct(run, example) -> dict:
    """판정이 기대와 일치하는가."""
    actual = (run.outputs or {}).get("verdict", "escalate")
    expected = (example.outputs or {}).get("expected_verdict")
    return {"key": "verdict_correct", "score": int(actual == expected)}


def no_false_approve(run, example) -> dict:
    """오승인 금지 — must_not_approve인데 approve면 0 (하드 게이트)."""
    actual = (run.outputs or {}).get("verdict", "escalate")
    mna = (example.outputs or {}).get("must_not_approve", False)
    return {"key": "no_false_approve", "score": 0 if (mna and actual == "approve") else 1}


def category_correct(run, example) -> dict:
    """분류(카테고리)가 기대와 일치하는가 — run_eval_real.py의 분류 축과 동일.

    v7 회귀 4건(2026-08-10)이 정확히 이 축에서 났다 — verdict만 보면 안 보이는
    지표라 Experiment에도 별도 열로 남긴다. 기대값 없는 케이스는 분모에서 제외
    (score=None — run_eval_real의 '0점 처리하지 않는다'와 같은 규약).
    """
    expected = (example.outputs or {}).get("expected_category") or ""
    if not expected:
        return {"key": "category_correct", "score": None}
    actual = (run.outputs or {}).get("category") or ""
    return {"key": "category_correct", "score": int(actual == expected)}


def gate_includes_hit(run, example) -> dict:
    """기대 가드레일 규칙이 전부 발동됐는가 (기대값 있는 50건만 채점, 없으면 제외).

    verdict가 맞아도 '왜 막혔는지'가 다르면 회귀다 — budget_insufficient로 막혀야
    할 건이 rule_ambiguous로 막히는 종류의 미끄러짐을 이 축이 잡는다.
    """
    expected = (example.outputs or {}).get("expected_gate_includes") or []
    if not expected:
        return {"key": "gate_includes_hit", "score": None}
    triggered = set((run.outputs or {}).get("gate") or [])
    return {"key": "gate_includes_hit", "score": int(set(expected) <= triggered)}


async def judge_quality(run, example) -> dict:
    """사유 품질 — LLM-as-judge(run_eval_judge.py와 동일 rubric·게이트)를 5번째 축으로.

    approve/reject(사유가 실제 생성된 건)만 채점하고 escalate는 제외(score=None —
    fail-safe 문구라 품질 채점이 무의미). 채점 기준은 passes(): 요청자 정중·내부
    미노출 + 관리자 근거 보유 + 인용 수치 실재(faithfulness, judge/v3) + 점수≥0.7.
    비용: judge gpt-4o 호출이 승인·반려 건수만큼 추가된다(회당 ≈ $0.01).
    """
    from app.eval_judge import judge_reasons, passes
    from app.llm.prompts import load_prompt
    from app.schemas.common import Opinion

    out = run.outputs or {}
    verdict = out.get("verdict")
    if verdict not in ("approve", "reject") or not out.get("reason_requester"):
        return {"key": "judge_quality", "score": None}

    # judge v3(근거 충실성)부터 소견을 대조 자료로 — run_eval_judge.py와 같은 분기
    use_opinions = load_prompt("judge").version not in ("judge/v1", "judge/v2")
    ops = {d["auditor"]: Opinion.model_validate(d) for d in out.get("opinions") or []}
    result, _meta = await judge_reasons(
        verdict, out["reason_requester"], out.get("reason_admin") or "",
        opinions=ops if (use_opinions and ops) else None)
    return {"key": "judge_quality", "score": int(passes(result)),
            "comment": result.notes or ""}


async def main() -> int:
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드가 아닙니다 — MOCK_LLM=false + OPENAI_API_KEY 필요")
        return 2
    if not s.langsmith_api_key:
        print("LANGSMITH_API_KEY가 없습니다 (.env)")
        return 2

    from langsmith import Client, aevaluate

    from app.graphs.review.graph import review_graph
    from app.graphs.indexing.graph import indexing_graph
    from app.llm.prompts import load_prompt

    client = Client(api_key=s.langsmith_api_key)
    if not client.has_dataset(dataset_name=DATASET_NAME):
        print(f"데이터셋 '{DATASET_NAME}' 없음 — 먼저 upload_langsmith_dataset.py 실행")
        return 2

    await open_pool()
    try:
        await apply_schema()
        teams = sorted(
            {
                (ex.inputs or {}).get("organizationId")
                for ex in client.list_examples(dataset_name=DATASET_NAME)
            }
            - {None}
        )
        await clean_golden_teams()
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule"})
        # classifier 포함 — category_correct 축을 채점하므로 어떤 분류기 버전으로
        # 측정했는지가 experiment 이름·메타데이터에 남아야 한다 (v7→v8 교체 전례)
        versions = {a: load_prompt(a).version
                    for a in ("rule_auditor", "adjudicator", "classifier")}
        print(f"골든 팀 {len(teams)}개 회칙 실인덱싱 완료 — 프롬프트 {versions}")

        async def target(inputs: dict) -> dict:
            final = await review_graph.ainvoke(
                {
                    "job_id": f"lsexp-{str(inputs['expenseId'])[:40]}",
                    "external_job_id": inputs.get("jobId"),
                    "expense_id": inputs["expenseId"],
                    "team_id": inputs["organizationId"],
                    "review_goal": inputs.get("reviewGoal", ""),
                    "receipt_text": inputs.get("receipt_text"),
                }
            )
            gate = final.get("gate_result")
            claim = final.get("claim")  # 분류 결과 추출 — run_eval_real.py와 동일 규약
            reasons = final.get("reasons")  # judge_quality 채점 재료 (escalate면 None)
            return {
                "verdict": final.get("verdict") or "escalate",
                "gate": gate.triggered_rules if gate else [],
                "category": (claim.category if claim else "") or "",
                "reason_requester": reasons.requester if reasons else None,
                "reason_admin": reasons.admin if reasons else None,
                # 소견은 judge faithfulness 대조 자료 — 웹 트레이스에서도 보인다
                "opinions": [op.model_dump() for op in (final.get("opinions") or {}).values()],
            }

        prefix = "golden-" + "-".join(v.replace("/", "") for v in versions.values())
        print(f"Experiment 실행 시작: {prefix} (데이터셋 {len(teams)}개 팀, 실 LLM)")
        # max_concurrency=1(순차) — 심사 1건이 gpt-4o를 3회(rule·precedent·adjudicator)
        # 호출하고 프롬프트가 커서, 병렬이면 저티어 TPM 한도(30k/min)를 넘겨 429가 난다.
        # 순차면 분당 토큰이 분산돼 안정.
        results = await aevaluate(
            target,
            data=DATASET_NAME,
            evaluators=[verdict_correct, no_false_approve, category_correct,
                        gate_includes_hit, judge_quality],
            experiment_prefix=prefix,
            metadata={"prompt_versions": versions, "harness": "run_eval_langsmith"},
            max_concurrency=1,
            client=client,
        )
        name = getattr(results, "experiment_name", prefix)
        print(f"\nExperiment 완료: {name}")
        print("LangSmith 웹 → Datasets → budgetops-golden → Experiments 탭에서 확인")
        return 0
    finally:
        try:
            await clean_golden_teams()
        except Exception:
            logging.exception("골든 팀 데이터 사후 정리 실패 — 수동 정리 필요")
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
