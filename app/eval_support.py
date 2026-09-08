"""골든셋 평가 로직 — CLI(eval/run_eval.py)와 대시보드 API(app/api/eval.py)가 공유.

app 패키지 안에 둬야 Docker 이미지에도 포함되고, /ui 대시보드에서도 import 가능하다.
"""

import csv
import json
import re
from pathlib import Path
from typing import Any

from app.api.jobs import translate_result_terms
from app.eval_metrics import category_metrics, score_category, verdict_metrics
from app.graphs.review.graph import review_graph
from app.graphs.review.nodes.callback import build_callback_payload
from app.schemas.analyze import AnalyzeRequest
from app.schemas.callback import CallbackPayload

ACCURACY_THRESHOLD = 0.90
DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden" / "golden_v1.json"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"
VERDICT_LABELS = {"approve": "승인", "reject": "반려", "escalate": "보류"}

# 사용자 노출 문구(콜백 reasons·opinions)에 섞이면 안 되는 내부 표기 — 관리자를
# "admin"으로 지칭하는 등 일반 사용자가 이해하기 어려운 표현을 막기 위한 회귀 그물
# (2026-08-11). ADMIN/AGENT/override는 판례 인용 시스템 표기가 few_shot을 통해
# 그대로 복제되던 결함, 나머지는 mock 문구·수치 키 이름이 새던 자리다.
BANNED_USER_FACING_PATTERNS: dict[str, re.Pattern[str]] = {
    "mock_suffix": re.compile(r"\(mock\)"),
    "override": re.compile(r"\boverride\b", re.IGNORECASE),
    "admin_tag": re.compile(r"\bADMIN\b"),
    "agent_tag": re.compile(r"\bAGENT\b"),
    "fail_safe": re.compile(r"\bfail-safe\b", re.IGNORECASE),
    "admin_approve_support": re.compile(r"\badmin_approve_support\b"),
    "total_budget_key": re.compile(r"\btotal_budget\b"),
    "remaining_after_key": re.compile(r"\bremaining_after\b"),
}


def scan_banned_terms(*texts: str | None) -> list[str]:
    """사용자 노출 문자열에서 금지 용어를 찾는다 (순수 함수) — 위반 없으면 빈 리스트."""
    hits: list[str] = []
    for text in texts:
        if not text:
            continue
        for name, pattern in BANNED_USER_FACING_PATTERNS.items():
            if pattern.search(text):
                hits.append(f"{name} in {text!r}")
    return hits


def scan_callback_payload_terms(payload: CallbackPayload) -> list[str]:
    """콜백 페이로드의 사용자 노출 텍스트(reasons·opinions) 전량 스캔."""
    texts: list[str] = []
    if payload.reasons:
        texts += [payload.reasons.requester, payload.reasons.admin]
    for op in payload.opinions:
        texts.append(op.summary)
        texts.extend(op.similar_cases)
    return scan_banned_terms(*texts)


def gate_rules_from_state(final_state: dict[str, Any]) -> list[str]:
    """심사 최종 상태 → Trajectory 채점용 가드레일 규칙 목록 (순수 함수).

    영수증 불일치는 `mismatch_gate`가 `guardrail_gate` **앞에서** escalate로 직행시키므로
    `gate_result`가 아예 없다 (§4.1). 그 경로도 궤적으로 남겨야 "왜 막혔는가"를 채점할 수
    있어 `mismatch` 리스트에서 도출한다.

    **로컬 CSV 하니스와 LangSmith Experiment가 같은 규칙을 봐야 해서 함수로 뽑았다.**
    이 보정이 `run_case`에만 있고 `eval/run_eval_langsmith.py`의 target에는 없던 동안,
    LangSmith `gate_includes_hit`이 영수증 불일치 케이스 8건을 계속 미달로 셌다
    (2026-08-11 실측 42/50 = 84%, 2회 연속 동일). 그 8건은 **판정이 모두 정답**이었으므로
    시스템 결함이 아니라 채점 하니스 결함이었다 — 같은 규칙이 두 벌로 있으면 이렇게
    조용히 갈라진다.
    """
    gate_result = final_state.get("gate_result")
    gate = list(gate_result.triggered_rules) if gate_result else []
    if not gate and final_state.get("mismatch"):
        return ["receipt_mismatch"]
    return gate


