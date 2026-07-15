"""콜백 페이로드 — camelCase 직렬화 + suggestedCategory 매핑 (bravo_API명세서 정합)."""
from app.graphs.review.nodes.callback import build_callback_payload
from app.schemas.common import ExpenseClaim


def _state(category: str = "식비") -> dict:
    return {
        "job_id": "job-1", "expense_id": "exp-1", "team_id": "team-1",
        "verdict": "approve", "confidence": 0.95,
        "opinions": {}, "mismatch": [], "reasons": None,
        "claim": ExpenseClaim(title="회식", amount=30000, category=category, date="2026-07-15"),
    }


def test_suggested_category_from_claim():
    payload = build_callback_payload(_state("식비"))
    assert payload.suggested_category == "식비"


def test_empty_category_maps_to_none():
    payload = build_callback_payload(_state(""))
    assert payload.suggested_category is None


def test_by_alias_dump_is_camel_case():
    payload = build_callback_payload(_state())
    dumped = payload.model_dump(mode="json", by_alias=True)
    assert "expenseId" in dumped and "expense_id" not in dumped
    assert "suggestedCategory" in dumped
    assert "processedBy" in dumped and dumped["processedBy"] == "AI"


def test_by_name_construction_still_works():
    """populate_by_name=True — 내부 코드는 snake_case 키워드 인자로 그대로 생성 가능."""
    payload = build_callback_payload(_state())
    assert payload.expense_id == "exp-1"
