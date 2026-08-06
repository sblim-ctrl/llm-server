"""classify_category — 지출 카테고리 자동 분류 (전역 9종, 풀스택 협의 2026-08-04).

카테고리는 **AI가 고정 9종 안에서 골라 채운다.** 카테고리 동적 추가 금지 —
후보 목록 밖의 값은 절대 만들지 않는다.

풀스택 협의 2026-08-04로 **지출 등록 화면의 카테고리 직접 입력이 없어졌다.** 백엔드도
`expenses.category`를 nullable로 바꿔 항상 빈 값으로 보내기로 회신했다(2026-08-06).
그래서 AI 분류가 **유일한 카테고리 출처**가 된다.

**AI 권한의 범위 (T7, 2026-08-06)**
- AI는 `all_categories()` 9종 **안에서만** 고른다. 목록 밖 값을 내면 코드가 키워드로
  교정한다 — 환각 카테고리가 백엔드 ENUM에 닿지 못하게 하는 마지막 방어다.
- 확신도 0.8 미만이면 AI 답을 **쓰지 않는다.** 키워드 규칙이라는 결정적 대체 경로로
  간다. 되물어볼 사람이 없으므로 확신 없는 추측을 확정값으로 쓰면 통계가 조용히 오염된다.
- 분류 실패는 심사를 막지 않는다 — '기타'로 채우고 진행한다. 카테고리는 안전 문제가
  아니라 분류 문제라, 이것 때문에 관리자를 부르면 과잉 보류가 된다.

**값이 채워져 와도 라벨은 AI가 확정한다.** 채워져 오는 값의 대부분은 우리가 지난 심사
콜백(suggestedCategory)으로 내보낸 것이 재심사 때 되돌아온 에코라 이상 신호가 아니다 —
경고는 **AI의 이번 판단과 다를 때만** 남긴다 (리뷰 3번, normalize_expense_category와
같은 눈높이: 아는 값은 조용히, 신호일 때만 소리 낸다).
(종전의 `_check_category_mismatch`는 사용자 선택이 있던 시절의 대조 장치라 제거했다.
`guardrail_gate`의 `category_mismatch` 규칙·state 필드도 함께 제거 — 2026-08-06 팀장 승인.)

- 카탈로그: templates/category_catalog.yaml (tools/category_catalog.py가 로드)

목 모드: 카탈로그의 키워드 규칙 기반 결정적 분류.
실모드: gpt-4o-mini 구조화 출력 — 후보 9종을 프롬프트에 강제하고, 목록 밖 답변은
        코드가 키워드 분류로 교정 (환각 카테고리 차단).
"""
import logging

from pydantic import BaseModel

from app.graphs.review.state import ReviewState
from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.tools.category_catalog import (
    all_categories, classify_by_keywords, fallback_category, keyword_category_or_none,
)

logger = logging.getLogger(__name__)

# 분류 결과를 그대로 확정값으로 쓰기 위한 최소 확신도. 미만이면 키워드 규칙으로
# 폴백한다(미적중이면 '기타').
#
# 카테고리 직접 입력이 없어지면서 AI가 유일한 출처가 됐기 때문에 넣었다. 저확신
# 추측을 확정값으로 쓰면 통계가 조용히 오염되는데, 그 시점엔 되물어볼 사람이 없다.
# 키워드 규칙을 폴백으로 고른 이유는 **결정적**이라서다 — 같은 지출이 매번 같은
# 카테고리로 가야 카테고리별 집계가 의미를 갖는다. 실측 정확도도 낮지 않다
# (17케이스 키워드 단독 88.2%, scripts/ab_classifier.py).
#
# 에스컬레이션은 하지 않는다. 카테고리는 안전 문제가 아니라 분류 문제이고, 이것 때문에
# 관리자를 부르면 과잉 보류가 된다.
CLASSIFY_MIN_CONFIDENCE = 0.8


class CategoryPrediction(BaseModel):
    category: str
    confidence: float = 1.0


