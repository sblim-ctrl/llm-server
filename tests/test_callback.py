"""콜백 페이로드 — camelCase 직렬화 + suggestedCategory 매핑 (bravo_API명세서 정합)."""
from app.graphs.review.nodes.callback import build_callback_payload, trace_meta
from app.schemas.common import ExpenseClaim


def _state(category: str = "식비") -> dict:
    return {
        "job_id": "job-1", "expense_id": 101, "team_id": 11,
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
    assert payload.expense_id == 101


def test_external_job_id_is_echoed():
    """pull 모델 — 백엔드 발급 jobId를 echo해야 expenses.ai_job_id 대조를 통과한다."""
    state = _state()
    state["external_job_id"] = "be-issued-42"
    assert build_callback_payload(state).job_id == "be-issued-42"


def test_internal_job_id_fallback_without_external():
    """직접 그래프 호출(external 없음) — 내부 job_id로 fallback."""
    assert build_callback_payload(_state()).job_id == "job-1"


# ── llm_meta 실측치 (B2→B4) ─────────────────────────
# 2026-08-03부터 콜백이 아니라 jobs.result에 실린다 (화면_대조_2026-08-03 §4) —
# 계산 자체는 trace_meta가 그대로 하므로 검증 대상을 그쪽으로 옮겼다.


def test_trace_meta_defaults_when_adjudicate_skipped():
    """escalate 직행 경로(가드레일 차단 등) — llm_meta에 adjudicator 없음 → 기본값, 크래시 금지."""
    meta = trace_meta(_state())
    assert meta["model_version"] == "mock"
    assert meta["prompt_version"] == "review/v1"
    assert meta["cost_usd"] == 0.0


def test_trace_meta_filled_from_llm_meta():
    from app.schemas.common import LLMCallMeta
    state = _state()
    state["llm_meta"] = {
        "classifier": LLMCallMeta(model="gpt-4o-mini", cost_usd=0.001),
        "adjudicator": LLMCallMeta(model="gpt-4o", prompt_version="adjudicator/v1",
                                   cost_usd=0.002),
    }
    state["started_at"] = 100.0  # time.time() 대비 과거 → latency_ms > 0
    meta = trace_meta(state)
    assert meta["model_version"] == "gpt-4o"
    assert meta["prompt_version"] == "adjudicator/v1"
    assert meta["cost_usd"] == 0.003  # 전체 호출 합산
    assert meta["latency_ms"] > 0


def test_observability_fields_are_not_sent_to_backend():
    """관측 4종은 어느 화면에도 안 쓰여 콜백에서 뺐다 — 다시 새어나가지 않도록 고정."""
    dumped = build_callback_payload(_state()).model_dump(mode="json", by_alias=True)
    for key in ("modelVersion", "promptVersion", "costUsd", "latencyMs"):
        assert key not in dumped


# ── processedBy = '최종 처리를 누가 했는가' (팀 결정 2026-07-31) ──


def test_ai_completed_verdicts_are_processed_by_ai():
    """AI가 승인·반려까지 끝낸 건만 AI로 남는다 — 프론트 'AI 자동처리' 배지 조건."""
    for verdict in ("approve", "reject"):
        state = _state()
        state["verdict"] = verdict
        assert build_callback_payload(state).processed_by == "AI"


def test_escalate_has_no_processed_by():
    """관리자 확인 대기 건은 최종 처리자가 아직 없다 — null.

    여기서 'AI'를 보내면 대기 건이 화면에 'AI가 처리함'으로 표시된다.
    """
    state = _state()
    state["verdict"] = "escalate"
    assert build_callback_payload(state).processed_by is None


def test_admin_decision_overrides_to_admin():
    """HITL 재개 경로 — 관리자가 직접 결정한 건은 ADMIN."""
    state = _state()
    state["verdict"] = "escalate"
    state["admin_decision"] = {"decision": "approve", "by": "admin-1"}
    assert build_callback_payload(state).processed_by == "ADMIN"


def test_processed_by_serializes_as_null_not_omitted():
    """백엔드 파서가 키 부재와 null을 구분하지 않도록 키는 항상 실어 보낸다."""
    state = _state()
    state["verdict"] = "escalate"
    dumped = build_callback_payload(state).model_dump(mode="json", by_alias=True)
    assert "processedBy" in dumped and dumped["processedBy"] is None


# ── opinions 배열 순서 고정 (2026-08-11 배포 데모 결함) ──────────────────────
#
# 심사관 3종이 병렬이라 opinions dict의 삽입 순서가 실행마다 달라진다. 각 소견에
# auditor 필드가 있어도, 수신 측이 배열 순서로 카드를 그리면 "회칙 심사관 자리에
# 영수증 내용"처럼 라벨이 어긋난다(새로고침할 때마다 내용이 바뀌는 증상).

def _op(auditor: str):
    from app.schemas.common import Opinion
    return Opinion(auditor=auditor, verdict="pass", summary=f"{auditor} 소견")


def test_opinions_are_emitted_in_fixed_order():
    """완료 순서가 어떻든 증빙·예산·판례·회칙 순으로 나간다 (#86 정정 — 계약 문서
    2026-08-11 갱신 블록의 제안 순서이자 실화면 순서. 종전 회칙-먼저는 PR #62가
    리뷰 없이 넣은 값이었다)."""
    state = _state()
    # 뒤섞인 삽입 순서 — 완료 순서와 무관하게 고정돼야 한다
    state["opinions"] = {k: _op(k) for k in ("precedent", "rule", "evidence", "budget")}
    payload = build_callback_payload(state)
    assert [o.auditor for o in payload.opinions] == ["evidence", "budget", "precedent", "rule"]


def test_opinion_order_is_stable_across_completion_orders():
    """삽입 순서를 바꿔도 결과 배열이 동일해야 한다 — 이것이 깨지면 화면이 흔들린다."""
    import itertools
    outputs = set()
    for perm in itertools.permutations(("rule", "budget", "precedent", "evidence")):
        state = _state()
        state["opinions"] = {k: _op(k) for k in perm}
        outputs.add(tuple(o.auditor for o in build_callback_payload(state).opinions))
    assert outputs == {("evidence", "budget", "precedent", "rule")}


def test_partial_opinions_keep_relative_order():
    """심사관이 일부만 있어도(에스컬레이션 경로) 상대 순서는 유지된다."""
    state = _state()
    state["opinions"] = {k: _op(k) for k in ("budget", "evidence")}
    assert [o.auditor for o in build_callback_payload(state).opinions] == ["evidence", "budget"]
