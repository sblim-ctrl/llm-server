"""query_rewriter — rule_auditor CRAG 재검색 질의 재작성 (강의 08-03 rewriter).

목 모드 결정성 검증이 핵심: 재작성기가 LLM으로 승격돼도 목 모드는 기존
결정적 템플릿을 그대로 반환해야 골든셋·재검색 동작이 불변이다.
"""
from app.graphs.review.nodes.rule_auditor import (
    RewrittenQuery,
    _fallback_query,
    _rewrite_query,
)
from app.schemas.common import ExpenseClaim

CLAIM = ExpenseClaim(
    title="회식 2차 노래방", amount=66_000, category="회식비",
    date="2026-07-10", description="팀 회식 후 2차로 이동",
)


async def test_mock_rewrite_returns_deterministic_template():
    """목 모드: 기존 템플릿('{category} 지출 한도 금지 규정') 그대로 — 골든셋 불변."""
    query, meta = await _rewrite_query(CLAIM, members=[])
    assert query == _fallback_query(CLAIM) == "회식비 지출 한도 금지 규정"
    assert meta.mock is True


async def test_rewrite_meta_has_prompt_version():
    """재작성 호출도 계측 대상 — prompt_version이 메타에 기록된다."""
    _, meta = await _rewrite_query(CLAIM, members=[])
    assert meta.prompt_version == "query_rewriter/v2"


def test_empty_query_falls_back():
    """실모드 방어: LLM이 빈 문자열을 내면 결정적 템플릿으로 폴백한다."""
    # _rewrite_query 내부 `result.query.strip() or _fallback_query(claim)` 규칙 검증
    assert (RewrittenQuery(query="  ").query.strip()
            or _fallback_query(CLAIM)) == _fallback_query(CLAIM)
