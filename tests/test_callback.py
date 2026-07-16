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


def test_external_job_id_is_echoed():
    """pull 모델 — 백엔드 발급 jobId를 echo해야 expenses.ai_job_id 대조를 통과한다."""
    state = _state()
    state["external_job_id"] = "be-issued-42"
    assert build_callback_payload(state).job_id == "be-issued-42"


def test_internal_job_id_fallback_without_external():
    """직접 그래프 호출(external 없음) — 내부 job_id로 fallback."""
    assert build_callback_payload(_state()).job_id == "job-1"


# ── llm_meta 실측치 반영 (B2→B4) ─────────────────────────


def test_meta_fields_default_when_adjudicate_skipped():
    """escalate 직행 경로(가드레일 차단 등) — llm_meta에 adjudicator 없음 → 기본값, 크래시 금지."""
    payload = build_callback_payload(_state())
    assert payload.model_version == "mock"
    assert payload.prompt_version == "review/v1"
    assert payload.cost_usd == 0.0


def test_meta_fields_filled_from_llm_meta():
    from app.schemas.common import LLMCallMeta
    state = _state()
    state["llm_meta"] = {
        "classifier": LLMCallMeta(model="gpt-4o-mini", cost_usd=0.001),
        "adjudicator": LLMCallMeta(model="gpt-4o", prompt_version="adjudicator/v1",
                                   cost_usd=0.002),
    }
    state["started_at"] = 100.0  # time.time() 대비 과거 → latency_ms > 0
    payload = build_callback_payload(state)
    assert payload.model_version == "gpt-4o"
    assert payload.prompt_version == "adjudicator/v1"
    assert payload.cost_usd == 0.003  # 전체 호출 합산
    assert payload.latency_ms > 0