async def classify_category(state: ReviewState) -> dict:
    """지출 카테고리를 AI가 정한다 — **항상 실행된다** (T7, 2026-08-06).

    종전에는 `claim.category`에 값이 있으면 분류를 건너뛰고 그 값을 존중했다. 사용자가
    화면에서 카테고리를 고르던 시절의 동작이다. 8/4 회의로 **사용자 선택 기능이
    삭제**되면서 AI 분류가 유일한 출처가 됐고, 백엔드도 `expenses.category`를 nullable로
    바꿔 항상 빈 값으로 보내기로 회신했다(2026-08-06).

    다만 **값이 채워져 오는 것 자체는 이상 신호가 아니다** (리뷰 3번, 2026-08-06).
    백엔드는 첫 심사 콜백의 suggestedCategory로 `expenses.category`를 채우므로, 같은
    지출을 두 번째로 심사하는 모든 경로에서 **우리가 지난번에 확정한 값이 되돌아온다.**
    읽기 경계 정규화(0155ad9·3b70de5) 덕에 들어올 수 있는 값은 9종뿐이다. 그래서
    무조건 경고하지 않고, **AI의 이번 판단과 다를 때만** 경고한다 — 같으면 재심사
    에코가 정상 확인된 것이고, 다르면 사람이 봐야 할 신호(분류 흔들림 또는 구화면
    입력)다. 어느 쪽이든 라벨은 AI 값으로 확정한다.
    """
    claim = state["claim"]
    candidates = all_categories()
    incoming = claim.category  # 재심사 에코(대부분) 또는 구화면 입력 — 분류 후 대조용
    # 영수증에서 읽은 **상호명·품목을 분류 근거에 넣는다** (2026-08-06).
    # 사용자 카테고리 입력이 사라진 뒤 제목이 "6월 모임"·"물품"처럼 엉성하게 오는 것이
    # 실측으로 확인됐다. 상호("○○펜션")·품목이 제목보다 강한 단서인 경우가 많다.
    # 영수증이 없거나 판독 실패면 종전과 같이 제목·설명만으로 분류한다(fail-open).
    receipt = state.get("receipt_data")
    hints = []
    if receipt is not None and receipt.parse_ok:
        if receipt.merchant:
            hints.append(receipt.merchant)
        hints.extend(receipt.items or [])
    text = " ".join([claim.title, claim.description, *hints]).strip()

    llm_meta = {}
    try:
        spec = load_prompt("classifier")
        pred, meta = await chat_structured(
            agent="classifier",
            system=spec.system_with_few_shot(),
            user=f"카테고리 후보(이 중에서만 선택): {', '.join(candidates)}\n\n"
                 f"지출 내용: {text}",
            schema=CategoryPrediction,
            mock_response=CategoryPrediction(category=classify_by_keywords(text)),
            mask_with=state.get("team_members") or [],
            prompt_version=spec.version,
        )
        llm_meta = {"classifier": meta}
        fallback = fallback_category()
        if pred.category not in candidates:
            # 환각 카테고리 — 코드가 키워드 규칙으로 교정한다
            logger.warning("classifier가 후보 밖 값을 냈다: %r — 키워드로 교정", pred.category)
            category = classify_by_keywords(text)
        elif pred.confidence < CLASSIFY_MIN_CONFIDENCE:
            # 저확신 — 결정적 규칙으로 폴백. AI가 유일한 출처라 추측을 확정값으로
            # 쓰지 않는다(위 상수 주석 참조).
            category = classify_by_keywords(text)
            logger.info("classifier 저확신(%.2f) — 키워드 폴백: %s → %s",
                        pred.confidence, pred.category, category)
        elif pred.category == fallback and (kw := keyword_category_or_none(text)):
            # **'기타'는 확신도와 무관하게 키워드에게 한 번 더 묻는다 (2026-08-06 실측 발견).**
            #
            # 저확신 폴백만으로는 안 걸리는 구멍이 있었다. '기타'가 카탈로그의 정식
            # 후보라서, 모델은 모를 때 "모르겠다"(저확신) 대신 **"기타"라고 확신 있게**
            # 답한다. 엉성한 제목 20건 실측에서 11건이 기타로 갔고, 그중 `대관료`·
            # `비품 구매`처럼 **카탈로그에 키워드가 버젓이 있는 것들**까지 기타가 됐다.
            # 확신도가 0.85라 폴백 문턱(0.8)을 넘어 키워드는 볼 기회조차 없었다.
            #
            # 그래서 '기타'를 "분류 결과"가 아니라 "모르겠다는 신호"로 취급한다. 키워드가
            # 아는 것이 있으면 그것을 쓰고, 키워드도 모르면 그때 비로소 기타로 남긴다.
            # 키워드에서 '구입'처럼 아무 데나 붙는 낱말을 걷어냈기에 이 위임이 안전하다.
            category = kw
            logger.info("classifier가 '기타'로 답했으나 키워드가 안다 — %s로 교정", kw)
        else:
            category = pred.category
    except Exception:
        logger.exception("classify_category failed — '기타'로 폴백")
        category = fallback_category()

    if incoming and incoming != category:
        # 사람이 봐야 할 신호만 경고로: 이전 확정값(또는 구화면 입력)과 이번 AI 판단이
        # 갈렸다 — 분류가 흔들리거나 프론트가 아직 카테고리 입력을 보내는 경우다.
        logger.warning(
            "들어온 category(%r)와 AI 분류(%r)가 다르다 — AI 값으로 덮는다 (expense=%s)",
            incoming, category, state.get("expense_id"),
        )
    elif incoming:
        # 재심사 에코 — 우리가 지난 심사에서 내보낸 값이 그대로 재확정됐다. 정상.
        logger.debug("category 재심사 에코 일치: %r (expense=%s)",
                     incoming, state.get("expense_id"))

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai", "llm_meta": llm_meta}
