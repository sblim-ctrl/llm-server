"""골든셋 평가 로직 — CLI(eval/run_eval.py)와 대시보드 API(app/api/eval.py)가 공유.

app 패키지 안에 둬야 Docker 이미지에도 포함되고, /ui 대시보드에서도 import 가능하다.
"""

import csv
import json
from pathlib import Path
from typing import Any

from app.eval_metrics import verdict_metrics
from app.graphs.review.graph import review_graph
from app.schemas.analyze import AnalyzeRequest

ACCURACY_THRESHOLD = 0.90
DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden" / "golden_v1.json"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"
VERDICT_LABELS = {"approve": "승인", "reject": "반려", "escalate": "보류"}


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
    gate = final_state.get("gate_result").triggered_rules if final_state.get("gate_result") else []
    # 영수증 불일치는 mismatch_gate에서 가드레일 전에 escalate로 직행한다 (§4.1) —
    # 그 경로도 trajectory로 기록 (실제 상태의 mismatch 리스트에서 도출)
    if not gate and final_state.get("mismatch"):
        gate = ["receipt_mismatch"]

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

    return {
        "id": case["id"],
        "scenario": case.get("scenario", ""),
        "expected": expected,
        "actual": actual,
        "correct": actual == expected,
        "false_approve": bool(case.get("must_not_approve")) and actual == "approve",
        "gate": gate,
        "expected_gate": expected_gate or [],
        "trajectory_ok": trajectory_ok,
        "expected_category": expected_category,
        "actual_category": actual_category,
        # 기대값 없는 케이스는 채점 대상에서 제외(None) — 0점으로 깎지 않는다
        "category_ok": (actual_category == expected_category) if expected_category else None,
    }


async def run_golden_set(golden_path: Path | None = None) -> dict[str, Any]:
    golden_path = golden_path or DEFAULT_GOLDEN_PATH
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]

    results = [await run_case(c) for c in cases]
    correct = sum(r["correct"] for r in results)
    false_approves = [r for r in results if r["false_approve"]]
    accuracy = correct / len(results) if results else 0.0

    traj_cases = [r for r in results if r["trajectory_ok"] is not None]
    traj_correct = sum(1 for r in traj_cases if r["trajectory_ok"])

    # 분류 정확도 — 기대값이 있는 케이스만 분모에 넣는다.
    # **하드 게이트가 아니다.** 목 모드 분류는 키워드 규칙이라(실LLM 미호출) 여기 숫자는
    # "키워드 규칙의 정확도"이지 실서비스 품질이 아니다. 게이트로 만들면 실모드에서만
    # 나올 개선을 목 숫자로 막게 된다 — 임계값은 실모드 측정 후에 정한다.
    cat_cases = [r for r in results if r["category_ok"] is not None]
    cat_correct = sum(1 for r in cat_cases if r["category_ok"])
    cat_misses = [
        {"id": r["id"], "expected": r["expected_category"], "actual": r["actual_category"]}
        for r in cat_cases
        if not r["category_ok"]
    ]

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
        # 분류 정확도 (관측 지표 — passed에 반영하지 않는다, 위 주석 참조)
        "category_total": len(cat_cases),
        "category_correct": cat_correct,
        "category_accuracy": (cat_correct / len(cat_cases)) if cat_cases else None,
        "category_misses": cat_misses,
        # §4 Sprint 2 — 판정 분포·에스컬레이션 P/R·자동 처리율 (순수 함수 계산)
        "metrics": verdict_metrics(results),
        "passed": not false_approves and accuracy >= ACCURACY_THRESHOLD,
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
                ]
            )
    return path
