"""PolicyDrafter — 마법사 1~3단계 통합 요청 (REQ-036, §4.4-c · LLM-005 전면 개정).

[팀 결정 2026-07-09] AI가 카테고리별 예산을 배분하는 기능은 제거 —
예산 현황은 지난 지출 내역 기반으로 표시(ReportWriter 담당).
[개정 2026-08-05] 승인 정책 제안(policy_params)도 제거 — 기준 금액은 마법사 2단계
사용자 입력이 원천이라 LLM이 제안할 것이 없다. 회칙 초안은 rule_source=ai일 때만
생성하고, 그 외(file·manual·skip)는 빈 rules로 응답한다 (API 명세서 개정안 §1).

패턴: 템플릿 로드 → 생성 → 검증(Generator-Evaluator, 강의 12-03).
한도 수치는 코드가 계산하고, LLM은 문구 다듬기만 담당한다.

동기 실행: 마법사 UX상 즉시 응답이 필요해 llm-api가 직접 이 그래프를 호출한다
(§2.2 'LLM 호출은 워커만' 원칙의 예외 — §7.2가 동기로 명시. 지연 문제 생기면 잡 전환).
"""

import logging
import re

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.llm.client import chat_structured
from app.llm.prompts import load_prompt
from app.schemas.writers import PolicyDraft, PolicyDraftRequest
from app.tools.category_catalog import all_categories

# 템플릿 로더는 심사 쪽 기본 정책 모드와 공유한다 (app/tools/policy_defaults.py) —
# 같은 YAML을 두 군데서 따로 읽지 않기 위해서다. 재수출이라 기존 import 경로도 유효.
from app.tools.policy_defaults import load_templates
from app.tools.search_references import search_references

logger = logging.getLogger(__name__)

# 추가 조항 상한 — 천장이지 목표가 아니다(프롬프트가 "빠짐없이, 단 중복·일반론 금지"로
# 실제 개수를 조절).
#
# **2026-08-12부터 유형별로 다르다.** 값은 템플릿의 `max_extra_rules`에 있고
# (`extra_rules_cap` 참조) 이 상수는 키가 없는 유형의 기본값일 뿐이다. 유형별로 나눈
# 이유는 사용자 피드백이다 — "친목 같은 모임에 회사와 같은 분량의 회칙이 나올 필요가
# 없다". 기본 조 수도 함께 줄여(친목 18→7 … 회사 16→11) 총 분량이 유형에 따라 갈린다:
#
#     친목 7+2=9 / 스터디 8+3=11 / 동아리 9+4=13 / 동호회 9+4=13 / 회사 11+4=15
#
# 종전에는 기본 16~18조 + 상한 10 공통이라 **어떤 유형이든 26~28조**가 나갈 수 있었다.
#
# **이 주석의 숫자는 템플릿과 함께 고쳐야 한다.** 상한만 바꾸고 주석을 두고 온 적이
# 있고(PR #65 리뷰 N2), 그전에도 같은 계열의 지적이 있었다(PR #9 리뷰 D6).
# 실제 조 수·글자 수는 `test_bylaw_length_by_team_type`이 지킨다.
MAX_EXTRA_RULES = 10


def extra_rules_cap(template: dict) -> int:
    """이 유형의 AI 맞춤 조항 상한. 템플릿에 없으면 전역 기본값.

    §12 원칙(유형 조정은 YAML만 고친다)을 지키려고 코드에 유형별 숫자를 두지 않는다 —
    `suggested_limits`가 비율·상하한을 YAML에서 읽는 것과 같은 이유다.
    """
    return int(template.get("max_extra_rules", MAX_EXTRA_RULES))


class ExtraRule(BaseModel):
    """LLM이 제안하는 추가 조 하나 — 기본 조항과 같은 형식으로 렌더링하기 위해 제목을 분리한다.

    외부 계약(`PolicyDraft.rules: list[str]`)은 그대로다 — 이 구조는 조립 과정에서만
    쓰이고 화면에는 "제N조(제목) 본문" 한 줄로 나간다.
    """

    title: str
    text: str

    def rendered(self) -> str:
        """조 번호를 뺀 "(제목) 본문" — 번호는 기본 조항 개수에 이어 조립부가 붙인다."""
        return f"({self.title.strip()}) {self.text.strip()}"


class ExtraRules(BaseModel):
    extra_rules: list[ExtraRule] = []


