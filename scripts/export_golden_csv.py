"""골든셋(golden_v1.json) → CSV 변환 — 제출용 평가셋 CSV 생성.

사용: uv run python scripts/export_golden_csv.py
출력: eval/golden/golden_v1.csv (엑셀 한글 호환 BOM)
"""

import csv
import json
from pathlib import Path

SRC = Path("eval/golden/golden_v1.json")
DST = Path("eval/golden/golden_v1.csv")

COLUMNS = [
    "id",
    "scenario",
    "team_type",
    "expenseId",
    "expected_verdict",
    "expected_category",
    "must_not_approve",
    "expected_rule_clauses",
    "receiptPath",
]


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = []
    for case in data["cases"]:
        inp = case.get("input", {})
        rows.append(
            {
                "id": case.get("id", ""),
                "scenario": case.get("scenario", ""),
                "team_type": case.get("team_type", ""),
                "expenseId": inp.get("expenseId", ""),
                "expected_verdict": case.get("expected_verdict", ""),
                "expected_category": case.get("expected_category", ""),
                "must_not_approve": case.get("must_not_approve", ""),
                "expected_rule_clauses": "; ".join(case.get("expected_rule_clauses", []) or []),
                "receiptPath": inp.get("receiptPath", ""),
            }
        )
    with DST.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {DST}")


if __name__ == "__main__":
    main()
