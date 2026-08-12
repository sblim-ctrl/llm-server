"""rule_auditor — 증빙에서 읽은 사실(상호·품목)을 판단 근거로 받는다 (2026-08-12).

**무엇이 문제였나.** 이 심사관만 `claim`(제목·금액·카테고리·날짜·설명)을 받고
영수증을 못 봤다. 제목·설명은 청구자가 자유롭게 쓴 주관적 텍스트라, 같은 지출도
어떻게 적느냐에 따라 판정이 갈렸다.

실사용 사례: 제목 "보드게임"·설명 "모임 활동"으로 올라온 60,000원을 "보드게임
**구입**"으로 읽고 개인 물품 조항 위반으로 판정했다. 같은 영수증을 카테고리
분류기(`classify_category`)와 증빙 심사관(`mismatch_gate`)은 제대로 읽고 있었다 —
상호 "플레이박스 보드게임", 품목 "2시간 이용권 x6". 시설 이용료였고 구입이 아니었다.

**이 파일은 배선을 검사한다.** `receipt_facts_block`만 검사하는 순수 함수 테스트는
호출부에서 전달을 지워도 통과한다(이 저장소에서 반복 확인된 함정 — PR #73에서
`translate_result_terms` 테스트 4건이 배선 삭제 뮤테이션을 전부 통과했다).
그래서 여기서는 **LLM에 실제로 넘어간 user 메시지**와 **검색에 넘어간 질의**를 본다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.graphs.review.nodes.rule_auditor import (
    RELEVANCE_MAX_DISTANCE,
    _SEARCH_ITEMS_CAP,
    _search_text,
    receipt_facts_block,
    rule_auditor,
)
from app.schemas.common import ExpenseClaim, Opinion, ReceiptData

# 실사용 사례 그대로 — 제목만 보면 '구입'으로 읽히는 청구
CLAIM = ExpenseClaim(
    title="보드게임",
    amount=60_000,
    category="행사_활동",
    date="2026-08-09",
    description="모임 활동",
)
RECEIPT = ReceiptData(
    amount=60_000,
    date="2026-08-09",
    merchant="플레이박스 보드게임",
    items=["2시간 이용권 x6", "음료 패키지 x6"],
    parse_ok=True,
)
RELEVANT_CHUNK = {
    "text": "제11조 개인이 단독으로 소유·사용하는 물품 구입비는 인정하지 아니한다.",
    "distance": RELEVANCE_MAX_DISTANCE - 0.2,
}


def _state(receipt: ReceiptData | None = RECEIPT) -> dict:
    return {
        "claim": CLAIM,
        "team_id": 1,
        "rule_version": 3,
        "team_members": [],
        "receipt_data": receipt,
    }


# ── 순수 함수 ────────────────────────────────────────────


def test_facts_block_renders_merchant_and_items():
    block = receipt_facts_block(RECEIPT)
    assert "플레이박스 보드게임" in block
    assert "2시간 이용권 x6" in block


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        ReceiptData(parse_ok=False, parse_error="판독 실패"),
        ReceiptData(parse_ok=True),  # 판독은 됐지만 상호·품목이 비었다
    ],
)
def test_facts_block_empty_when_nothing_to_say(receipt):
    """미첨부·판독 실패·빈 값이면 블록 자체를 만들지 않는다 — 빈 제목만 붙으면 잡음이다."""
    assert receipt_facts_block(receipt) == ""


# ── 배선 (여기가 핵심) ───────────────────────────────────


async def _captured_llm_user(state: dict) -> str:
    """rule_auditor를 돌리고 LLM에 실제로 넘어간 user 메시지를 돌려준다."""
    captured = {}

    async def fake_chat(**kwargs):
        captured["user"] = kwargs["user"]
        return Opinion(auditor="rule", verdict="pass", summary="테스트"), None

    with patch(
        "app.graphs.review.nodes.rule_auditor.search_rules",
        new=AsyncMock(return_value=[RELEVANT_CHUNK]),
    ), patch("app.graphs.review.nodes.rule_auditor.chat_structured", new=fake_chat):
        await rule_auditor(state)
    return captured["user"]


async def test_llm_receives_receipt_facts():
    """LLM user 메시지에 상호·품목이 실려야 한다.

    이 검사가 없으면 `receipt_facts_block`을 만들어 두고 호출부에서 안 쓰는 상태가
    조용히 통과한다 — 종전 상태와 동작이 같아진다.
    """
    user = await _captured_llm_user(_state())
    assert "플레이박스 보드게임" in user, "상호가 판정 입력에 없다"
    assert "2시간 이용권 x6" in user, "품목이 판정 입력에 없다"


async def test_facts_come_before_the_clauses():
    """사실이 조항보다 먼저 온다 — 무엇을 산 것인지 확정한 뒤 조항을 댄다.

    순서가 뒤집히면 조항을 먼저 읽고 제목에 끼워 맞추는 경로가 남는다.
    """
    user = await _captured_llm_user(_state())
    assert user.index("증빙에서 읽은 사실") < user.index("관련 회칙 조항")


async def test_no_receipt_block_when_receipt_missing():
    """영수증이 없으면 빈 헤더를 붙이지 않는다 — 없는 사실을 있는 것처럼 보이면 안 된다."""
    user = await _captured_llm_user(_state(receipt=None))
    assert "증빙에서 읽은 사실" not in user
    assert CLAIM.title in user  # claim 자체는 그대로 간다


async def test_search_query_includes_receipt_facts():
    """RAG 검색 질의에도 상호·품목이 들어가야 한다.

    판정 입력만 고치고 검색을 두면, 애초에 엉뚱한 조항이 검색돼 올라오는 경로가
    남는다 — 제목 "보드게임"으로만 찾으면 '물품 구입 금지' 조항이 먼저 걸린다.
    """
    captured = {}

    async def fake_search(team_id, query, version):
        captured["query"] = query
        return [RELEVANT_CHUNK]

    async def fake_chat(**kwargs):
        return Opinion(auditor="rule", verdict="pass", summary="테스트"), None

    with patch(
        "app.graphs.review.nodes.rule_auditor.search_rules", new=fake_search
    ), patch("app.graphs.review.nodes.rule_auditor.chat_structured", new=fake_chat):
        await rule_auditor(_state())

    assert "플레이박스 보드게임" in captured["query"], "검색 질의에 상호가 없다"
    assert "2시간 이용권 x6" in captured["query"], "검색 질의에 품목이 없다"
    assert CLAIM.title in captured["query"], "제목은 그대로 남아야 한다"


def test_search_query_caps_receipt_items():
    """품목은 intake 계약 상한(10개)까지만 질의에 붙는다 (#84 리뷰).

    intake/v3가 최대 10개를 명문화하지만 코드에 상한이 없으면, 그 계약이 바뀌거나
    그래프 밖 호출이 긴 목록을 넘길 때 품목이 임베딩 질의를 지배해 제목·설명 신호가
    희석된다. 상한을 넘는 목록은 잘리고 제목은 항상 남아야 한다.
    """
    long_receipt = RECEIPT.model_copy(
        update={"items": [f"품목{i}" for i in range(_SEARCH_ITEMS_CAP + 5)]}
    )
    query = _search_text(CLAIM, long_receipt)
    assert f"품목{_SEARCH_ITEMS_CAP - 1}" in query, "상한 안의 품목이 빠졌다"
    assert f"품목{_SEARCH_ITEMS_CAP}" not in query, "상한을 넘는 품목이 잘리지 않았다"
    assert CLAIM.title in query


async def test_default_policy_path_also_gets_facts():
    """회칙 미등록 팀(기본 정책 모드)도 같은 사실을 받아야 한다.

    두 경로가 갈리면 회칙을 등록한 팀과 아닌 팀의 판정 근거가 달라진다.
    """
    captured = {}

    async def fake_chat(**kwargs):
        captured["user"] = kwargs["user"]
        return Opinion(auditor="rule", verdict="pass", summary="테스트"), None

    state = _state()
    state["rule_version"] = None  # 인덱싱된 회칙 없음 → 기본 정책 모드
    state["team_type"] = "스터디"
    with patch("app.graphs.review.nodes.rule_auditor.chat_structured", new=fake_chat):
        await rule_auditor(state)

    assert "플레이박스 보드게임" in captured["user"]
    assert "2시간 이용권 x6" in captured["user"]
