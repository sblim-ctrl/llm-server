"""골든셋 평가 로직 — CLI(eval/run_eval.py)와 대시보드 API(app/api/eval.py)가 공유.

app 패키지 안에 둬야 Docker 이미지에도 포함되고, /ui 대시보드에서도 import 가능하다.
"""
import json
from pathlib import Path
from typing import Any

from app.graphs.review.graph import review_graph
from app.schemas.analyze import AnalyzeRequest

ACCURACY_THRESHOLD = 0.90
DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden" / "golden_v1.json"
VERDICT_LABELS = {"approve": "승인", "reject": "반려", "escalate": "보류"}


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    req = AnalyzeRequest.model_validate(case["input"])
    final_state = await review_graph.ainvoke({
        "job_id": f"eval-{case['id']}",
        "expense_id": req.expense_id,
        "team_id": req.team_id,
        "claim": req.claim,
        "receipt_url": req.receipt_signed_url,
    })
    actual = final_state.get("verdict") or "escalate"
    expected = case["expected_verdict"]
    return {
        "id": case["id"],
        "scenario": case.get("scenario", ""),
        "expected": expected,
        "actual": actual,
        "correct": actual == expected,
        "false_approve": bool(case.get("must_not_approve")) and actual == "approve",
        "gate": (final_state.get("gate_result").triggered_rules
                 if final_state.get("gate_result") else []),
    }


async def run_golden_set(golden_path: Path | None = None) -> dict[str, Any]:
    golden_path = golden_path or DEFAULT_GOLDEN_PATH
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = golden["cases"]

    results = [await run_case(c) for c in cases]
    correct = sum(r["correct"] for r in results)
    false_approves = [r for r in results if r["false_approve"]]
    accuracy = correct / len(results) if results else 0.0

    return {
        "version": golden["version"],
        "total": len(results),
        "correct": correct,
        "accuracy": accuracy,
        "accuracy_threshold": ACCURACY_THRESHOLD,
        "false_approve_count": len(false_approves),
        "false_approve_ids": [r["id"] for r in false_approves],
        "passed": not false_approves and accuracy >= ACCURACY_THRESHOLD,
        "results": results,
    }
