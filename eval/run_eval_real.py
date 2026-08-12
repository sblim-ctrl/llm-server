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
import functools
import json
import logging
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

from app.config import get_settings  # noqa: E402
from app.db.pool import apply_schema, close_pool, get_pool, open_pool  # noqa: E402
from app.eval_support import gate_rules_from_state  # noqa: E402 — 궤적 도출 규칙 공유

DEFAULT_GOLDEN = ROOT / "eval" / "golden" / "golden_v1.json"
FIXTURE_PATH = ROOT / "eval" / "fixtures" / "mock_backend.json"
RESULTS_DIR = ROOT / "eval" / "results"
ACCURACY_TARGET = 0.90


@functools.cache
def _fixture_expenses() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["expenses"]


def receipt_text_for(case_input: dict) -> str | None:
    """receiptPath → receipt_text 변환 — 목 규약 의미 보존 (모듈 docstring 3번).

    expenseId는 T9부터 fixture 정수 키다 — 지출 금액·날짜는 쿼리스트링이 아니라
    eval/fixtures/mock_backend.json에서 읽는다.
    """
    expense = _fixture_expenses()[str(case_input["expenseId"])]
    amount, dt = expense["amount"], expense["date"]
    rp = case_input.get("receiptPath")
    if not rp:
        return None  # 미첨부 시나리오
    if rp.startswith("mock://receipt"):
        p = parse_qs(urlsplit(rp).query)  # 오버라이드 → 불일치 시나리오
        amount = int(p["amount"][0]) if "amount" in p else amount
        dt = p["date"][0] if "date" in p else dt
    return f"영수증 합계 {amount:,}원 / {dt}"


GOLDEN_TEAM_ID_RANGE = (9000, 9999)  # eval/fixtures/mock_backend.json의 조직 대역(T9)


