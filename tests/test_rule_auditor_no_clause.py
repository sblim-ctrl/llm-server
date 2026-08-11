"""rule_auditor — "관련 조항 없음"은 pass다 (2026-08-11 정책 확정).

종전에는 검색이 근거를 못 찾으면(grade="insufficient") warn을 냈고, 그게 guardrail의
`rule_ambiguous` → 에스컬레이션이라 **회칙에 안 적힌 지출이 전부 관리자 대기열로** 갔다.
회칙은 모든 지출 유형을 열거하지 않으므로(장소 대관·택배·비품처럼 조항이 없는 게 정상인
항목이 더 많다) 정상 지출 대부분이 보류됐다 — 배포 데모에서 장소 대관비가 그랬다.

Self-RAG 원칙(근거 없이 지어내지 않는다)은 그대로고 결론만 바로잡았다: 조항 부재는
"판단 불가"가 아니라 "회칙을 근거로는 막을 수 없음"이다.

**이 파일이 없으면 정책이 무방비다.** 이 변경에는 원래 단위 테스트가 없었다 — PR의
신규 테스트 19건은 전부 guardrail 몫이었다(2026-08-11 리뷰 분리 과정에서 발견).
"""

from unittest.mock import AsyncMock, patch

from app.graphs.review.nodes.rule_auditor import RELEVANCE_MAX_DISTANCE, rule_auditor
from app.schemas.common import ExpenseClaim

CLAIM = ExpenseClaim(
    title="장소 대관비",
    amount=90_000,
    category="장소_대관",
    date="2026-07-22",
    description="정기 모임 공간 대관",
)

# 검색은 항상 무언가를 돌려준다 — 문제는 그게 이 청구와 무관하다는 것이다.
# 데모에서 장소 대관비 청구에 다과비 조항이 걸려 나온 그 상황을 그대로 만든다.
IRRELEVANT_CHUNK = {
    "text": "3. 다과비는 회당 30,000원 한도로 집행한다.",
    "distance": RELEVANCE_MAX_DISTANCE + 0.1,
}
RELEVANT_CHUNK = {
    "text": "5. 장소 대관은 사전 승인 후 집행한다.",
    "distance": RELEVANCE_MAX_DISTANCE - 0.2,
}


def _state() -> dict:
    return {"claim": CLAIM, "team_id": 1, "rule_version": 3, "team_members": []}


async def test_no_relevant_clause_passes_instead_of_warning():
    """무관한 조항만 걸려 나오면 pass — 종전 warn(→에스컬레이션)이 데모 보류의 원인이었다."""
    with patch(
        "app.graphs.review.nodes.rule_auditor.search_rules",
        new=AsyncMock(return_value=[IRRELEVANT_CHUNK]),
    ):
        out = await rule_auditor(_state())

    opinion = out["opinions"]["rule"]
    assert opinion.verdict == "pass", "조항 부재는 위반이 아니다 — warn이면 관리자 대기열로 간다"
    assert opinion.auditor == "rule"


async def test_no_relevant_clause_cites_nothing():
    """근거를 못 찾았으면 근거 칸은 비어야 한다 — 무관한 조항을 인용하면 환각 인용이다.

    Self-RAG 원칙은 이 변경 뒤에도 그대로다. 결론이 pass로 바뀐 것이지, 없는 근거를
    지어내도 된다는 뜻이 아니다.
    """
    with patch(
        "app.graphs.review.nodes.rule_auditor.search_rules",
        new=AsyncMock(return_value=[IRRELEVANT_CHUNK]),
    ):
        out = await rule_auditor(_state())

    opinion = out["opinions"]["rule"]
    assert not opinion.evidence, f"인용하면 안 되는 조항을 근거로 남겼다: {opinion.evidence}"
    assert IRRELEVANT_CHUNK["text"] not in opinion.summary


async def test_relevant_clause_still_goes_to_llm_judgement():
    """관련 조항이 있으면 종전대로 LLM 판정 경로다 — 전부 pass로 만든 게 아니다.

    이 테스트가 없으면 "조항 부재는 pass"가 "회칙 심사를 사실상 껐다"로 번져도
    아무도 모른다. 근거 조항이 소견에 실리는지로 두 경로를 가른다.
    """
    with patch(
        "app.graphs.review.nodes.rule_auditor.search_rules",
        new=AsyncMock(return_value=[RELEVANT_CHUNK]),
    ):
        out = await rule_auditor(_state())

    opinion = out["opinions"]["rule"]
    assert opinion.evidence == [RELEVANT_CHUNK["text"]], "검증된 근거는 그대로 인용돼야 한다"
    assert "rule_auditor" in out["llm_meta"], "LLM 판정 경로를 탔다면 계측이 남아야 한다"
