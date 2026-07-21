"""LLM-as-Judge 채점 — 목 모드 결정적 동작 + passes 게이트 (§4 Sprint 2)."""
from app.eval_judge import JudgeResult, judge_reasons, passes

GOOD_REQ = "'스터디 교재' 지출이 회칙과 예산 기준을 충족하여 승인되었습니다."
GOOD_ADMIN = "회칙 제4조 적합, 잔액 182,000원 중 32,000원 집행, 반려 판례 없음."
LEAKY_REQ = "잔액이 1,000원밖에 없어 반려합니다. 유사 판례도 있었습니다."
VAGUE_ADMIN = "예산 부족."


async def test_good_reasons_pass():
    r, meta = await judge_reasons("approve", GOOD_REQ, GOOD_ADMIN)
    assert r.requester_leaks_internal is False
    assert r.admin_has_grounds is True
    assert passes(r) is True
    assert meta.mock is True


async def test_leaky_requester_fails():
    """요청자용에 잔액 수치·판례 노출 → 내부 노출 감지 → 불합격."""
    r, _ = await judge_reasons("reject", LEAKY_REQ, GOOD_ADMIN)
    assert r.requester_leaks_internal is True
    assert passes(r) is False


async def test_qualitative_reject_reason_passes():
    """캘리브레이션: '예산 잔액이 부족하여'(숫자 없음)는 내부 노출이 아니다 —
    v1 judge가 '잔액' 단어만 보고 오판하던 false positive의 회귀 방지."""
    reason = "모임 예산 잔액이 부족하여 이번 지출은 승인이 어렵습니다. 충전 후 신청해 주세요."
    r, _ = await judge_reasons("reject", reason, GOOD_ADMIN)
    assert r.requester_leaks_internal is False
    assert passes(r) is True


async def test_vague_admin_fails():
    """관리자용에 근거 수치·조항 없음 → 불합격."""
    r, _ = await judge_reasons("reject", GOOD_REQ, VAGUE_ADMIN)
    assert r.admin_has_grounds is False
    assert passes(r) is False


def test_passes_requires_all_conditions():
    base = dict(requester_polite=True, requester_leaks_internal=False,
                admin_has_grounds=True, overall_score=0.9)
    assert passes(JudgeResult(**base)) is True
    assert passes(JudgeResult(**{**base, "overall_score": 0.5})) is False  # 임계 미달
    assert passes(JudgeResult(**{**base, "requester_leaks_internal": True})) is False
    assert passes(JudgeResult(**{**base, "admin_has_grounds": False})) is False
