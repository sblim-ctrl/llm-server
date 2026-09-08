"""골든셋 v2 결정적 생성기 — 7유형 원안 + receipt_mismatch(8번째, Phase 0 커버리지 갭 보강)
× 약 100건 = 800건. 기대값은 scripts/golden_v2/engine.py로 코드 유도(회칙 충돌·판례
유사검색 축은 실모드 전용이라 사람이 판단해 적음 — 모듈 docstring 참조).

실행: uv run python scripts/generate_golden_v2.py
출력:
  eval/golden/golden_v2/{type}.json  — 유형별 케이스 파일 8개
  eval/fixtures/mock_backend.json    — org 9100번대·expense 91000번대 append(v1 보존)

주의: eval/golden/golden_v1.json은 절대 건드리지 않는다(사용자 지시).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # eval/run_eval.py와 같은 관례 — 직접 스크립트 실행 시 필요

from scripts.golden_v2 import (  # noqa: E402
    gen_boundary,
    gen_circumvention,
    gen_clear_approve,
    gen_clear_reject,
    gen_missing_info,
    gen_notation_variant,
    gen_receipt_mismatch,
    gen_rule_conflict,
)
from scripts.golden_v2.fixtures import FixtureRegistry  # noqa: E402

GOLDEN_V2_DIR = ROOT / "eval" / "golden" / "golden_v2"
FIXTURE_PATH = ROOT / "eval" / "fixtures" / "mock_backend.json"

GENERATORS = [
    gen_clear_approve,
    gen_clear_reject,
    gen_boundary,
    gen_missing_info,
    gen_receipt_mismatch,
    gen_notation_variant,
    gen_rule_conflict,
    gen_circumvention,
]

TYPE_DESCRIPTIONS = {
    "clear_approve": "명백 승인 — 한도 내·영수증 일치·예산 충분",
    "clear_reject": "명백 반려 — 예산 잔액 명백 부족(단독 및 금액 임계값과의 조합)",
    "boundary": "경계선 — 금액·예산 임계값의 '>=' 경계",
    "missing_info": "정보/판정 권한 부족 — 영수증 미첨부 또는 auto_approve_disabled",
    "receipt_mismatch": "영수증 불일치 (8번째, Phase 0 유형 커버리지 갭 보강)",
    "notation_variant": "표기 변형 — 영문·외래어·오타로 같은 항목을 표기(분류 축 목/실 대조)",
    "rule_conflict": "회칙 충돌 — 두 조항이 다른 한도를 말함(실모드 전용)",
    "circumvention": "우회 시도 — 분할 결제·동일 건 재청구(판례 유사검색 축 실모드 전용)",
}


def main() -> None:
    reg = FixtureRegistry()
    GOLDEN_V2_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for module in GENERATORS:
        cases = module.generate(reg)
        type_key = module.TYPE
        out_path = GOLDEN_V2_DIR / f"{type_key}.json"
        payload = {
            "version": "v2",
            "type": type_key,
            "description": TYPE_DESCRIPTIONS[type_key],
            "cases": cases,
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{type_key:20s} {len(cases):4d}건 → {out_path.relative_to(ROOT)}")
        total += len(cases)

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    before_orgs = len(fixture["organizations"])
    before_expenses = len(fixture["expenses"])

    fixture["organizations"].update(reg.organizations)
    fixture["expenses"].update(reg.expenses)
    fixture["expense_histories"].update(reg.expense_histories)
    if reg.policy_documents:
        fixture.setdefault("policy_documents", {}).update(reg.policy_documents)

    FIXTURE_PATH.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n총 {total}건 생성")
    print(
        f"픽스처: organizations {before_orgs} → {len(fixture['organizations'])} "
        f"(+{len(reg.organizations)}), expenses {before_expenses} → {len(fixture['expenses'])} "
        f"(+{len(reg.expenses)}), policy_documents +{len(reg.policy_documents)}"
    )


if __name__ == "__main__":
    main()
