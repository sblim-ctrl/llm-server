"""골든셋 실모드 평가 하니스 — 실 LLM으로 판정 품질 실측 (사용자 트랙 §6-1).

실행:  MOCK_LLM=false 를 프로세스에 주입해 실행 (.env의 MOCK_LLM=true는 건드리지
말 것 — 전체 pytest가 목 모드에 의존):

    $env:MOCK_LLM="false"; uv run python eval/run_eval_real.py          # PowerShell
    MOCK_LLM=false uv run python eval/run_eval_real.py [golden_path]    # bash

프롬프트 A/B: PROMPT_VERSION_{AGENT}=vN 환경변수를 함께 주면 해당 버전으로 실행.

목 골든셋(eval/run_eval.py)과 다른 점 — 2026-07-20 실측 6회전에서 확립한 절차:
1. 골든 팀 데이터 사전 정리 — 과거 목 실행이 남긴 목 임베딩 판례가 실모드
   의미 검색에 잡히는 오염 제거 (1차 실측에서 발견된 하니스 결함의 재발 방지).
2. 회칙 실인덱싱 — 골든 팀들에 목 회칙 원문을 실임베딩으로 인덱싱 (rule_auditor의
   실 RAG 경로 활성화. 목 골든셋은 회칙 미인덱싱 = no_rules 경로라 서로 불간섭).
3. 영수증은 receipt_text로 변환 — 골든셋의 가짜 URL은 실 Vision에서 판독 불능이
   되므로, 목 규약(기본=청구 일치, mock:// 파라미터=불일치)을 텍스트로 재현.
   Vision 실경로는 A-9에서 실이미지로 별도 검증됨.
4. 실행 후 골든 팀 데이터 사후 정리 — 목 골든셋 CI 게이트 무오염 보장.

게이트: 오승인(false-approve) 1건이라도 있으면 exit 1 (목 게이트와 동일 하드 기준).
정확도는 참고 지표로 출력 (실모드 목표 ≥90% — PROGRESS §6-1 추이 참고).
비용: 30건 기준 약 $0.15~0.25 (gpt-4o, 건당 평균 ~$0.006).
"""
import asyncio
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings                                    # noqa: E402
from app.db.pool import apply_schema, close_pool, get_pool, open_pool  # noqa: E402

DEFAULT_GOLDEN = ROOT / "eval" / "golden" / "golden_v1.json"
RESULTS_DIR = ROOT / "eval" / "results"
ACCURACY_TARGET = 0.90


def receipt_text_for(case_input: dict) -> str | None:
    """receiptPath → receipt_text 변환 — 목 규약 의미 보존 (모듈 docstring 3번)."""
    q = parse_qs(urlsplit(case_input["expenseId"]).query)
    amount, dt = int(q["amount"][0]), q["date"][0]
    rp = case_input.get("receiptPath")
    if not rp:
        return None                                  # 미첨부 시나리오
    if rp.startswith("mock://receipt"):
        p = parse_qs(urlsplit(rp).query)              # 오버라이드 → 불일치 시나리오
        amount = int(p["amount"][0]) if "amount" in p else amount
        dt = p["date"][0] if "date" in p else dt
    return f"영수증 합계 {amount:,}원 / {dt}"


async def clean_golden_teams() -> None:
    """골든 팀 잔재 정리 — 판례(목/실 임베딩 혼입 방지)·회칙 청크 (docstring 1·4번)."""
    async with get_pool().connection() as conn:
        await conn.execute("DELETE FROM precedents WHERE team_id LIKE 'golden-%%'")
        await conn.execute("DELETE FROM context_chunks WHERE team_id LIKE 'golden-%%'")


async def main() -> int:
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드가 아닙니다 — MOCK_LLM=false 환경변수와 OPENAI_API_KEY가 필요합니다.")
        print('예: $env:MOCK_LLM="false"; uv run python eval/run_eval_real.py')
        return 2

    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GOLDEN
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]

    await open_pool()
    started = time.time()
    try:
        from app.graphs.indexing.graph import indexing_graph
        from app.graphs.review.graph import review_graph
        from app.llm.prompts import load_prompt
        from app.schemas.analyze import AnalyzeRequest

        await apply_schema()
        versions = {a: load_prompt(a).version for a in ("rule_auditor", "adjudicator")}
        print(f"골든셋 {golden['version']} {len(cases)}건 실모드 실측 — 프롬프트 {versions}")

        await clean_golden_teams()
        teams = sorted({c["input"]["organizationId"] for c in cases})
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule", "version": 1})
        print(f"골든 팀 {len(teams)}개 회칙 실인덱싱 완료 — 실행 시작\n")

        rows, correct, false_appr, cost_total = [], 0, [], 0.0
        for case in cases:
            req = AnalyzeRequest.model_validate(case["input"])
            final = await review_graph.ainvoke({
                "job_id": f"eval-real-{case['id']}",
                "external_job_id": req.job_id,
                "expense_id": req.expense_id,
                "team_id": req.organization_id,
                "receipt_text": receipt_text_for(case["input"]),
            })
            actual = final.get("verdict") or "escalate"
            exp = case["expected_verdict"]
            ok = actual == exp
            fa = bool(case.get("must_not_approve")) and actual == "approve"
            cost = sum(m.cost_usd for m in (final.get("llm_meta") or {}).values())
            cost_total += cost
            correct += ok
            if fa:
                false_appr.append(case["id"])
            gate = final.get("gate_result")
            gate_rules = "|".join(gate.triggered_rules) if gate else ""
            rows.append([case["id"], exp, actual, ok, fa, gate_rules, f"{cost:.5f}"])
            mark = "O" if ok else "X"
            print(f" [{mark}] {case['id']:30s} 기대={exp:8s} 실제={actual:8s} ${cost:.4f}"
                  + (f"  gate={gate_rules}" if not ok else ""))

        n = len(rows)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"golden_realmode_{date.today().isoformat()}.csv"
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "expected", "actual", "correct", "false_approve",
                        "gate", "cost_usd"])
            w.writerows(rows)

        acc = correct / n if n else 0.0
        print(f"\n정확도: {correct}/{n} = {acc:.1%} (실모드 목표 ≥ {ACCURACY_TARGET:.0%})")
        print(f"오승인(하드 게이트): {len(false_appr)}건 {false_appr or ''}")
        print(f"총 비용 ${cost_total:.4f} (건당 평균 ${cost_total / n:.4f}) · "
              f"소요 {time.time() - started:.0f}s · CSV: {out}")

        await clean_golden_teams()
        print("골든 팀 데이터 사후 정리 완료 (목 골든셋 게이트 무오염)")

        if false_appr:
            print("\n!! 오승인 발생 — 절대 머지 불가")
            return 1
        if acc < ACCURACY_TARGET:
            print("\n주의: 실모드 정확도 목표 미달 — 튜닝 백로그 확인 (PROGRESS §6-1)")
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
