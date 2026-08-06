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

**값이 채워져 오면** 화면에 입력 수단이 없으므로 계약 위반이다. 존중하지 않고 AI 분류로
덮되 경고 로그를 남긴다 — 조용히 덮으면 계약이 어긋난 사실 자체가 묻힌다.
(종전의 `_check_category_mismatch`는 사용자 선택이 있던 시절의 대조 장치라 제거했다.
`guardrail_gate`의 `category_mismatch` 규칙은 이제 아무도 세우지 않는다 — 그 파일은
소유가 갈려 있어 제거 여부는 팀장 판단으로 남긴다.)

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
    all_categories, classify_by_keywords, fallback_category,
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

    그래서 값이 채워져 오는 것은 **더 이상 정상 경로가 아니다.** 화면에 입력 수단이
    없는데 값이 왔다는 건 어딘가 잘못됐다는 뜻이라, 존중하지 않고 AI 분류로 덮되
    **경고 로그를 남긴다** — 조용히 덮으면 계약이 어긋난 사실 자체가 묻힌다.
    """
    claim = state["claim"]
    candidates = all_categories()
    if claim.category:
        logger.warning(
            "지출에 category가 채워져 왔다 — 화면에 입력 수단이 없으므로 계약 위반이다. "
            "AI 분류로 덮는다 (받은 값: %r, expense=%s)",
            claim.category, state.get("expense_id"),
        )
    text = f"{claim.title} {claim.description}"

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
        else:
            category = pred.category
    except Exception:
        logger.exception("classify_category failed — '기타'로 폴백")
        category = fallback_category()

    return {"claim": claim.model_copy(update={"category": category}),
            "category_source": "ai", "llm_meta": llm_meta}