def scan_job_result_terms(result: Any) -> list[str]:
    """폴링 응답(`GET /v1/jobs/{job_id}`의 `result`) 사용자 노출 텍스트 스캔.

    콜백과 같은 심사 결과인데 **출구가 다르다** — 콜백만 검사하면 폴링 안전망
    (§7.1)으로 나가는 문구는 게이트 밖에 남는다(#71). dict가 아니거나 심사 잡이
    아니면(예: `dead`의 `{"error", "message"}`) 검사할 대상이 없어 빈 목록이다.
    """
    if not isinstance(result, dict):
        return []
    texts: list[str] = []
    reasons = result.get("reasons")
    if isinstance(reasons, dict):
        texts += [str(reasons.get("requester") or ""), str(reasons.get("admin") or "")]
    for op in result.get("opinions") or []:
        if not isinstance(op, dict):
            continue
        texts.append(str(op.get("summary") or ""))
        texts += [str(c) for c in (op.get("similar_cases") or [])]
    return scan_banned_terms(*texts)


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    # pull 모델 — 워커(run_review_job)와 같은 초기 상태로 실행. 지출 상세는
    # load_context가 expense_id로 eval/fixtures/mock_backend.json을 되물어 채운다(T9).
    req = AnalyzeRequest.model_validate(case["input"])
    final_state = await review_graph.ainvoke(
        {
            "job_id": f"eval-{case['id']}",
            "external_job_id": req.job_id,
            "expense_id": req.expense_id,
            "team_id": req.organization_id,
            "review_goal": req.review_goal,
            "receipt_path": req.receipt_path,
        }
    )
    actual = final_state.get("verdict") or "escalate"
    expected = case["expected_verdict"]
    gate = gate_rules_from_state(final_state)

    # Trajectory 검사: 기대한 가드레일 규칙이 실제로 발동했는가 (가이드 'Trajectory 평가'의 로컬 버전)
    expected_gate = case.get("expected_gate_includes")
    trajectory_ok = (
        all(rule in gate for rule in expected_gate) if expected_gate is not None else None
    )

    # 분류 채점 — 사람이 매긴 정답(expected_category) 대비 AI가 확정한 카테고리.
    # T7 이후 카테고리는 AI가 유일하게 정하므로(들어온 값은 덮인다) 골든셋의 category를
    # 입력이 아니라 기대값으로 옮겼고(2026-08-06), 여기서 그것과 대조한다.
    # **판정 정확도와는 독립된 지표다** — 오분류가 판정을 바꾸지는 않지만 카테고리별
    # 예산 집계·통계를 조용히 오염시키므로 따로 본다.
    claim = final_state.get("claim")
    actual_category = claim.category if claim else None
    expected_category = case.get("expected_category")

    # 콜백으로 나가는 그대로 스캔 — 이 함수가 조립해 시뮬레이션한 문구가 아니라
    # 실제 발송 페이로드(callback.py build_callback_payload)를 대상으로 해야
    # "테스트만 통과하고 실제로는 새는" 괴리가 생기지 않는다.
    term_violations = scan_callback_payload_terms(build_callback_payload(final_state))
    # 폴링 출구(§7.1)도 같은 게이트에 넣는다 (#71·#73). worker.py의 결과 조립부는
    # 소유 경계상 이 PR에서 함수로 빼지 않아, 스캐너가 읽는 reasons·opinions 두 키만
    # worker와 같은 직렬화(model_dump)로 재현하고 read_job이 적용하는 치환
    # (translate_result_terms)까지 태워 "폴링 응답으로 나가는 그대로"를 스캔한다.
    # 엔드포인트가 실제로 치환을 부르는지는 test_polling_terms.py가 배선 테스트로
    # 보증하고, 여기는 치환을 거친 뒤에도 금지 용어가 남는 케이스를 골든셋 전량으로
    # 잡는 그물이다.
    reasons = final_state.get("reasons")
    polled_result = translate_result_terms(
        {
            "reasons": reasons.model_dump() if reasons else None,
            "opinions": [o.model_dump() for o in final_state.get("opinions", {}).values()],
        }
    )
    term_violations += scan_job_result_terms(polled_result)

    return {
        "id": case["id"],
        "scenario": case.get("scenario", ""),
        # v2 골든셋 전용(§Phase 4 유형별 집계) — v1 케이스는 키가 없어 None. 기존 컬럼은
        # 그대로라 export_results_csv·run_golden_set 등 기존 소비자는 영향받지 않는다.
        "type": case.get("type"),
        "expected": expected,
        "actual": actual,
        "correct": actual == expected,
        "false_approve": bool(case.get("must_not_approve")) and actual == "approve",
        "gate": gate,
        "expected_gate": expected_gate or [],
        "trajectory_ok": trajectory_ok,
        "expected_category": expected_category,
        "actual_category": actual_category,
        "category_ok": score_category(actual_category, expected_category),
        "term_violations": term_violations,
    }


