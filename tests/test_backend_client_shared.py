"""공유 httpx 클라이언트 (성능 고도화) — 싱글턴·정리·재생성 동작 + 응답 키 정규화."""

import pytest

from app.tools import backend_client
from app.tools.backend_client import (
    _LEGACY_CATEGORY_ALIASES,
    _client,
    _normalize_budget,
    close_backend_client,
    normalize_expense_category,
)
from app.tools.category_catalog import all_categories


async def test_client_is_reused_and_closed():
    c1 = _client()
    assert _client() is c1  # 호출마다 재생성하지 않음 (연결 풀 재사용)
    await close_backend_client()
    assert c1.is_closed
    assert backend_client._http_client is None  # 정리 후 상태 초기화


async def test_client_recreated_after_close():
    c1 = _client()
    await close_backend_client()
    c2 = _client()
    assert c2 is not c1 and not c2.is_closed  # 종료 후 재요청 시 새로 생성
    await close_backend_client()  # 테스트 뒷정리


# ── 예산 응답 키 정규화 (DB 표기 used_budget / API 표기 usedBudget) ──


def test_normalize_budget_accepts_all_spellings():
    expected = {"total_budget": 300_000, "spent": 118_000}
    assert _normalize_budget({"total_budget": 300_000, "spent": 118_000}) == expected
    assert _normalize_budget({"total_budget": 300_000, "used_budget": 118_000}) == expected
    assert _normalize_budget({"totalBudget": 300_000, "usedBudget": 118_000}) == expected


def test_normalize_budget_raises_when_key_missing():
    """0으로 때우지 않는다 — budget_auditor가 error 소견으로 잡아 에스컬레이션되어야 한다."""
    with pytest.raises(KeyError):
        _normalize_budget({"total_budget": 300_000})


# ── 지출 이력 카테고리 정규화 (구 값 → 전역 9종) ──


def test_alias_targets_are_all_in_catalog():
    """대응표의 도착지는 전부 9종 안이어야 한다 — 카탈로그가 바뀌면 여기서 먼저 깨진다."""
    assert set(_LEGACY_CATEGORY_ALIASES.values()) <= set(all_categories())


def test_nine_categories_pass_through_unchanged():
    for name in all_categories():
        assert normalize_expense_category(name) == name


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("식대/회식비", "식비"),
        ("교통/출장비", "교통"),
        ("온라인/구독비", "IT_인프라"),
        ("교재/자료비", "교육"),
        ("회의/워크숍비", "회의"),
        ("공간/대관비", "장소_대관"),
        ("숙박/여행비", "장소_대관"),  # 팀 결정 2026-08-06 (기타 아님)
        ("실습/프로젝트비", "행사_활동"),  # 팀 결정 2026-08-06 (교육 아님)
        ("홍보/콘텐츠비", "행사_활동"),  # 팀 결정 2026-08-06 (기타 아님)
        ("레저/액티비티비", "행사_활동"),
        ("인쇄/문구비", "비품"),
        ("선물/기념비", "기타"),
        ("행사", "행사_활동"),  # 백엔드 구 ENUM
        ("디자인", "기타"),  # 백엔드 구 ENUM
        ("행사활동", "행사_활동"),  # 언더바 누락 방어 (2026-08-09 백엔드 마이그레이션 공지)
    ],
)
def test_legacy_categories_map_to_nine(legacy, expected):
    assert normalize_expense_category(legacy) == expected


def test_unknown_category_falls_back_with_warning(caplog):
    """조용히 접지 않는다 — 계약이 어긋난 사실이 로그에 남아야 한다."""
    with caplog.at_level("WARNING"):
        assert normalize_expense_category("듣도보도못한비") == "기타"
    assert "듣도보도못한비" in caplog.text


@pytest.mark.parametrize("empty", [None, "", "   ", 123])
def test_missing_category_falls_back(empty):
    assert normalize_expense_category(empty) == "기타"


async def test_get_expense_history_normalizes_real_mode_rows(monkeypatch):
    """실모드 응답에 구 값이 섞여 와도 이력을 쓰는 네 곳은 9종만 본다."""

    class _FakeResponse:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> list[dict]:
            return [
                {"title": "교재", "amount": 30000, "category": "교재/자료비"},
                {"title": "포스터", "amount": 50000, "category": "디자인"},
                {"title": "회식", "amount": 80000, "category": "식비"},
            ]

    class _FakeClient:
        @staticmethod
        async def get(_url: str, params: dict | None = None) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(backend_client, "_client", lambda: _FakeClient())
    monkeypatch.setattr(backend_client.get_settings(), "mock_backend", False, raising=False)

    rows = await backend_client.get_expense_history(1)
    assert [r["category"] for r in rows] == ["교육", "기타", "식비"]


