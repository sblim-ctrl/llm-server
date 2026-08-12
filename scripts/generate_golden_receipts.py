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

# 한글 렌더 가능한 폰트 후보 (mac → Linux → Windows).
#
# **Windows 경로가 없어서 사고가 났다** (#70): 후보에 못 찾으면 조용히
# `load_default()`로 떨어졌고, 그 폰트는 한글을 두부(□)로 그린다. 결과물은 정상처럼
# 저장돼(3.5KB) 그대로 커밋됐다 — 같은 스크립트·같은 레이아웃인데 생성한 사람의 OS에
# 따라 판독 가능/불가가 갈렸다. 지금 저장소에 11개가 그 상태로 남아 있다.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/gulim.ttc",
]


class KoreanFontNotFound(RuntimeError):
    """한글 폰트를 못 찾음 — 두부 영수증을 만드느니 멈춘다."""


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """한글 폰트를 찾아 로드. **못 찾으면 예외** — 조용한 폴백을 두지 않는다.

    종전에는 `ImageFont.load_default()`로 폴백했다. 그게 #70의 원인이다: 실패가
    보이지 않으니 두부 이미지가 정상 산출물로 커밋됐다. 여기서 멈추면 폰트를 깔거나
    후보 경로를 추가하라는 신호가 즉시 온다 — 골든 자산이 조용히 오염되는 것보다 낫다.
    """
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise KoreanFontNotFound(
        "한글 폰트를 찾지 못했습니다. 아래 중 하나를 설치하거나 _FONT_CANDIDATES에 "
        "경로를 추가하세요:\n  " + "\n  ".join(_FONT_CANDIDATES)
    )


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
    """기본은 신규 생성(example.com 잔여분). `--ids a,b,c`면 **재생성 모드**.

    재생성 모드가 따로 있는 이유: 이미 file://로 이관된 케이스는 기본 경로에서
    건너뛰므로, 두부로 렌더된 기존 영수증을 다시 만들 방법이 없었다(#70). 재생성
    모드는 골든셋 JSON을 **쓰지 않는다** — 경로가 이미 맞으므로 건드릴 이유가 없고,
    전체를 다시 직렬화하면 손으로 정리한 포맷이 통째로 바뀐다.
    """
    regen_ids: set[str] = set()
    if len(sys.argv) > 1 and sys.argv[1].startswith("--ids"):
        raw = sys.argv[1].split("=", 1)[1] if "=" in sys.argv[1] else sys.argv[2]
        regen_ids = {s.strip() for s in raw.split(",") if s.strip()}

    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    expenses = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["expenses"]
    cases = data["cases"]
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    if regen_ids:
        known = {c["id"] for c in cases}
        if unknown := regen_ids - known:
            print(f"골든셋에 없는 id: {sorted(unknown)}")
            return 2

    generated = 0
    for case in cases:
        receipt_path = case["input"].get("receiptPath") or ""
        if regen_ids:
            if case["id"] not in regen_ids:
                continue
        elif not receipt_path.startswith("https://example.com"):
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

    print(f"이미지 생성: {generated}건 → {RECEIPTS_DIR}")
    if regen_ids:
        # 재생성 모드는 경로를 바꾸지 않는다 — 골든셋을 다시 직렬화하면 손으로 정리한
        # 포맷이 통째로 바뀌어 diff가 파일 전체가 된다.
        # 한글 콘솔(cp949)에서 깨지지 않도록 em dash 같은 문자는 쓰지 않는다
        print("재생성 모드: golden_v1.json은 건드리지 않았다")
        return 0
    GOLDEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"golden_v1.json 갱신 완료 ({GOLDEN_PATH})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
