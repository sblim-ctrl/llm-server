"""PIIMasker 순수 함수 단위 테스트 (§4.3, REQ-042·043)."""
from app.middleware.pii_masker import build_alias_map, mask_names

MEMBERS = [
    {"name": "김철수", "role": "총무"},
    {"name": "이영희", "role": "회원"},
    {"name": "박민준", "role": "회원"},
]


def test_unique_role_gets_plain_alias():
    alias = build_alias_map(MEMBERS)
    assert alias["김철수"] == "총무"


def test_duplicate_roles_get_numbered():
    alias = build_alias_map(MEMBERS)
    assert alias["이영희"] == "회원1"
    assert alias["박민준"] == "회원2"


def test_masks_names_in_text():
    text = "김철수가 이영희에게 회식비를 이체함"
    assert mask_names(text, MEMBERS) == "총무가 회원1에게 회식비를 이체함"


def test_longer_names_replaced_first():
    members = [{"name": "김철수", "role": "총무"}, {"name": "김철", "role": "회원"}]
    # "김철수"가 "김철"보다 먼저 치환되어야 "회원수" 같은 오염이 없다
    assert mask_names("김철수 결제", members) == "총무 결제"


def test_no_members_returns_original():
    assert mask_names("김철수 결제", []) == "김철수 결제"


def test_empty_text():
    assert mask_names("", MEMBERS) == ""
