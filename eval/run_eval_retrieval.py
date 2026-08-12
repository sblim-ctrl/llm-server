"""회칙 검색 품질 평가 — context_recall (실모드 전용).

실행:  $env:MOCK_LLM="false"; uv run python eval/run_eval_retrieval.py [golden_path]
       (기본 골든: eval/golden/golden_rule_axis.json — `expected_rule_clauses`
        라벨이 있는 케이스만 채점하고, 없는 케이스는 건너뛴다)

**왜 필요한가**: 기존 평가 축(run_eval·run_eval_langsmith)은 전부 최종 판정을 본다.
그래서 **엉뚱한 조항을 검색해도 판정만 맞으면 통과한다** — 검색이 맞아서 맞은 것인지
운으로 맞은 것인지 구분할 수 없다. 이 하니스는 그 사각지대 하나만 본다:
"판정의 근거가 됐어야 할 회칙 조항이 실제로 검색됐는가."

**측정 대상은 재구현하지 않는다.** `rule_auditor._retrieve_with_correction`을 그대로
호출한다 — 질의 구성(title+description)·거리 필터(RELEVANCE_MAX_DISTANCE)·CRAG 재작성
재검색까지 심사가 타는 경로 그대로다. 여기서 검색 로직을 흉내 내면 프로덕션 경로와
갈라져 "하니스만 통과하는" 측정이 된다. claim·rule_version도 실제 `load_context`
노드를 돌려 얻는다(같은 이유).

**실모드 전용**: 목 임베딩은 해시 기반(바이트가 같아야 거리 0)이라 의미 검색이라는
개념 자체가 성립하지 않는다. 목 모드로 돌리면 숫자가 나와도 뜻이 없다.

채점:
- `expected_rule_clauses`가 비어 있지 않은 케이스 → **recall**: 기대 조항이 검색
  결과에 있는가. 전부 있으면 적중(strict), 일부면 부분 점수로 함께 표시한다.
- `expected_rule_clauses`가 빈 리스트인 케이스(대조군) → 회칙이 다루지 않는 지출인데
  조항이 잡히면 **경고**로만 남긴다. 실패로 보지 않는 이유: 후보 조항을 가져와 심사관
  LLM이 "해당 없음"으로 판단하는 것도 정상 동작이고(Self-RAG), "아무것도 검색되면
  안 된다"를 팀 규칙으로 합의한 적이 없다. 다만 무관한 금지 조항이 근거 자료로
  들어가는 것은 위험 신호라 눈에 보이게 남긴다.
- **precision은 채점하지 않는다.** 기대 조항 외에 딸려 온 조항이 곧 오답은 아니다
  (회식비 건에 제8조 다과·간식이 함께 잡히는 것은 자연스럽다). 제대로 재려면 검색된
  청크마다 관련성 라벨이 필요한데 비용 대비 얻는 정보가 적다 — 대신 '함께 검색된
  조항 수'를 관측치로 출력해 노이즈 추이만 본다.

비용: 케이스당 임베딩 1~2회(+1차 검색 실패 시 재작성 LLM 1회) — 5건 기준 $0.01 미만.
영수증도 프로덕션 노드(intake_receipt)로 얻으므로(#89) **file:// PNG 케이스는 실모드에서
케이스당 Vision 1회가 추가**된다(rule-axis 골든이 그렇다). mock://·미첨부는 추가 비용 0.
절차는 run_eval_real.py와 같다(실행 전 골든 팀 정리 → 회칙 실인덱싱 → 실행 후 정리).

⚠️ #89 이후 질의가 종전 기준선과 다르다: 골든 PNG는 품목=지출 제목 복사라(#87 참조)
질의에 제목이 한 번 더 들어가고 상호도 붙는다 — 프로덕션(v7)과 같아진 것이지만,
아래 "첫 기준선(2/4·62.5%)"과 수치를 직접 비교하면 안 된다. 실키로 재측정해 기준선을
다시 잡아야 한다.

**첫 기준선 (2026-08-12 · RELEVANCE_MAX_DISTANCE=0.65 · top_k=3) (무효 — #89 이전 측정)**: 조항 적중 2/4 ·
조항 단위 평균 62.5% · 대조군 위반 1건. 같은 5건의 **판정은 전부 정답이었다** —
즉 판정 정확도가 검색 품질을 보증하지 않는다는 것이 이 하니스의 첫 산출물이다.
임계값만으로는 분리되지 않는다는 것도 함께 확인했다: 기대 조항의 최대 거리(0.739)와
무관 조항의 최소 거리(0.743)가 0.004밖에 안 떨어져 있다.
"""