def normalize_rule(rule: str) -> str:
    """조항 비교용 정규화 — 공백·문장부호만 다른 사실상 같은 조항을 같게 본다.

    LLM 추가 조항이 기본 조항을 살짝 바꿔 되풀이하는 일이 잦은데(예: 조사·쉼표 차이),
    표면 문자열 비교로는 걸러지지 않아 초안에 같은 말이 두 번 실린다.
    """
    return re.sub(r"[\s·,.()\[\]'\"]+", "", rule)


def dedupe_rules(base: list[str], extra: list[str]) -> list[str]:
    """기본 조항과 겹치거나 자기들끼리 겹치는 추가 조항을 버린다. 순서 보존.

    빈 조항·공백뿐인 조항도 여기서 떨어진다 — LLM이 빈 문자열을 섞어 보내는 경우가 있다.
    """
    seen = {normalize_rule(r) for r in base}
    out: list[str] = []
    for rule in extra:
        cleaned = rule.strip()
        key = normalize_rule(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


# notes의 회비 표기. verify가 이 조각으로 '회비가 조항과 정합한지'를 판별하므로 상수로 둔다
# — 단순히 notes에 '회비'가 있는지 보면 모임 이름('무회비 동아리' 등)에 걸려 오탐한다.
DUES_NOTE = " · 회비 {dues}원"
# 회비 조항을 식별하는 문구. 템플릿(bylaw_articles)의 회비 조 본문이 이 말로 시작한다.
DUES_MARK = "회비는 1인당 "


#: 회칙에 쓰면 안 되는 **금액·정도의 모호어**. 심사관이 판단할 수 없는 말이라 조항이
#: 기준으로 기능하지 못한다("소액 선물은 인정한다" → 얼마까지가 소액인가?).
#:
#: v5 프롬프트가 이미 금지하지만 LLM이 지키지 않는 것을 실측으로 확인했다(2026-08-11:
#: 친목 초안에 "소액 선물" 조항이 나왔고, 그것도 템플릿의 경조사비 조와 내용이 겹쳤다).
#: 프롬프트만으로는 못 막는 계열이라 코드에서 한 번 더 거른다 — 이 프로젝트에서 반복된
#: "규칙보다 예시가 세다"의 다른 얼굴이다.
#:
#: **의도적으로 좁게 잡았다.** "충분한"(잔액이 충분한 = 잔액 ≥ 청구액, 사실 조건)과
#: "필요한 경우"(절차 조건)는 우리 템플릿이 정당하게 쓰고 있어 넣지 않는다. 금액이
#: 들어갈 자리를 형용사로 때우는 말만 막는다.
VAGUE_AMOUNT_TERMS = (
    "소액", "고액", "고가", "적절한", "적절히", "적당한", "적당히",
    "상당한", "과도한", "알맞은", "합리적인", "저렴한", "소정의",
)


#: limits 키 → 회칙에 쓰는 항목 이름. LLM에게 한도 표를 보여줄 때 쓴다.
LIMIT_LABELS = {
    "meal": "식비(1인 1회)", "venue": "장소 대관비(회당)", "supplies": "비품비(분기)",
    "transport": "교통비(1인당)", "education": "교육비(1인당)",
    "event": "행사·활동비(건당)", "gift": "경조사비(1건)", "travel": "여행·숙박(1인 1박)",
}


def unknown_amounts_in(text: str, allowed: set[int]) -> list[int]:
    """조항이 인용한 금액 중 허용 목록(회칙 한도·승인 기준)에 없는 것.

    LLM이 한도를 지어내면 회칙 안에서 숫자가 갈린다. 프롬프트로 금지하고 한도 표까지
    주지만, 실측에서 프롬프트만으로는 안 지켜지는 계열임이 반복 확인돼(모호어와 같은
    유형) 조립 단계에서 한 번 더 거른다.
    """
    return [a for a in _amounts_in(text) if a not in allowed]


def vague_terms_in(text: str) -> list[str]:
    """조항에 들어간 금액 모호어 목록 (없으면 빈 목록)."""
    return [w for w in VAGUE_AMOUNT_TERMS if w in text]


def drop_vague_rules(rules: list[str]) -> tuple[list[str], list[str]]:
    """모호어가 든 조항을 떨어뜨린다. (남길 것, 버린 것) 반환.

    초안 전체를 불통과시키지 않고 해당 조만 버리는 이유: 이 API는 마법사가 동기로
    부르는 자리라 검증 실패가 5xx가 된다(모듈 docstring 참조). 기본 조항은 우리가
    쓴 것이라 이미 깨끗하고(테스트로 고정), 위험한 것은 LLM 조항뿐이므로 그것만
    버리면 초안은 여전히 완결된 회칙으로 남는다.
    """
    keep, dropped = [], []
    for rule in rules:
        (dropped if vague_terms_in(rule) else keep).append(rule)
    return keep, dropped


def article_text(article: dict, *, has_auto_range: bool) -> str:
    """조 본문 — 자동 승인 구간이 없으면(기준 금액 0) `text_no_auto`를 우선 쓴다.

    기준 금액 0은 화면의 '모든 지출을 직접 확인' 토글이다(schemas/writers 참조).
    그때 기본 문구를 그대로 치환하면 "1건 0원 미만의 지출은 AI가 자동 심사한다"처럼
    **존재할 수 없는 금액 구간**을 말하는 조가 된다. 확정된 회칙은 인덱싱되어 심사
    근거가 되므로(effective_dues 참조) 공허한 조항을 남기지 않는다.

    `requires_dues`처럼 YAML 플래그로 둔 이유도 같다 — 문구 검색으로 갈라내면 표현이
    바뀔 때 조용히 새고, 유형마다 어미가 달라(회사는 '규정'·'책임자') 코드에서
    문장을 만들면 유형별 어투가 깨진다.
    """
    if not has_auto_range and (alt := article.get("text_no_auto")):
        return alt
    return article["text"]


def _article_applies(article: dict, dues: int) -> bool:
    """`requires_dues: true`인 조는 회비 입력이 없으면 통째로 뺀다.

    회비 조뿐 아니라 '회비를 기한 내 납부한다', '잔여 회비를 이월한다'처럼 **회비가
    있다는 것을 전제하는 의무 조항**이 여기 해당한다. 회비를 정한 적 없는 모임에
    그런 조항을 만들어 주면 회칙이 사실과 다른 의무를 부과하게 된다(2026-08-11).
    템플릿에 플래그로 표시하는 이유는 문구 검색으로 걸러면 표현이 바뀔 때마다
    조용히 새는 자리이기 때문이다.
    """
    return dues > 0 or not article.get("requires_dues")


def _round_to(amount: float, unit: int = 1_000) -> int:
    """단위 반올림 (하한은 unit)."""
    return max(unit, int(round(amount / unit)) * unit)


def _bylaw_unit(amount: float) -> int:
    """round_bylaw_amount가 쓰는 반올림 단위 — 하한 올림에서도 같은 단위를 써야 한다."""
    if amount < 50_000:
        return 5_000
    if amount < 200_000:
        return 10_000
    return 50_000


def round_bylaw_amount_up(amount: float) -> int:
    """같은 단위로 **올림** — 선언한 하한을 반올림이 깎지 않도록 쓰는 짝 함수.

    `round_bylaw_amount`는 가까운 쪽으로 붙이므로 12,000원처럼 단위의 배수가 아닌
    값은 10,000원으로 내려간다. 한도의 `min`은 "이보다 낮게는 주지 않는다"는 선언이라
    내림이 적용되면 안 된다 (PR #65 리뷰 N1).
    """
    unit = _bylaw_unit(amount)
    return max(unit, -(-int(amount) // unit) * unit)


def round_bylaw_amount(amount: float) -> int:
    """회칙에 적을 금액으로 반올림 — **금액 크기에 따라 단위를 키운다**.

    사람이 쓴 규정은 19,000원·48,000원·320,000원처럼 적지 않는다. 자릿수가 올라갈수록
    끝자리가 둥글어지는 것이 자연스럽다(2026-08-11 지적):
        5만 미만   → 5,000원 단위   (19,000 → 20,000)
        20만 미만  → 10,000원 단위  (48,000 → 50,000)
        20만 이상  → 50,000원 단위  (320,000 → 300,000)
    """
    return _round_to(amount, _bylaw_unit(amount))


def suggested_limits(template: dict, initial_budget: int, member_count: int | None) -> dict[str, str]:
    """카테고리별 한도 앵커를 예산·인원에서 산출 (결정적 — LLM 아님).

    종전에는 `PER_MEAL_LIMIT = 30_000` 상수 하나가 유형·예산·인원과 무관하게 쓰였다.
    예산 30만원 모임과 1,000만원 모임에 같은 한도가 나가던 자리다.

    비율·상하한은 유형별로 `templates/policy_templates.yaml`의 `limits`에 있다 —
    §12 원칙(유형 조정은 YAML만 고친다)을 지키기 위해 코드에 숫자를 두지 않는다.
    basis=per_person이면 1인당 예산 기준, total이면 총예산 기준이다.
    """
    n = max(member_count or 1, 1)
    per_person = initial_budget / n
    out: dict[str, str] = {}
    for key, cfg in (template.get("limits") or {}).items():
        basis = per_person if cfg.get("basis") == "per_person" else initial_budget
        raw = basis * float(cfg.get("ratio", 0))
        clamped = min(max(raw, cfg.get("min", 0)), cfg.get("max", raw or 0))
        # 반올림이 상한을 넘지 않게 상한도 같은 규칙으로 둥글린 값과 비교한다
        rounded = min(round_bylaw_amount(clamped), round_bylaw_amount(cfg.get("max", clamped)))
        # 반올림이 **하한을 깎는 것**은 막는다 — min은 "이보다 낮게는 주지 않는다"는
        # 선언이라 내림이 적용되면 안 된다. 예: meal.min=12,000이 5,000 단위 반올림으로
        # 10,000이 되던 자리(동아리·동호회, PR #65 리뷰 N1). 하한만 올림으로 맞춘다.
        if (floor := cfg.get("min")) and rounded < floor:
            rounded = round_bylaw_amount_up(floor)
        out[key] = f"{rounded:,}"
    return out


def effective_dues(req_dues: int | None) -> int:
    """회칙에 적을 회비 — **사용자 입력이 유일한 원천**이다. 입력이 없으면 회비 조를 뺀다.

    한때(2026-08-11 오전) 입력이 없으면 유형별 기본값을 인원·예산으로 보정해 제안했다.
    같은 날 되돌렸다. 이유는 두 가지다.

    ① **관리자가 정한 적 없는 금액을 회칙이 단정하게 된다.** 관리자가 화면에서 그 값을
       입력하지 않는 한 실제 설정에는 반영되지 않으므로, 회칙 문서와 시스템 설정이
       처음부터 어긋난 채로 시작한다.
    ② 확정된 회칙은 인덱싱되어 rule_auditor의 판정 근거가 된다 — 지어낸 금액이 심사
       근거로 굳는 경로다.

    승인 기준 금액도 같은 이유로 회칙 조항에서 숫자를 뺐다(templates 참조).
    """
    return req_dues or 0


class DraftState(TypedDict, total=False):
    request: PolicyDraftRequest
    template: dict
    references: list[dict]
    draft: PolicyDraft
    verified: bool
    verify_error: str | None


async def load_template(state: DraftState) -> dict:
    req = state["request"]
    template = load_templates()[req.team_type]
    return {"template": template}


async def retrieve_references(state: DraftState) -> dict:
    """참고 규정 문서 검색 (RAG) — 생성 전 근거 자료 확보.

    검색 실패는 생성 자체를 막지 않는다 — 참고자료 없이도 기본 템플릿으로
    진행 가능하므로 fail-open. (강의 08 Agentic RAG 패턴)
    """
    req = state["request"]
    if req.rule_source != "ai":
        return {"references": []}  # 초안을 만들지 않으므로 검색 불필요
    query = f"{req.team_type} {req.description}".strip()
    try:
        refs = await search_references(query)
    except Exception:
        logger.exception("search_references failed — 참고자료 없이 진행")
        refs = []
    return {"references": refs}


def _mock_extra_rules(description: str, cap: int = MAX_EXTRA_RULES) -> list[ExtraRule]:
    """목 모드 휴리스틱 — 소개 문구 키워드 기반 추가 조항 제안. 소개 없으면 빈 목록."""
    if not description:
        return []
    text = description.lower()
    rules: list[ExtraRule] = []
    if any(k in text for k in ("등산", "캠핑", "액티비티", "레저", "운동")):
        rules.append(ExtraRule(
            title="안전 장비",
            text="야외·활동성 행사에 필요한 안전장비(구급용품 등) 구입은 활동 안전을 위한 지출로 우선 인정한다.",
        ))
    if any(k in text for k in ("스터디", "개발", "코딩", "프로젝트", "실습")):
        rules.append(ExtraRule(
            title="실습 인프라",
            text="실습에 필요한 서버·도메인·구독형 개발 도구 비용은 스터디 기간 내 결제분만 인정한다.",
        ))
    if any(k in text for k in ("신입", "모집", "홍보", "리크루팅")):
        rules.append(ExtraRule(
            title="모집 홍보",
            text="신입 모집 관련 홍보물 제작비는 모집 기간 내 집행 건에 한해 인정한다.",
        ))
    return rules[:cap]


# rule_source별 notes 문구 — ai가 아니면 초안 없이 안내만 돌려준다.
_NON_AI_NOTES = {
    "skip": "회칙 없이 시작 — 기본 정책 모드로 심사합니다.",
    "manual": "직접 입력한 회칙을 사용합니다 — 저장 후 회칙 변경 알림(LLM-006)이 심사에 반영합니다.",
    "file": "업로드한 회칙 파일을 사용합니다 — 저장 후 회칙 변경 알림(LLM-006)이 심사에 반영합니다.",
}


async def generate_draft(state: DraftState) -> dict:
    """초안 조립. 기준 금액은 요청 값 그대로, 기본 조항은 템플릿 + 치환.

    rule_source가 ai가 아니면(파일·직접 입력·건너뛰기) 회칙 초안을 만들지 않는다 —
    rules는 빈 배열이고 LLM·RAG도 타지 않는다 (개정안 §1-4). 회비 조각도 notes에
    붙이지 않는다 — 회칙 조항이 없으므로 notes에도 표기가 없어야 verify의 정합
    검사와 맞는다 (회비 반영은 ai 초안 경로의 몫).

    ai 경로: 모임 소개가 있으면 LLM이 그 모임 특성에 맞는 추가 조항(최대
    유형별 `max_extra_rules`개)을 제안한다. 소개가 없으면 LLM을 호출하지 않아 기본 조항만
    남는다. 기본 조항은 LLM이 절대 건드리지 않음 — 필수 조항 보장은 코드 검증
    (verify_draft)의 책임으로 유지하기 위해서다.
    """
    req, template = state["request"], state["template"]

    if req.rule_source != "ai":
        draft = PolicyDraft(
            rules=[],
            recommended_categories=all_categories(),
            notes=f"'{req.team_name}' ({req.team_type}) — {_NON_AI_NOTES[req.rule_source]}",
        )
        return {"draft": draft}

    # 기준 금액 하나가 회칙의 승인 기준선이 된다. 템플릿 placeholder 이름은
    # {auto_approve_limit}지만 넣는 값은 요청의 force_escalation_amount다 —
    # 백엔드가 auto_approve_limit = escalation_threshold = 기준금액으로 저장하므로
    # (개정안 §1-3 저장 규약) 두 이름은 같은 금액을 가리킨다.
    limits = suggested_limits(template, req.initial_budget, req.member_count)
    dues = effective_dues(req.dues)
    # 기준 금액 0 = 자동 승인 구간이 아예 없다(전건 관리자 확인). 조 문구도 프롬프트도
    # 금액 구간을 말하면 안 된다 — article_text 참조.
    has_auto_range = req.force_escalation_amount > 0
    fmt = {
        "auto_approve_limit": f"{req.force_escalation_amount:,}",
        "dues": f"{dues:,}",
        "dues_period": template.get("dues_period", ""),
        **limits,
    }
    # 회칙 초안은 bylaw_articles를 쓴다 — base_rules는 심사용(회칙 미등록 팀의 기본
    # 정책 모드)이라 짧게 유지된다. 두 용도를 한 목록으로 쓰던 것을 2026-08-11에
    # 분리했다: 초안을 실제 회칙처럼 늘리면 심사 근거까지 같이 늘어나던 구조였다.
    articles = [a for a in template["bylaw_articles"] if _article_applies(a, dues)]
    base_rules = [f"제{i}조({a['title']}) {article_text(a, has_auto_range=has_auto_range).format(**fmt)}"
                  for i, a in enumerate(articles, start=1)]

    extra_rules: list[str] = []
    cap = extra_rules_cap(template)
    if req.description:
        refs = state.get("references") or []
        ref_text = "\n".join(f"- {r['text']}" for r in refs) or "(참고자료 없음)"
        try:
            spec = load_prompt("policy_drafter")
            result, _meta = await chat_structured(
                agent="policy_drafter",
                system=spec.system_with_few_shot(),
                user=f"모임 유형: {req.team_type}\n모임 이름: {req.team_name}\n"
                f"모임 소개: {req.description}\n"
                f"회원 수: {req.member_count or '미입력'}\n"
                f"총예산: {req.initial_budget:,}원\n"
                # 0원을 그대로 적으면 LLM이 "0원 이상은 관리자 승인" 같은 조를 쓴다 —
                # 인용 가능한 기준 금액이 없다는 사실을 말로 알린다 (#75).
                + (f"관리자 승인 기준 금액: {req.force_escalation_amount:,}원\n"
                   if has_auto_range else
                   "관리자 승인: 모든 지출이 금액과 관계없이 관리자 승인 대상입니다"
                   " — 자동 승인 구간이 없으므로 승인 기준 금액을 조항에 쓰지 마세요.\n")
                # 유형별 상한을 말로 알린다 — 실제 절단은 아래 `fresh[:cap]`이 하지만,
                # 미리 알려주면 상한을 넘겨 만든 뒤 잘려나가는 낭비를 줄인다.
                + f"추가할 수 있는 조항 수: 최대 {cap}개 (이 모임 유형의 상한)\n\n"
                # 한도 표를 그대로 준다 — 종전에는 LLM이 금액을 몰라 "회칙이 정한 한도
                # 범위에서"처럼 실제 한도가 불분명한 문구를 썼다(2026-08-11 지적).
                # 이제 이 표의 금액만 인용하게 하고, 그 밖의 금액은 조립부가 걸러낸다.
                + "이 회칙이 정한 한도 (조항에 금액을 쓸 때는 이 값만 그대로 인용하세요):\n"
                + "\n".join(f"- {LIMIT_LABELS.get(k, k)}: {v}원" for k, v in limits.items())
                + "\n\n이미 작성된 기본 조항 (같은 내용을 반복하지 마세요):\n"
                + "\n".join(f"- {r}" for r in base_rules)
                + f"\n\n참고 규정(다른 모임 사례 — 그대로 베끼지 말고 참고만):\n{ref_text}",
                schema=ExtraRules,
                mock_response=ExtraRules(extra_rules=_mock_extra_rules(req.description, cap)),
                prompt_version=spec.version,
            )
            # 중복 제거를 상한 적용보다 먼저 — 그래야 겹친 조항이 상한 자리를 차지하지 않는다
            fresh = dedupe_rules(base_rules, [r.rendered() for r in result.extra_rules])
            fresh, vague = drop_vague_rules(fresh)
            if vague:
                logger.info(
                    "모호어 조항 %d개 제외 — %s",
                    len(vague), [f"{vague_terms_in(v)}: {v[:40]}" for v in vague],
                )
            # 회칙이 정한 한도·승인 기준 밖의 금액을 쓴 조항도 뺀다.
            # 회비도 이 회칙이 정한 금액이다 — 빼두면 기본 조항의 회비를 정당하게
            # 인용한 LLM 조항이 통째로 버려진다 (PR #65 리뷰 N4).
            allowed = {int(v.replace(",", "")) for v in limits.values()}
            if has_auto_range:
                allowed.add(req.force_escalation_amount)
            if dues:
                allowed.add(dues)
            kept = [r for r in fresh if not unknown_amounts_in(r, allowed)]
            if len(kept) != len(fresh):
                logger.info(
                    "한도 밖 금액 조항 %d개 제외 — %s", len(fresh) - len(kept),
                    [r[:50] for r in fresh if unknown_amounts_in(r, allowed)],
                )
            fresh = kept
            extra_rules = [
                # 기본 조항 뒤에 조 번호를 이어 붙인다 — 한 문서로 읽혀야 한다
                f"제{len(base_rules) + i}조{r}"
                for i, r in enumerate(fresh[:cap], start=1)
            ]
        except Exception:
            logger.exception("policy_drafter 추가 조항 생성 실패 — 기본 조항만 사용")

    # notes의 회비 표기는 **실제로 회비 조가 실렸을 때만** 붙인다 — 회사 유형처럼
    # 회비 조 자체가 없는 템플릿에서는 사용자가 회비를 입력해도 조항이 생기지 않으므로,
    # 입력값만 보고 notes에 적으면 verify의 '조항 ↔ notes 금액 일치' 검사에 걸린다.
    has_dues_rule = any(DUES_MARK in r for r in base_rules)
    if dues and not has_dues_rule:
        # 회사 유형에는 회비 조가 없다 — 입력을 받아도 조항·notes 어디에도 안 남는다.
        # 의도된 동작이지만 화면 입력이 흔적 없이 사라지는 자리라 로그로 남긴다
        # (PR #65 리뷰 N6). 계약·문구는 바꾸지 않는다.
        logger.info(
            "회비 %s원 입력이 초안에 반영되지 않음 — '%s' 유형에 회비 조가 없다",
            f"{dues:,}", req.team_type,
        )
    dues_note = DUES_NOTE.format(dues=f"{dues:,}") if has_dues_rule else ""
    draft = PolicyDraft(
        rules=base_rules + extra_rules,
        recommended_categories=all_categories(),  # 전역 고정 9종 (신규 생성 없음)
        notes=f"'{req.team_name}' ({req.team_type}) 초기예산 {req.initial_budget:,}원{dues_note}"
        " 기준 자동 생성 초안 — 관리자 검토 후 확정",
    )
    return {"draft": draft}


# 승인 기준선을 말하는 조항을 식별 — 이 조항의 금액은 요청의 기준 금액과 반드시 같아야 한다.
# '자동 심사'뿐 아니라 '관리자 승인/확인'까지 보는 이유: 같은 기준을 "8만원 넘으면 관리자가
# 확인한다"처럼 '자동'이라는 말 없이 쓸 수 있고, 그때도 회칙과 심사 기준은 똑같이 갈라진다.
# 헛경보 없음을 주석으로 주장하지 않는다 — 종전에 "기존 조항 28개 전수 확인 결과 헛경보
# 0건"이라 적혀 있었는데, 그 28개는 회칙 개편(#65) **이전의 base_rules**였다. 개편으로
# 들어온 bylaw_articles에는 다시 확인한 적이 없었고 실제로 회사 유형이 걸려 있었다.
# 전수 확인은 주석이 아니라 테스트가 한다 — `test_all_team_types_draft_verifies`.
_AUTO_RULE_HINT = re.compile(r"자동\s*(?:심사|승인)|관리자.{0,4}(?:승인|확인)")
_AMOUNT_RE = re.compile(r"([\d,]+)\s*원")
# '3만원'·'20만 원' 같은 한글 단위 표기 — 숫자 표기만 보면 필터를 우회한다(N5).
# 위 정규식과 겹치지 않는다: '3만원'은 숫자 뒤가 '만'이라 `[\d,]+\s*원`에 안 걸린다.
_MAN_AMOUNT_RE = re.compile(r"([\d,]+)\s*만\s*원")
# DUES_RULE·DUES_NOTE에서 placeholder 앞부분만 — 문구를 고쳐도 따라간다
_DUES_NOTE_MARK = DUES_NOTE.split("{")[0]
# 회비 조항 안의 금액을 뽑는다 — notes 표기와 같은 값인지 대조하기 위해서다.
# 납부 주기가 금액 앞에 온다("회비는 1인당 월 20,000원") — 숫자가 아닌 말은 건너뛴다
_DUES_IN_RULE = re.compile(re.escape(DUES_MARK) + r"[^\d]*([\d,]+)\s*원")
_DUES_IN_NOTE = re.compile(re.escape(_DUES_NOTE_MARK) + r"([\d,]+)\s*원")


def _amounts_in(text: str) -> list[int]:
    """조항 문장에 등장하는 금액을 모두 정수로 — '12,000원'과 '3만원' 둘 다.

    한글 단위 표기를 함께 잡는 이유: 이 함수 결과가 한도 밖 금액 필터
    (`unknown_amounts_in`)와 자동 심사 조항 검사의 입력이다. 숫자 표기만 보면
    LLM이 "3만원"이라고 쓰는 순간 두 검사를 조용히 우회한다 (PR #65 리뷰 N5).
    '3만원'과 '30,000원'은 같은 값으로 환산하므로 한도 표와 그대로 대조된다.
    """
    out: list[int] = []
    for raw in _AMOUNT_RE.findall(text):
        digits = raw.replace(",", "")
        if digits.isdigit():
            out.append(int(digits))
    for raw in _MAN_AMOUNT_RE.findall(text):
        digits = raw.replace(",", "")
        if digits.isdigit():
            out.append(int(digits) * 10_000)
    return out


def verify_draft_pure(
    draft: PolicyDraft, *, rule_source: str, force_escalation_amount: int
) -> str | None:
    """검증(Evaluator) — 위반 시 사유 반환, 통과 시 None. 순수 함수 (단위 테스트 대상).

    이 초안은 관리자가 그대로 확정하면 곧바로 팀 회칙이 되고, 심사 에이전트가 그 회칙을
    근거로 판정한다. 그래서 '그럴듯하지만 서로 어긋나는' 산출물을 통과시키지 않는 것이
    핵심이다 — 특히 LLM 추가 조항이 요청의 기준 금액과 다른 금액을 말하면, 회원이 보는
    회칙과 심사 기준이 갈라진다. rule_source가 ai가 아니면 초안을 만들지 않는 계약이라
    rules가 비어 있어야 한다 (개정안 §1-4).
    """
    # 마법사 1단계가 이 목록을 그대로 칩으로 보여준다 — 비면 화면이 비고 중복이면 칩이 두 번 뜬다
    cats = draft.recommended_categories
    if not cats:
        return "추천 카테고리 없음"
    if len(cats) != len(set(cats)):
        return "추천 카테고리 중복"

    if rule_source != "ai":
        if draft.rules:
            return f"rule_source={rule_source}인데 회칙 조항 존재 (빈 배열이어야 함)"
        # non-ai notes는 팀 이름을 그대로 품는다(§generate_draft) — 회비 조항이 아예
        # 없는 경로라 아래 정합 검사를 적용할 대상이 없다. 적용하면 notes에 우연히
        # " · 회비 "가 낀 팀 이름(예: '산악 · 회비 모임')에서 오탐 500이 난다.
        return None

    if not draft.rules:
        return "조항 없음"
    if any("{" in r for r in draft.rules):
        return "치환되지 않은 placeholder 존재"
    if any(not r.strip() for r in draft.rules):
        return "빈 조항 존재"

    keys = [normalize_rule(r) for r in draft.rules]
    if len(keys) != len(set(keys)):
        return "중복 조항 존재"

    # 금액 모호어 — LLM 조항은 조립 단계(drop_vague_rules)에서 이미 걸러지므로, 여기까지
    # 오는 것은 **템플릿에 모호어가 들어간 경우**뿐이다. 그건 우리 쪽 결함이라 조용히
    # 넘기지 않고 불통과시킨다(테스트가 CI에서 먼저 잡지만 이중으로 막는다).
    for rule in draft.rules:
        if found := vague_terms_in(rule):
            return f"금액 모호어 사용: {found[0]} — 금액이나 조건으로 바꿔야 한다"

    # 환각 방어 — 자동 심사를 말하는 조항의 금액은 요청의 기준 금액 하나뿐이어야 한다.
    #
    # ⚠️ 이 검사는 **템플릿 조항도 함께 걸린다.** '자동 심사'·'관리자 승인/확인'이라는
    # 말이 든 조에 한도 placeholder를 같이 쓰면 두 금액이 우연히 같지 않은 한 매번
    # 불통과다 — 회사 유형 경조사비 조가 그렇게 초안 생성을 통째로 500으로 만들고
    # 있었다(2026-08-12 발견, 템플릿에서 '자동 심사' 문구를 뺐다). 조항을 새로 쓸 때
    # 이 조합을 만들지 말 것. `test_all_team_types_draft_verifies`가 5유형을 지킨다.
    for rule in draft.rules:
        if not _AUTO_RULE_HINT.search(rule):
            continue
        amounts = _amounts_in(rule)
        if force_escalation_amount == 0:
            # 자동 승인 구간이 없다 = 인용할 기준 금액 자체가 없다. "0원 미만"(공집합)도
            # "0원 이상"(전체)도 규범으로 기능하지 않으므로 금액이 있다는 것만으로 잘못이다.
            if amounts:
                return (
                    f"기준 금액이 0(전건 관리자 확인)인데 조항이 금액을 인용함: {amounts[0]:,}원 "
                    "— 이때는 금액 없이 '모든 지출'로 써야 한다"
                )
            continue
        bad = [a for a in amounts if a != force_escalation_amount]
        if bad:
            return (
                f"자동 심사 한도 조항의 금액이 설정 금액과 불일치: {bad[0]:,}원 "
                f"(설정 {force_escalation_amount:,}원)"
            )

    # 회비 조항과 notes 표기는 같은 값에서 나온다 — 한쪽만 있거나 금액이 다르면 조립 버그다.
    # (2026-08-11: 종전엔 '둘 다 있나/없나'만 봤다. 회비가 제안값으로도 들어오게 되면서
    #  존재 여부만으로는 부족해져 **금액 일치**까지 본다.)
    in_rule = next((m.group(1) for r in draft.rules if (m := _DUES_IN_RULE.search(r))), None)
    in_note = (m.group(1) if (m := _DUES_IN_NOTE.search(draft.notes)) else None)
    if in_rule != in_note:
        return f"회비 조항과 notes 표기 불일치: 조항 {in_rule or '없음'} / notes {in_note or '없음'}"
    return None


async def verify_draft(state: DraftState) -> dict:
    req = state["request"]
    error = verify_draft_pure(
        state["draft"],
        rule_source=req.rule_source,
        force_escalation_amount=req.force_escalation_amount,
    )
    if error:
        logger.error("policy draft verification failed: %s", error)
    return {"verified": error is None, "verify_error": error}


def build_policy_draft_graph():
    g = StateGraph(DraftState)
    g.add_node("load_template", load_template)
    g.add_node("retrieve_references", retrieve_references)
    g.add_node("generate_draft", generate_draft)
    g.add_node("verify_draft", verify_draft)
    g.add_edge(START, "load_template")
    g.add_edge("load_template", "retrieve_references")
    g.add_edge("retrieve_references", "generate_draft")
    g.add_edge("generate_draft", "verify_draft")
    g.add_edge("verify_draft", END)
    return g.compile()


policy_draft_graph = build_policy_draft_graph()