async def clean_golden_teams() -> None:
    """골든 팀 잔재 정리 — 판례(목/실 임베딩 혼입 방지)·회칙 청크 (docstring 1·4번).

    team_id가 BIGINT로 전환된 뒤로는 `LIKE 'golden-%'`가 성립하지 않는다(T9) — 골든
    ID 대역 전체를 지운다. 이번 실행이 실제로 쓰는 ID만 지우면, 골든셋이 바뀌어 어떤
    ID가 더 이상 쓰이지 않게 됐을 때 그 행이 영구히 남아 실키 임베딩이 목 게이트를
    오염시킬 수 있다 — 대역 전체를 지우는 편이 더 안전하다.
    """
    async with get_pool().connection() as conn:
        await conn.execute(
            "DELETE FROM precedents WHERE team_id BETWEEN %s AND %s", GOLDEN_TEAM_ID_RANGE
        )
        await conn.execute(
            "DELETE FROM context_chunks WHERE team_id BETWEEN %s AND %s", GOLDEN_TEAM_ID_RANGE
        )


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

        teams = sorted({c["input"]["organizationId"] for c in cases})
        await clean_golden_teams()
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule"})
        print(f"골든 팀 {len(teams)}개 회칙 실인덱싱 완료 — 실행 시작\n")

        # cat_* — 분류 정확도(관측). 목 모드(run_eval)의 숫자는 실LLM을 안 부르는
        # 키워드 규칙 정확도라 실서비스 품질이 아니다. 실LLM이 분류하는 **여기가 진짜
        # 숫자가 나오는 자리**다 (T9 검토 §3). 판정 통과·실패에는 관여하지 않는다.
        rows, correct, false_appr, cost_total = [], 0, [], 0.0
        cat_total = cat_correct = 0
        cat_misses: list[tuple[str, str, str]] = []
        for case in cases:
            req = AnalyzeRequest.model_validate(case["input"])
            final = await review_graph.ainvoke(
                {
                    "job_id": f"eval-real-{case['id']}",
                    "external_job_id": req.job_id,
                    "expense_id": req.expense_id,
                    "team_id": req.organization_id,
                    "receipt_text": receipt_text_for(case["input"]),
                }
            )
            actual = final.get("verdict") or "escalate"
            exp = case["expected_verdict"]
            ok = actual == exp
            fa = bool(case.get("must_not_approve")) and actual == "approve"
            cost = sum(m.cost_usd for m in (final.get("llm_meta") or {}).values())
            cost_total += cost
            correct += ok
            if fa:
                false_appr.append(case["id"])
            # 궤적 도출은 로컬 CSV 하니스·LangSmith와 **같은 함수**를 쓴다 — 직접
            # gate_result만 읽으면 영수증 불일치(mismatch_gate 단락) 경로가 빈칸이 된다
            gate_rules = "|".join(gate_rules_from_state(final))

            # 분류 채점 — 기대값 없는 케이스는 분모에서 뺀다(0점 처리하지 않는다)
            claim = final.get("claim")
            cat_act = (claim.category if claim else "") or ""
            cat_exp = case.get("expected_category") or ""
            if cat_exp:
                cat_total += 1
                if cat_act == cat_exp:
                    cat_correct += 1
                else:
                    cat_misses.append((case["id"], cat_exp, cat_act))

            rows.append(
                [case["id"], exp, actual, ok, fa, gate_rules, f"{cost:.5f}", cat_exp, cat_act]
            )
            mark = "O" if ok else "X"
            print(
                f" [{mark}] {case['id']:30s} 기대={exp:8s} 실제={actual:8s} ${cost:.4f}"
                + (f"  gate={gate_rules}" if not ok else "")
            )

        n = len(rows)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"golden_realmode_{date.today().isoformat()}.csv"
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                ["id", "expected", "actual", "correct", "false_approve", "gate", "cost_usd",
                 "expected_category", "actual_category"]
            )
            w.writerows(rows)

        acc = correct / n if n else 0.0
        print(f"\n정확도: {correct}/{n} = {acc:.1%} (실모드 목표 ≥ {ACCURACY_TARGET:.0%})")
        print(f"오승인(하드 게이트): {len(false_appr)}건 {false_appr or ''}")

        # 분류 정확도 — 실LLM 기준. 목 모드 숫자와 나란히 놓고 봐야 의미가 있다.
        if cat_total:
            print(
                f"분류 정확도: {cat_correct}/{cat_total} = {cat_correct / cat_total:.1%} "
                "(실LLM 기준 — 목 모드 숫자는 키워드 규칙 정확도라 별개다)"
            )
            for case_id, want, got in cat_misses:
                print(f"  오분류 {case_id:30s} 기대={want:10s} 실제={got}")

        # 판정 지표 (§4 Sprint 2) — rows에서 expected·actual만 추려 순수 계산
        from app.eval_metrics import verdict_metrics

        m = verdict_metrics([{"expected": r[1], "actual": r[2]} for r in rows])

        def _pct(v: float | None) -> str:
            return "N/A" if v is None else f"{v:.0%}"

        print(
            f"자동 처리율: {m['automation_rate']:.0%} | "
            f"에스컬레이션 R={_pct(m['escalation_recall'])} "
            f"P={_pct(m['escalation_precision'])} (안전 핵심)"
        )
        for label in ("approve", "reject", "escalate"):
            p = m["per_class"][label]
            print(
                f"  {label:8s}(n={p['support']:2d}): "
                f"P={_pct(p['precision'])} R={_pct(p['recall'])} F1={_pct(p['f1'])}"
            )
        print(
            f"총 비용 ${cost_total:.4f} (건당 평균 ${cost_total / n:.4f}) · "
            f"소요 {time.time() - started:.0f}s · CSV: {out}"
        )

        if false_appr:
            print("\n!! 오승인 발생 — 절대 머지 불가")
            return 1
        if acc < ACCURACY_TARGET:
            print("\n주의: 실모드 정확도 목표 미달 — 튜닝 백로그 확인 (PROGRESS §6-1)")
        return 0
    finally:
        # try 블록 중간에 예외가 나도 사후 정리는 항상 실행돼야 한다 — 그래야
        # 실키 임베딩이 남아 다음 목 골든셋 실행을 오염시키는 경로가 안 생긴다.
        # 정리 자체가 실패해도 close_pool()은 반드시 돌아야 커넥션이 새지 않는다.
        try:
            await clean_golden_teams()
            print("골든 팀 데이터 사후 정리 완료 (목 골든셋 게이트 무오염)")
        except Exception:
            logging.exception("골든 팀 데이터 사후 정리 실패 — 수동 정리 필요")
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