async def test_get_expense_detail_normalizes_real_mode_category(monkeypatch):
    """상세도 이력과 같은 경계에서 접는다 — claim.category가 구 값으로 서지 않게.

    load_context가 claim.category를 만드는 출처는 이력이 아니라 이 함수다. 여기서
    접지 않으면 백엔드 ENUM 마이그레이션 전까지 구 값이 심사 그래프 안까지 들어온다.
    """

    class _FakeResponse:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict:
            return {
                "title": "교재",
                "amount": 32000,
                "category": "교재/자료비",
                "date": "2026-07-01",
                "description": "알고리즘 교재 2권",
            }

    class _FakeClient:
        @staticmethod
        async def get(_url: str, params: dict | None = None) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(backend_client, "_client", lambda: _FakeClient())
    monkeypatch.setattr(backend_client.get_settings(), "mock_backend", False, raising=False)

    detail = await backend_client.get_expense_detail(1, 1)
    assert detail["category"] == "교육"
    # 나머지 필드는 그대로 통과시킨다
    assert detail["title"] == "교재"
    assert detail["amount"] == 32000


@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_get_expense_detail_keeps_blank_category_blank(monkeypatch, blank):
    """빈 값은 '기타'로 접지 않는다 — BE-001 계약상 null이 정상 경로다.

    이력과 갈리는 지점이다. 이력의 빈 값은 집계 버킷이 필요해 '기타'로 접지만,
    상세의 빈 값은 **분류기를 돌리라는 신호**다. 여기서 '기타'로 채우면 claim.category가
    비어 있지 않게 되어 AI 분류가 통째로 무력화된다(모든 지출이 기타로 확정).
    """

    class _FakeResponse:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict:
            return {"title": "모임 회식", "amount": 30000, "category": blank}

    class _FakeClient:
        @staticmethod
        async def get(_url: str, params: dict | None = None) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(backend_client, "_client", lambda: _FakeClient())
    monkeypatch.setattr(backend_client.get_settings(), "mock_backend", False, raising=False)

    detail = await backend_client.get_expense_detail(1, 1)
    assert not (detail["category"] or "").strip()


async def test_get_expense_detail_mock_does_not_normalize(monkeypatch):
    """목 분기는 normalize_expense_category를 타지 않는다 — fixture 값을 그대로 반환한다.

    fixture 자체는 이미 9종만 담지만(tests/test_mock_fixture.py가 강제), 이 함수가
    실모드처럼 접지 않는다는 계약은 별도로 지켜야 한다 — 나중에 mock 분기에도
    정규화를 추가하면 fixture가 의도적으로 담은 값이 조용히 바뀐다.
    """
    monkeypatch.setattr(
        backend_client,
        "_fixture_expense",
        lambda expense_id: {
            "title": "레거시 값 테스트",
            "amount": 1000,
            "category": "교재/자료비",  # 정규화하면 "교육"이 될 값
            "date": "2026-07-01",
            "description": "",
        },
    )
    detail = await backend_client.get_expense_detail(9002, 90001)
    assert detail["category"] == "교재/자료비"


async def test_get_team_profile_normalizes_real_mode_team_type(monkeypatch):
    """백엔드 ENUM은 언더바 표기(2026-08-06 확정) — 프로필 응답도 경계에서 내부 표기로 접는다.

    변환 없이는 templates·유형별 카탈로그 조회가 조용히 기본 유형으로 fallback한다
    (policy_defaults.py:53 · load_context.py:77-79).
    """

    class _FakeResponse:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict:
            return {"team_type": "동아리_학생회"}

    class _FakeClient:
        @staticmethod
        async def get(_url: str, params: dict | None = None) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(backend_client, "_client", lambda: _FakeClient())
    monkeypatch.setattr(backend_client.get_settings(), "mock_backend", False, raising=False)

    profile = await backend_client.get_team_profile(1)
    assert profile["team_type"] == "동아리/학생회"