import asyncio
import csv
import json
import logging
import re
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

DEFAULT_GOLDEN = ROOT / "eval" / "golden" / "golden_rule_axis.json"
RESULTS_DIR = ROOT / "eval" / "results"
ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조")


def article_numbers(text: str) -> set[str]:
    """텍스트에서 조항 번호만 뽑는다 — '제 3 조'·'제3조' 표기 흔들림을 흡수."""
    return set(ARTICLE_RE.findall(text or ""))


async def main() -> int:
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print("실모드가 아닙니다 — MOCK_LLM=false + OPENAI_API_KEY 필요")
        print("(목 임베딩은 해시 기반이라 검색 품질 측정이 성립하지 않습니다)")
        return 2

    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GOLDEN
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = [c for c in golden["cases"] if c.get("expected_rule_clauses") is not None]
    skipped = len(golden["cases"]) - len(cases)
    if not cases:
        print(f"{golden_path.name}에 expected_rule_clauses 라벨이 없습니다 — 채점 불가")
        return 2

    from app.graphs.indexing.graph import indexing_graph
    from app.graphs.review.nodes.intake_receipt import intake_receipt
    from app.graphs.review.nodes.load_context import load_context
    # 프로덕션 검색 경로를 그대로 호출한다(모듈 docstring 참조) — 재구현 금지.
    from app.graphs.review.nodes.rule_auditor import _retrieve_with_correction

    await open_pool()
    try:
        await apply_schema()
        teams = sorted({c["input"]["organizationId"] for c in cases})
        await clean_golden_teams()
        for t in teams:
            await indexing_graph.ainvoke({"team_id": t, "doc_type": "rule"})
        print(f"골든 팀 {len(teams)}개 회칙 실인덱싱 완료 — 케이스 {len(cases)}건"
              + (f" (라벨 없어 건너뜀 {skipped}건)" if skipped else ""))

        results = []
        for case in cases:
            inp = case["input"]
            ctx = await load_context({
                "job_id": f"retr-{case['id']}",
                "expense_id": inp["expenseId"],
                "team_id": inp["organizationId"],
                "review_goal": inp.get("reviewGoal", ""),
            })
            # 영수증도 프로덕션 노드(intake_receipt)로 얻는다 (#89). rule_auditor v7부터
            # 검색 질의에 증빙의 상호·품목이 들어가는데(#84 _search_text), 하니스가
            # receipt를 안 넘기면 질의가 프로덕션과 갈라진다 — 이 파일 docstring이
            # 금지한 바로 그 상태였다. rule-axis 골든은 file:// PNG라 질의가 실제로
            # 달라진다(모듈 docstring ⚠️ 참조) — 기준선 재측정 필요.
            intake = await intake_receipt({
                "claim": ctx["claim"],
                "receipt_path": inp.get("receiptPath"),
            })
            chunks, grade, _meta = await _retrieve_with_correction(
                inp["organizationId"], ctx["claim"], ctx["rule_version"],
                ctx.get("team_members") or [],
                receipt=intake.get("receipt_data"),
            )
            retrieved: set[str] = set()
            for c in chunks:
                retrieved |= article_numbers(c["text"])
            expected = {n for label in case["expected_rule_clauses"]
                        for n in article_numbers(label)}

            if expected:
                hit = expected & retrieved
                recall = len(hit) / len(expected)
                ok = hit == expected
            else:
                # 대조군 — 조항이 잡혀도 실패로 세지 않는다(모듈 docstring 채점 절 참조).
                # recall은 정의되지 않으므로 None으로 두고 분모에서 뺀다.
                recall = None
                ok = not retrieved
            results.append({
                "id": case["id"], "grade": grade,
                "expected": sorted(expected, key=int), "retrieved": sorted(retrieved, key=int),
                "recall": recall, "ok": ok,
                "extra": sorted(retrieved - expected, key=int),
            })

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = RESULTS_DIR / "retrieval_run.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "grade", "expected_clauses", "retrieved_clauses",
                        "recall", "ok", "extra_clauses"])
            for r in results:
                w.writerow([r["id"], r["grade"],
                            "|".join("제" + n + "조" for n in r["expected"]),
                            "|".join("제" + n + "조" for n in r["retrieved"]),
                            "" if r["recall"] is None else f"{r['recall']:.2f}", r["ok"],
                            "|".join("제" + n + "조" for n in r["extra"])])

        print()
        for r in results:
            mark = "O" if r["ok"] else "X"
            exp = ",".join("제" + n + "조" for n in r["expected"]) or "(없어야 함)"
            got = ",".join("제" + n + "조" for n in r["retrieved"]) or "(없음)"
            print(f" [{mark}] {r['id']:26s} grade={r['grade']:12s} 기대={exp:12s} 검색={got}")

        clause_cases = [r for r in results if r["expected"]]
        control = [r for r in results if not r["expected"]]
        strict = sum(1 for r in clause_cases if r["ok"])
        micro = (sum(r["recall"] for r in clause_cases) / len(clause_cases)
                 if clause_cases else None)
        print()
        if clause_cases:
            print(f"context_recall(전부 적중): {strict}/{len(clause_cases)} "
                  f"= {strict / len(clause_cases):.1%}")
            print(f"context_recall(조항 단위 평균): {micro:.1%}")
        if control:
            c_ok = sum(1 for r in control if r["ok"])
            print(f"대조군(회칙이 다루지 않는 지출): {c_ok}/{len(control)} — 조항 미검색")
        noise = [len(r["extra"]) for r in clause_cases]
        if noise:
            print(f"함께 검색된 기대 외 조항: 평균 {sum(noise) / len(noise):.1f}개 "
                  f"(관측치 — 점수 아님)")
        grades = {}
        for r in results:
            grades[r["grade"]] = grades.get(r["grade"], 0) + 1
        print(f"검색 단계 분포: {grades}")
        print(f"\n결과 CSV: {csv_path}")

        # 판정 기준: 기대 조항을 **하나도** 못 가져온 케이스만 실패로 센다.
        # 부분 적중은 경고 — 어느 조항까지 '필요한 근거'인지는 해석 여지가 있어
        # (예: 해석 충돌 케이스에서 반대편 조항이 꼭 있어야 하는가) 하드 기준으로
        # 삼기 이르다. 대조군 위반도 경고다(위 docstring 채점 절).
        missed = [r for r in clause_cases if r["recall"] == 0.0]
        partial = [r for r in clause_cases if r["recall"] and not r["ok"]]
        if partial:
            print(f"\n경고: 부분 적중 {len(partial)}건 — {[r['id'] for r in partial]}")
        for r in control:
            if not r["ok"]:
                print(f"경고: 대조군 {r['id']} — 회칙이 다루지 않는 지출인데 "
                      f"{','.join('제' + n + '조' for n in r['retrieved'])}가 근거로 들어감")
        if missed:
            print(f"\n실패: 기대 조항을 전혀 못 가져온 케이스 {len(missed)}건 "
                  f"— {[r['id'] for r in missed]}")
            return 1
        print("\n통과")
        return 0
    finally:
        try:
            await clean_golden_teams()
        except Exception:
            logging.exception("골든 팀 데이터 사후 정리 실패 — 수동 정리 필요")
        await close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
