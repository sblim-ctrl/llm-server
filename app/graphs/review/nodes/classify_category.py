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
- 분류 실패는 심사를 막지 않는다 — 이전 확정값이나 키워드 규칙으로 채우고 진행한다.
  카테고리는 안전 문제가 아니라 분류 문제라, 이것 때문에 관리자를 부르면 과잉 보류가 된다.
  단 **실패가 확정값을 파괴하지는 않는다** — 아래 except 절 주석 참조 (리뷰 ③).

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
# (17케이스 키워드 단독 16/17=94.1%, scripts/ab_classifier.py — '구입' 제거로
#  '농구공 5개 구입'이 기타로 가는 1건은 의도된 교환, 카탈로그 주석 참조).
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
    # 영수증에서 읽은 **상호명·품목은 LLM 입력에만** 넣는다 (B-1, 2026-08-06 리뷰).
    #
    # 제목이 "6월 모임"처럼 엉성할 때 상호("○○펜션")가 가장 강한 단서라는 실측은
    # 유효하다(8건 중 5건 기타 탈출). 단 그 단서를 해석할 수 있는 건 문맥을 읽는
    # LLM뿐이다. 키워드 매칭은 부분 문자열이라 상호명에 안전하지 않다 — 상호는 업종과
    # 무관한 낱말을 흔히 품는다('OO화원 플라워카페'의 카페→식비, '카페24'(호스팅),
    # '여행박사'). 실제로 '회원 경조사 조화'(팀 합의: 기타)를 상호의 '카페' 두 글자가
    # 식비로 뒤집었다. 그래서 키워드 계열(환각 교정·저확신 폴백·기타 재질의)은 전부
    # **사용자가 쓴 제목·설명(user_text)만** 본다. 영수증이 없거나 판독 실패면 종전과
    # 같이 제목·설명만으로 분류한다(fail-open).
    receipt = state.get("receipt_data")
    hints = []
    if receipt is not None and receipt.parse_ok:
        if receipt.merchant:
            hints.append(receipt.merchant)
        hints.extend(receipt.items or [])
    user_text = f"{claim.title} {claim.description}".strip()  # 키워드 매칭 전용
    text = " ".join([user_text, *hints]).strip()              # LLM 입력 전용

    llm_meta = {}
    llm_failed = False   # 예외 경로 표식 — 아래 로그가 원인(분류기 장애)을 가리지 않게 한다
    try:
        spec = load_prompt("classifier")
        pred, meta = await chat_structured(
            agent="classifier",
            system=spec.system_with_few_shot(),
            user=f"카테고리 후보(이 중에서만 선택): {', '.join(candidates)}\n\n"
                 f"지출 내용: {text}",
            schema=CategoryPrediction,
            # 목 응답도 **키워드 매처**이므로 user_text만 본다 (B-1 후속, 리뷰 ② 지적).
            # `text`(상호명 포함)를 넘기면 목이 상호를 해석하는 척하게 되는데, 부분 문자열
            # 매칭에는 그 능력이 없어 이득 없이 오탐만 물려받는다('플라워카페'→식비).
            # confidence 기본값이 1.0이라 그 답은 고확신으로 통과해 곧장 확정된다.
            # 목 모드는 골든셋·데모가 도는 모드라, 여기서 굳으면 실모드가 내지 않을 답이
            # 기대값으로 박힌다(T9 골든셋 재설계가 이 PR 직후라 특히 중요).
            mock_response=CategoryPrediction(category=classify_by_keywords(user_text)),
            mask_with=state.get("team_members") or [],
            prompt_version=spec.version,
        )
        llm_meta = {"classifier": meta}
        fallback = fallback_category()
        if pred.category not in candidates:
            # 환각 카테고리 — 코드가 키워드 규칙으로 교정한다 (근거: 제목·설명만)
            logger.warning("classifier가 후보 밖 값을 냈다: %r — 키워드로 교정", pred.category)
            category = classify_by_keywords(user_text)
        elif pred.confidence < CLASSIFY_MIN_CONFIDENCE:
            # 저확신 — 결정적 규칙으로 폴백. AI가 유일한 출처라 추측을 확정값으로
            # 쓰지 않는다(위 상수 주석 참조).
            category = classify_by_keywords(user_text)
            logger.info("classifier 저확신(%.2f) — 키워드 폴백(제목·설명 기준): %s → %s",
                        pred.confidence, pred.category, category)
        elif pred.category == fallback and (kw := keyword_category_or_none(user_text)):
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
            # 이 위임이 안전한 조건 두 가지: '구입'처럼 아무 데나 붙는 낱말을 걷어냈고
            # (카탈로그), 조회 대상이 사용자가 쓴 제목·설명뿐이다(상호명 금지 — B-1).
            category = kw
            logger.info("classifier가 '기타'로 답했으나 키워드가 안다 — %s로 교정 "
                        "(근거: 제목·설명 키워드 — 영수증 상호는 쓰지 않음)", kw)
        else:
            category = pred.category
    except Exception:
        # **확정값을 파괴하지 않는다** (리뷰 ③, 2026-08-06). 종전에는 무조건 '기타'로
        # 떨어져서, 지난 심사에서 확정한 카테고리가 LLM 일시 장애 한 번으로 '기타'가
        # 되고 그 값이 판례 임베딩·콜백 suggestedCategory로 나갔다 — 되돌릴 경로가 없다.
        #
        # 없으면 키워드 규칙으로 간다. 전면 장애는 저확신의 극단이고, 이 파일은 이미
        # 저확신에서 결정적 규칙으로 폴백한다(위 분기) — 같은 원칙을 여기에도 적용한다.
        # 키워드도 모르면 classify_by_keywords가 '기타'를 돌려주므로 종전 동작이 하한이다.
        #
        # **incoming은 후보 안에서만 신뢰한다.** 이 절은 LLM을 못 불렀으므로 위쪽의
        # `pred.category not in candidates` 방어를 통과하지 않는다 — 검증 없이 쓰면
        # 카탈로그 밖 값이 그대로 확정돼 이 파일의 불변식("9종 밖 값은 절대 만들지
        # 않는다")이 예외 경로에서만 뚫린다. 목 모드는 읽기 경계 정규화를 적용하지
        # 않으므로(골든셋 규약 보존, 3b70de5) `다과`·`대관` 같은 구 어휘가 실제로 온다.
        logger.exception("classify_category failed — 확정값 유지 또는 키워드 폴백")
        category = (incoming if incoming in candidates else None) or classify_by_keywords(user_text)
        llm_failed = True

    if incoming and incoming != category:
        # 사람이 봐야 할 신호만 경고로: 이전 확정값(또는 구화면 입력)과 이번 AI 판단이
        # 갈렸다 — 분류가 흔들리거나 프론트가 아직 카테고리 입력을 보내는 경우다.
        logger.warning(
            "들어온 category(%r)와 AI 분류(%r)가 다르다 — AI 값으로 덮는다 (expense=%s)",
            incoming, category, state.get("expense_id"),
        )
    elif incoming and llm_failed:
        # 값은 같지만 **재확정된 것이 아니다** — 분류기를 못 불러 이전 값을 그대로 들고
        # 나갔다. 여기서 '에코 일치·정상'을 찍으면 관측이 원인을 가린다(장애가 정상으로
        # 보인다). 값이 맞다는 것과 검증됐다는 것은 다르다.
        logger.warning("category %r 유지 — 분류기 장애로 재확정하지 못했다 (expense=%s)",
                       incoming, state.get("expense_id"))
    elif incoming:
        # 재심사 에코 — 우리가 지난 심사에서 내보낸 값이 그대로 재확정됐다. 정상.
        logger.debug("category 재심사 에코 일치: %r (expense=%s)",
                     incoming, state.get("expense_id"))

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai", "llm_meta": llm_meta}
