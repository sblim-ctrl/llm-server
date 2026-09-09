"""골든 v2 케이스 딕셔너리 빌더 — eval/golden/golden_v1.json과 같은 필드 모양 + v2 신규
필드(type/difficulty/mode_required)를 더한다.

신규 필드:
  type          7종 원안 + receipt_mismatch(8번째, Phase 0 유형 커버리지 갭 보강) 중 하나.
  difficulty    easy | medium | hard.
  mode_required mock(목 모드로 충분) | real(회칙 실인덱싱·판례 실검색이 있어야 의미 있음).
"""

from typing import Any


def build_case(
    *,
    case_id: str,
    scenario: str,
    team_type: str,
    case_type: str,
    difficulty: str,
    mode_required: str,
    organization_id: int,
    expense_id: int,
    receipt_path: str | None,
    expected_verdict: str,
    expected_category: str,
    expected_gate_includes: list[str] | None = None,
    expected_rule_clauses: list[str] | None = None,
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": case_id,
        "scenario": scenario,
        "team_type": team_type,
        "type": case_type,
        "difficulty": difficulty,
        "mode_required": mode_required,
        "input": {
            "jobId": f"job-{case_id}",
            "expenseId": expense_id,
            "organizationId": organization_id,
            "reviewGoal": "회칙·예산·판례에 근거해 이 지출의 승인 여부를 심사하라",
            "receiptPath": receipt_path,
        },
        "expected_verdict": expected_verdict,
        "expected_category": expected_category,
        "must_not_approve": expected_verdict != "approve",
    }
    if expected_gate_includes is not None:
        case["expected_gate_includes"] = expected_gate_includes
    if expected_rule_clauses is not None:
        case["expected_rule_clauses"] = expected_rule_clauses
    return case
