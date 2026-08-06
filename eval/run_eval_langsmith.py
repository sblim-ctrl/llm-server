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
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule", "version": 1})
        versions = {a: load_prompt(a).version for a in ("rule_auditor", "adjudicator")}
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
            return {
                "verdict": final.get("verdict") or "escalate",
                "gate": gate.triggered_rules if gate else [],
            }

        prefix = "golden-" + "-".join(v.replace("/", "") for v in versions.values())
        print(f"Experiment 실행 시작: {prefix} (데이터셋 {len(teams)}개 팀, 실 LLM)")
        # max_concurrency=1(순차) — 심사 1건이 gpt-4o를 3회(rule·precedent·adjudicator)
        # 호출하고 프롬프트가 커서, 병렬이면 저티어 TPM 한도(30k/min)를 넘겨 429가 난다.
        # 순차면 분당 토큰이 분산돼 안정.
        results = await aevaluate(
            target,
            data=DATASET_NAME,
            evaluators=[verdict_correct, no_false_approve],
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
