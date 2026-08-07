"""GET /v1/context/status — 회칙이 실제로 심사에 반영될 수 있는지 조회.

인덱싱은 202로 접수만 하고 비동기로 돌기 때문에, 실패해도 백엔드가 알 방법이 없었다.
그 상태로 두면 관리자는 마법사에서 회칙을 등록하고 설정 완료까지 눌렀는데 심사는 회칙
없이 돌아가고 아무도 눈치채지 못한다. 조용한 실패라 더 나쁘다.
"""

from unittest.mock import AsyncMock, patch

from app.api.context import read_context_status


def _rows(chunk_count=0, version=None, indexed_at=None):
    return {"chunk_count": chunk_count, "version": version, "indexed_at": indexed_at}


async def test_no_rules_reports_not_indexed():
    """회칙이 없는 것은 정상 상태다 — 예외가 아니라 indexed=false로 알린다."""
    with patch("app.api.context.get_context_status", new=AsyncMock(return_value=_rows())):
        s = await read_context_status(11)
    assert s.indexed is False
    assert s.chunk_count == 0
    assert s.indexed_at is None


async def test_indexed_team_reports_counts():
    from datetime import datetime

    at = datetime(2026, 8, 3, 10, 30)
    with patch("app.api.context.get_context_status", new=AsyncMock(return_value=_rows(12, 2, at))):
        s = await read_context_status(11)
    assert s.indexed is True
    assert s.chunk_count == 12
    assert s.indexed_at.startswith("2026-08-03")


async def test_indexed_flag_follows_chunk_count():
    """조항이 하나라도 있으면 indexed다 — 화면이 이 값 하나로 분기할 수 있어야 한다."""
    for count, expected in ((0, False), (1, True), (99, True)):
        with patch(
            "app.api.context.get_context_status", new=AsyncMock(return_value=_rows(count, 1))
        ):
            s = await read_context_status(11)
        assert s.indexed is expected, f"chunk_count={count}"
