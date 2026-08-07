"""rule_auditor — 회칙 미인덱싱 팀(version=None)의 no_rules 단락 회귀 테스트.

version이 None이면(회칙이 인덱싱된 적 없는 팀) search_rules를 부를 이유가 없다 —
인덱스 자체가 없으니 호출해도 항상 빈 결과다. _retrieve_with_correction은 이 경우
DB 조회 없이 바로 ("no_rules", None)로 확정한다(app/graphs/review/nodes/rule_auditor.py
docstring 참조).
"""

from unittest.mock import AsyncMock, patch

from app.graphs.review.nodes.rule_auditor import _retrieve_with_correction
from app.schemas.common import ExpenseClaim

CLAIM = ExpenseClaim(title="스터디 교재", amount=32_000, category="도서", date="2026-07-07")


async def test_no_version_short_circuits_without_calling_search_rules():
    with patch("app.graphs.review.nodes.rule_auditor.search_rules", new=AsyncMock()) as mock_search:
        result = await _retrieve_with_correction(team_id=1, claim=CLAIM, version=None, members=[])
    assert result == ([], "no_rules", None)
    mock_search.assert_not_called()