async def run_golden_set(golden_path: Path | None = None) -> dict[str, Any]:
    golden_path = golden_path or DEFAULT_GOLDEN_PATH
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]

    results = [await run_case(c) for c in cases]
    correct = sum(r["correct"] for r in results)
    false_approves = [r for r in results if r["false_approve"]]
    term_violation_cases = [r for r in results if r["term_violations"]]
    accuracy = correct / len(results) if results else 0.0

    traj_cases = [r for r in results if r["trajectory_ok"] is not None]
    traj_correct = sum(1 for r in traj_cases if r["trajectory_ok"])

    # 분류 정확도는 `category_metrics`(순수 함수)가 센다 — 게이트가 아닌 이유는 그쪽
    # docstring에 있다.
    #
    # **남은 오분류 9건은 부분 문자열 매칭의 구조적 한계다** (2026-08-06 전수 판정).
    # 어휘를 더 넣어 고칠 수 있는 것은 이미 고쳤고(동아리방·티셔츠·강습), 아래는 카탈로그
    # 순서를 바꾸거나 키워드를 빼야 하는데 둘 다 더 큰 오탐을 만든다:
    #   · 수식어가 본체를 가로챈다 — "워크숍 숙박비"→회의, "지방 출장 숙박비"→교통,
    #     "정기모임 여행 경비"→회의 ('워크숍'·'출장'·'정기모임'을 빼면 진짜 그 지출을 놓친다)
    #   · 앞선 카테고리가 이긴다 — "행사용 물품"→행사_활동(비품이 아래), "온라인 강의
    #     구독"→IT_인프라(교육이 아래) (순서를 바꾸면 다른 축이 깨진다)
    #   · 상호·장소 낱말이 끌어간다 — "보드게임 카페"→식비 ('카페'를 빼면 진짜 카페 지출을 놓친다)
    #   · 어휘 자체가 모호하다 — "부서 소모임 비용"→기타 (사람도 제목만으론 애매)
    # 전부 **문맥을 읽는 실모드 LLM이 맞히는 영역**이다. 키워드는 폴백이라는 점을 기억할 것.
    summary = {
        "version": golden["version"],
        "total": len(results),
        "correct": correct,
        "accuracy": accuracy,
        "accuracy_threshold": ACCURACY_THRESHOLD,
        "false_approve_count": len(false_approves),
        "false_approve_ids": [r["id"] for r in false_approves],
        "trajectory_total": len(traj_cases),
        "trajectory_correct": traj_correct,
        "trajectory_accuracy": (traj_correct / len(traj_cases)) if traj_cases else None,
        # 분류 정확도 (관측 지표 — passed에 반영하지 않는다)
        **category_metrics(results),
        # §4 Sprint 2 — 판정 분포·에스컬레이션 P/R·자동 처리율 (순수 함수 계산)
        "metrics": verdict_metrics(results),
        # 사용자 노출 문구 금지 용어 위반 — false_approve와 같은 급의 하드 게이트
        # (2026-08-11, admin/override 등 비직관 용어 노출 방지)
        "term_violation_count": len(term_violation_cases),
        "term_violation_ids": [r["id"] for r in term_violation_cases],
        "passed": (
            not false_approves and not term_violation_cases and accuracy >= ACCURACY_THRESHOLD
        ),
        "results": results,
    }
    summary["csv_path"] = str(export_results_csv(results))
    return summary


