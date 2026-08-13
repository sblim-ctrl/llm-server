"""평가셋을 제출용 CSV로 내보낸다 — 골든 JSON + fixture 조인 (읽기 전용).

**왜 필요한가.** 평가셋의 진실은 `eval/golden/*.json`이지만 두 가지 이유로 그대로는
읽히지 않는다:

1. **케이스와 지출 상세가 떨어져 있다.** 골든 케이스는 `expenseId`만 갖고 실제
   제목·금액·날짜는 `eval/fixtures/mock_backend.json`에 있다(pull 모델 — 서버가
   되물어 조회하는 구조를 평가에서도 그대로 재현하기 위해서다). 팀 예산·승인 기준도
   `organizations`에 따로 있다. 사람이 "이 케이스가 무엇을 묻는가"를 보려면 조인이 필요하다.
2. **JSON 중첩 구조는 표 도구로 못 본다.** 제출·리뷰·통계는 CSV가 편하다.

**원본은 건드리지 않는다.** 이 스크립트는 읽기 전용이고, 산출물은 `eval/published/`에
새로 쓴다(`eval/results/`는 하니스 실행 산출물이라 .gitignore 대상 — 제출물과 섞지 않는다).
골든 JSON·fixture는 소유자 파일이므로 여기서 수정하지 않는다.

실행:  uv run python scripts/export_eval_dataset.py
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GOLDEN_DIR = ROOT / "eval" / "golden"
FIXTURE = ROOT / "eval" / "fixtures" / "mock_backend.json"
RESULTS_DIR = ROOT / "eval" / "results"
OUT_DIR = ROOT / "eval" / "published"

# utf-8-sig: Excel이 BOM 없는 UTF-8 CSV를 cp949로 읽어 한글이 깨진다(#74와 같은 계열).
ENCODING = "utf-8-sig"


def _join(values) -> str:
    """리스트 → 파이프 구분 문자열. CSV 안에서 쉼표와 충돌하지 않게 '|'를 쓴다."""
    return "|".join(str(v) for v in (values or []))


def export_review_golden() -> tuple[Path, int]:
    """심사 평가셋 — 케이스 + 지출 상세 + 팀 설정을 한 행으로."""
    golden = json.loads((GOLDEN_DIR / "golden_v1.json").read_text(encoding="utf-8"))
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expenses, orgs = fx["expenses"], fx["organizations"]

    out = OUT_DIR / "golden_review_v1.csv"
    with out.open("w", newline="", encoding=ENCODING) as f:
        w = csv.writer(f)
        w.writerow([
            "id", "scenario", "team_type", "org_id", "expense_id",
            "title", "amount", "date", "description", "receipt_path",
            "auto_approve", "auto_approve_limit", "total_budget", "spent",
            "expected_verdict", "expected_category", "must_not_approve",
            "expected_gate_includes", "expected_rule_clauses",
        ])
        for c in golden["cases"]:
            inp = c["input"]
            # fixture 키는 문자열·정수가 섞여 있어 둘 다 시도한다
            eid = inp.get("expenseId")
            exp = expenses.get(str(eid)) or expenses.get(eid) or {}
            oid = inp.get("organizationId")
            org = orgs.get(str(oid)) or orgs.get(oid) or {}
            budget = org.get("budget") or {}
            w.writerow([
                c["id"], c.get("scenario", ""), c.get("team_type", ""), oid, eid,
                exp.get("title", ""), exp.get("amount", ""), exp.get("date", ""),
                exp.get("description", ""), inp.get("receiptPath", ""),
                org.get("auto_approve", ""), org.get("auto_approve_limit", ""),
                budget.get("total_budget", ""), budget.get("spent", ""),
                c.get("expected_verdict", ""), c.get("expected_category", ""),
                c.get("must_not_approve", ""),
                _join(c.get("expected_gate_includes")),
                # None(라벨 없음)과 []( 대조군 — "조항이 없어야 정상")은 뜻이 다르다.
                # 빈 문자열로 뭉개면 대조군이 미라벨로 보이므로 구분해 적는다.
                "(미라벨)" if c.get("expected_rule_clauses") is None
                else (_join(c["expected_rule_clauses"]) or "(대조군)"),
            ])
    return out, len(golden["cases"])


def export_writers_golden() -> tuple[Path, int]:
    """라이터 평가셋 — 7종이 각각 다른 키를 써서 공통 열 + 원본 JSON 열로 편다."""
    golden = json.loads((GOLDEN_DIR / "writers_golden_v1.json").read_text(encoding="utf-8"))
    rows = 0
    out = OUT_DIR / "golden_writers_v1.csv"
    with out.open("w", newline="", encoding=ENCODING) as f:
        w = csv.writer(f)
        w.writerow(["writer", "id", "scenario", "team_id", "input_json", "expect_json"])
        for group, cases in golden.items():
            if not group.endswith("_cases"):
                continue
            writer_name = group.removesuffix("_cases")
            for c in cases:
                inp = c.get("input") or {}
                w.writerow([
                    writer_name, c["id"], c.get("scenario", ""),
                    c.get("team_id") or inp.get("team_id", ""),
                    json.dumps(inp, ensure_ascii=False),
                    json.dumps(c.get("expect") or {}, ensure_ascii=False),
                ])
                rows += 1
    return out, rows


def _latest(pattern: str) -> Path | None:
    """`eval/results/`에서 가장 최근 파일 — 실모드 산출물은 날짜가 파일명에 붙는다."""
    hits = sorted(RESULTS_DIR.glob(pattern))
    return hits[-1] if hits else None


def export_run_results() -> list[tuple[Path, int]]:
    """하니스 실행 산출물을 제출용으로 고정 이름 복사 + 실모드 추이 요약 생성.

    `eval/results/`는 .gitignore 대상이라(매 실행 덮어쓰는 작업 폴더) 노트북이 그곳을
    읽으면 **받는 사람이 클론했을 때 실행되지 않는다.** 제출 노트북은 `eval/published/`
    안에서만 읽도록 여기서 고정 이름으로 복사한다.
    """
    made: list[tuple[Path, int]] = []
    sources = {
        "results_review_realmode.csv": _latest("golden_realmode_20*.csv"),
        "results_review_mock.csv": RESULTS_DIR / "golden_run.csv",
        "results_retrieval.csv": RESULTS_DIR / "retrieval_run.csv",
        "results_writers.csv": RESULTS_DIR / "writers_golden_run.csv",
        "results_judge.csv": RESULTS_DIR / "judge_run.csv",
    }
    for name, src in sources.items():
        if not src or not src.exists():
            print(f"  (건너뜀: {name} — 원본 없음)")
            continue
        dst = OUT_DIR / name
        rows = src.read_text(encoding="utf-8-sig").splitlines()
        dst.write_text("\n".join(rows) + "\n", encoding=ENCODING)
        made.append((dst, max(len(rows) - 1, 0)))

    # 실모드 추이 — 날짜별 CSV들에서 규모·정확도·오승인·비용만 뽑아 한 표로.
    # 원본 파일 전부를 제출물에 넣으면 프롬프트 실험본까지 섞여 읽기 어렵다.
    hist = OUT_DIR / "history_review_realmode.csv"
    runs = sorted(RESULTS_DIR.glob("golden_realmode_20*.csv"))
    with hist.open("w", newline="", encoding=ENCODING) as f:
        w = csv.writer(f)
        w.writerow(["run_date", "cases", "accuracy", "false_approves", "total_cost_usd"])
        for src in runs:
            rows = list(csv.DictReader(src.read_text(encoding="utf-8-sig").splitlines()))
            if not rows:
                continue
            n = len(rows)
            ok = sum(1 for r in rows if str(r.get("correct", "")).lower() == "true")
            fa = sum(1 for r in rows if str(r.get("false_approve", "")).lower() == "true")
            cost = sum(float(r.get("cost_usd") or 0) for r in rows)
            w.writerow([src.stem.replace("golden_realmode_", ""), n,
                        f"{ok / n:.4f}", fa, f"{cost:.4f}"])
    made.append((hist, len(runs)))
    return made


def export_submission_single() -> tuple[Path, int]:
    """제출용 단일 CSV — 케이스 정의 + 실행 결과를 id로 조인해 한 파일로 만든다.

    제출 요건이 "평가셋 CSV 1개 + 노트북 1개"라 파일을 갈라 두면 채점자가 둘을 맞춰
    봐야 한다. 한 장에 **무엇을 시험했고(정의) 어떻게 나왔는지(결과)**가 함께 있으면
    그 파일만으로 평가 전체를 읽을 수 있다. 조인 키는 케이스 id.

    라이터 평가셋(32건)은 열 구조가 전혀 달라(생성물 기대값 JSON) 여기 섞지 않는다 —
    섞으면 행의 절반이 빈 칸이 된다. 저장소의 golden_writers_v1.csv로 따로 둔다.
    """
    ds = OUT_DIR / "golden_review_v1.csv"
    rs = OUT_DIR / "results_review_realmode.csv"
    if not (ds.exists() and rs.exists()):
        raise SystemExit("golden_review_v1.csv·results_review_realmode.csv가 먼저 필요합니다")

    with rs.open(encoding="utf-8-sig") as f:
        # 결과 쪽 expected_category·expected는 정의 쪽과 중복이라 결과 고유 열만 가져온다
        res = {r["id"]: r for r in csv.DictReader(f)}
    keep = ["actual", "correct", "false_approve", "gate", "cost_usd", "actual_category"]

    with ds.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = list(reader.fieldnames or [])

    out = OUT_DIR / "budgetops_eval_set.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols + keep)
        w.writeheader()
        for r in rows:
            hit = res.get(r["id"], {})
            w.writerow({**r, **{k: hit.get(k, "") for k in keep}})
    return out, len(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, n in (export_review_golden(), export_writers_golden()):
        print(f"{path.relative_to(ROOT)} — {n}건")
    print("실행 산출물:")
    for path, n in export_run_results():
        print(f"  {path.relative_to(ROOT)} — {n}행")
    sub, n = export_submission_single()
    print(f"제출용 단일본: {sub.relative_to(ROOT)} — {n}건 (정의 + 결과 조인)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
