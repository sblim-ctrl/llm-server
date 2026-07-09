"""영수증 추출 텍스트 파싱 테스트 — 백엔드가 텍스트를 주는 경로 (팀 방향 2026-07-09)."""
from app.graphs.review.nodes.intake_receipt import parse_receipt_text


def test_parses_amount_and_date():
    text = "OO식당\n2026-07-08\n삼겹살 2인분 32,000원\n합계 45,000원"
    r = parse_receipt_text(text)
    assert r.parse_ok is True
    assert r.amount == 45_000   # 최대 금액 = 합계 가정
    assert r.date == "2026-07-08"


def test_plain_number_amount():
    r = parse_receipt_text("결제금액 18000원")
    assert r.amount == 18_000


def test_no_amount_marks_unparseable():
    r = parse_receipt_text("읽을 수 없는 영수증입니다")
    assert r.parse_ok is False   # → 가드레일 receipt_unreadable로 에스컬레이션
