"""LLM 하네스(B2) — 마스킹 seam·비용 계산·목 메타."""
from pydantic import BaseModel

from app.llm.client import chat_structured, cost_usd, prepare_user_prompt

MEMBERS = [{"name": "김철수", "role": "총무"}, {"name": "이영희", "role": "회원"}]


class Echo(BaseModel):
    text: str = "ok"


def test_prepare_user_prompt_masks_member_names():
    masked = prepare_user_prompt("김철수가 결제하고 이영희가 참석", MEMBERS)
    assert "김철수" not in masked and "이영희" not in masked
    assert "총무" in masked  # 실명 → 역할 치환 (PIIMasker 규약)


def test_prepare_user_prompt_without_roster_is_noop():
    assert prepare_user_prompt("김철수가 결제", None) == "김철수가 결제"
    assert prepare_user_prompt("김철수가 결제", []) == "김철수가 결제"


def test_cost_usd_from_pricing_table():
    # gpt-4o: $2.50/1M in, $10.00/1M out
    assert cost_usd("gpt-4o", 1_000_000, 0) == 2.50
    assert cost_usd("gpt-4o", 0, 1_000_000) == 10.00
    assert cost_usd("unknown-model", 1000, 1000) == 0.0  # 미등록 → 0 + 경고


async def test_mock_call_returns_meta_with_routed_model():
    result, meta = await chat_structured(
        agent="adjudicator", system="s", user="u", schema=Echo,
        mock_response=Echo(), prompt_version="adjudicator/v1")
    assert result.text == "ok"
    assert meta.mock is True
    assert meta.model == "gpt-4o"           # models.yaml 라우팅 값
    assert meta.prompt_version == "adjudicator/v1"
    assert meta.tokens_in == 0 and meta.cost_usd == 0.0
