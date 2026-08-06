"""골든셋 영수증 이미지 생성 — receiptPath의 https://example.com 플레이스홀더를
실제 로컬 이미지 파일(eval/golden/receipts/{id}.png)로 교체한다.

배경: MOCK_LLM=false(실키) 실행에서 intake_receipt가 receipt_path를 그대로
OpenAI Vision에 image_url로 넘기는데, example.com은 실제 이미지가 아니라 매번
invalid_image_url로 실패해 guardrail_gate가 전건 receipt_unreadable→escalate로
수렴시켰다(adjudicator 등 후속 프롬프트가 아예 호출되지 않음).

대상: receiptPath가 https://example.com으로 시작하는 케이스만(이미 대부분
file://로 이관돼 잔여 5건 — 재실행해도 이미 렌더링된 나머지에는 영향 없다).
아래는 그대로 둔다 — mock://receipt?... 8건(mismatch 시나리오, 실키에서도
결정적으로 처리되는 기존 계약)과 receiptPath 없는 6건(미첨부 시나리오).

청구 내용(eval/fixtures/mock_backend.json의 title/amount/category/date — T9 이전엔
expenseId 쿼리스트링이었다)과 정확히 일치하는 금액·날짜를 렌더링한다 —
mismatch_gate는 amount·date만 비교하므로 이 둘만 정확하면 되고, merchant는 임의
상호명을 붙인다.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "eval" / "golden" / "golden_v1.json"
FIXTURE_PATH = ROOT / "eval" / "fixtures" / "mock_backend.json"
RECEIPTS_DIR = ROOT / "eval" / "golden" / "receipts"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _merchant_for(category: str) -> str:
    table = {
        "도서": "동네서점",
        "다과": "카페모카",
        "홍보": "굿즈프린트",
        "비품": "오피스마트",
        "교육": "온라인클래스",
        "인쇄": "복사마당",
        "대관": "공유오피스",
        "실습": "테크스토어",
        "행사": "이벤트홀",
        "물품": "생활마트",
        "회의": "스터디카페",
        "식비": "맛있는식당",
        "장비": "스포츠샵",
        "시설": "체육관",
        "숙박": "게스트하우스",
        "레저": "볼링장",
        "선물": "꽃집",
        "장소": "파티룸",
        "교통": "모범택시",
        "경조사": "화훼마켓",
        "복리후생": "복지몰",
    }
    for key, name in table.items():
        if key in category:
            return name
    return "일반상점"


def render_receipt(title: str, amount: int, date: str, category: str) -> Image.Image:
    img = Image.new("RGB", (500, 400), "white")
    draw = ImageDraw.Draw(img)
    title_font = _load_font(22)
    body_font = _load_font(18)

    merchant = _merchant_for(category)
    lines = [
        (merchant, title_font),
        ("", body_font),
        (f"날짜: {date}", body_font),
        (f"품목: {title}", body_font),
        ("", body_font),
        ("-" * 30, body_font),
        (f"합계: {amount:,}원", title_font),
        ("-" * 30, body_font),
        ("카드 승인 완료", body_font),
    ]
    y = 30
    for text, font in lines:
        draw.text((30, y), text, fill="black", font=font)
        y += 34
    return img


def main() -> int:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    expenses = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["expenses"]
    cases = data["cases"]
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    for case in cases:
        receipt_path = case["input"].get("receiptPath") or ""
        if not receipt_path.startswith("https://example.com"):
            continue  # mock://receipt(불일치 시나리오)·미첨부는 그대로 둔다

        expense = expenses[str(case["input"]["expenseId"])]
        title = expense["title"]
        amount = expense["amount"]
        date = expense["date"]
        # 상호명 선택용 — fixture의 expenses에는 더 이상 category가 없다(2026-08-06:
        # 심사 전 지출에 카테고리가 없는 것이 백엔드 계약). 사람이 매긴 정답은 골든셋의
        # expected_category에 있으므로 그것을 쓴다. 없으면 _merchant_for가 '일반상점'으로 떨어진다.
        category = case.get("expected_category", "")

        img = render_receipt(title, amount, date, category)
        out_path = RECEIPTS_DIR / f"{case['id']}.png"
        img.save(out_path)

        # 저장소 루트 기준 상대경로 — 팀원 간 이식성.
        # **as_posix() 필수**: 윈도우에서 돌리면 relative_to가 역슬래시 경로를 주고
        # (`eval\golden\receipts\x.png`), 그대로 골든셋에 박히면 CI(우분투)·macOS의
        # 실모드 평가에서 파일을 못 연다. 이 파일은 OS를 가리지 않고 공유되므로
        # 경로 구분자를 POSIX로 고정한다 (2026-08-06 실제로 밟은 함정).
        rel_path = out_path.relative_to(ROOT).as_posix()
        case["input"]["receiptPath"] = f"file://{rel_path}"
        generated += 1

    GOLDEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"이미지 생성: {generated}건 → {RECEIPTS_DIR}")
    print(f"golden_v1.json 갱신 완료 ({GOLDEN_PATH})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