def export_results_csv(results: list[dict[str, Any]]) -> Path:
    """평가 결과 CSV — 가이드 제출 체크리스트('평가셋 CSV') 대응. 매 실행 시 덮어씀."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "golden_run.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM — 엑셀 한글 호환
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "scenario",
                "expected",
                "actual",
                "correct",
                "false_approve",
                "expected_gate",
                "actual_gate",
                "trajectory_ok",
                "expected_category",
                "actual_category",
                "category_ok",
                "term_violations",
                "type",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r["id"],
                    r["scenario"],
                    r["expected"],
                    r["actual"],
                    r["correct"],
                    r["false_approve"],
                    "|".join(r["expected_gate"]),
                    "|".join(r["gate"]),
                    "" if r["trajectory_ok"] is None else r["trajectory_ok"],
                    r["expected_category"] or "",
                    r["actual_category"] or "",
                    "" if r["category_ok"] is None else r["category_ok"],
                    "|".join(r["term_violations"]),
                    r.get("type") or "",
                ]
            )
    return path


async def run_typed_golden_set(golden_paths: list[Path]) -> dict[str, Any]:
    """여러 골든 파일(golden_v2/{type}.json 등)을 합쳐 실행하고 유형별로 집계한다.

    run_golden_set()과 별도 함수로 둔 이유: run_golden_set은 단일 파일 + 기존 summary
    모양(대시보드 GET /v1/eval/golden 공유)을 그대로 유지해야 하고, 이 함수는 여러 파일을
    합쳐 "유형별" 지표(§Phase 4)를 추가로 내야 해서 반환 모양 자체가 다르다 — 시그니처를
    바꾸기보다 나란히 두는 편이 기존 소비자(대시보드·run_eval.py)에 안전하다.
    """
    cases: list[dict[str, Any]] = []
    for path in golden_paths:
        cases.extend(json.loads(path.read_text(encoding="utf-8"))["cases"])

    results = [await run_case(c) for c in cases]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_type.setdefault(r["type"] or "unknown", []).append(r)

    type_summaries: dict[str, Any] = {}
    for type_key, type_results in sorted(by_type.items()):
        correct = sum(r["correct"] for r in type_results)
        false_approves = [r for r in type_results if r["false_approve"]]
        vm = verdict_metrics(type_results)
        type_summaries[type_key] = {
            "n": len(type_results),
            "correct": correct,
            "accuracy": correct / len(type_results) if type_results else 0.0,
            "false_approve_count": len(false_approves),
            "false_approve_ids": [r["id"] for r in false_approves],
            "escalation_recall": vm["escalation_recall"],
            "escalation_precision": vm["escalation_precision"],
            **category_metrics(type_results),
        }

    correct_total = sum(r["correct"] for r in results)
    false_approves_total = [r for r in results if r["false_approve"]]
    term_violation_cases = [r for r in results if r["term_violations"]]

    return {
        "total": len(results),
        "correct": correct_total,
        "accuracy": (correct_total / len(results)) if results else 0.0,
        "false_approve_count": len(false_approves_total),
        "false_approve_ids": [r["id"] for r in false_approves_total],
        "term_violation_count": len(term_violation_cases),
        "term_violation_ids": [r["id"] for r in term_violation_cases],
        "by_type": type_summaries,
        "results": results,
        "csv_path": str(export_results_csv(results)),
    }
