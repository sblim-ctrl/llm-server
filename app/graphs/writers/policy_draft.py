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
# 실제 개수를 조절). base_rules 4~5개와 합쳐 총 10~12개 = 모바일 카드 한 장 분량.
#
# 프롬프트가 이 상한을 실제로 쓰는 것은 **v3부터**다. v1·v2는 본문에 "0~3개"·"최대 3개"로
# 적혀 있어 실효 상한이 3이었고, 이 주석도 "v2가 0~7개를 사용한다"로 사실과 달랐다
# (PR #9 리뷰 D6 지적). v3가 "0~7개"로 맞췄다.
MAX_EXTRA_RULES = 10


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
# 회비 미입력 시 제안값의 하한 — 유형별 dues_default를 인원·예산으로 보정한 뒤 이 아래로는
# 내리지 않는다(0원 제안은 회칙 문장이 성립하지 않는다).
MIN_SUGGESTED_DUES = 5_000


def _article_applies(article: dict, dues: int) -> bool:
    """회비 조는 회비가 0일 때 뺀다 — '회비는 1인당 0원' 조항은 회칙으로 성립하지 않는다.

    회사 유형처럼 회비 개념이 없는 모임(dues_default=0)에서 사용자도 입력하지 않은
    경우가 이에 해당한다.
    """
    return dues > 0 or DUES_MARK not in article.get("text", "")


def _round_to(amount: float, unit: int = 1_000) -> int:
    """회칙에 적을 금액으로 반올림 — 1,000원 단위가 아니면 사람이 쓴 규정처럼 안 보인다."""
    return max(unit, int(round(amount / unit)) * unit)


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
        out[key] = f"{_round_to(clamped):,}"
    return out


def effective_dues(template: dict, req_dues: int | None, initial_budget: int,
                   member_count: int | None) -> tuple[int, bool]:
    """회칙에 적을 회비와 '제안값인지' 여부.

    사용자가 마법사 1단계에서 입력했으면 그 값이 원천이다(제안하지 않는다). 입력이
    없으면 유형별 기본 회비를 인원·예산으로 보정해 제안한다 — 화면의 '월 회비' 칸이
    비어 있을 때 관리자가 참고할 값이 회칙 안에 있어야 한다는 요구(2026-08-11)다.

    ※ 이것은 2026-08-05에 제거된 `policy_params`(승인 정책 제안)의 부활이 아니다.
      승인 기준 금액은 여전히 사용자 입력이 유일한 원천이고, 여기서 만드는 것은
      **회칙 조항 안의 권고 문구**뿐이다 — API 응답 필드가 늘지 않는다.
    """
    if req_dues:
        return req_dues, False
    base = int(template.get("dues_default") or 0)
    if base <= 0:
        return 0, True  # 회사 유형 등 회비 개념이 없는 경우
    # 인원이 많고 예산이 넉넉하면 1인 부담을 낮춘다 (1인당 예산이 클수록 회비는 덜 필요)
    n = max(member_count or 1, 1)
    per_person = initial_budget / n
    factor = 0.6 if per_person >= base * 30 else (0.8 if per_person >= base * 15 else 1.0)
    return max(_round_to(base * factor), MIN_SUGGESTED_DUES), True


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


def _mock_extra_rules(description: str) -> list[ExtraRule]:
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
    return rules[:MAX_EXTRA_RULES]


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
    MAX_EXTRA_RULES개)을 제안한다. 소개가 없으면 LLM을 호출하지 않아 기본 조항만
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
    dues, dues_is_suggested = effective_dues(
        template, req.dues, req.initial_budget, req.member_count
    )
    fmt = {
        "auto_approve_limit": f"{req.force_escalation_amount:,}",
        "dues": f"{dues:,}",
        **limits,
    }
    # 회칙 초안은 bylaw_articles를 쓴다 — base_rules는 심사용(회칙 미등록 팀의 기본
    # 정책 모드)이라 짧게 유지된다. 두 용도를 한 목록으로 쓰던 것을 2026-08-11에
    # 분리했다: 초안을 실제 회칙처럼 늘리면 심사 근거까지 같이 늘어나던 구조였다.
    articles = [a for a in template["bylaw_articles"] if _article_applies(a, dues)]
    base_rules = [f"제{i}조({a['title']}) {a['text'].format(**fmt)}"
                  for i, a in enumerate(articles, start=1)]

    extra_rules: list[str] = []
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
                f"관리자 승인 기준 금액: {req.force_escalation_amount:,}원\n\n"
                f"이미 작성된 기본 조항 (같은 내용을 반복하지 마세요):\n"
                + "\n".join(f"- {r}" for r in base_rules)
                + f"\n\n참고 규정(다른 모임 사례 — 그대로 베끼지 말고 참고만):\n{ref_text}",
                schema=ExtraRules,
                mock_response=ExtraRules(extra_rules=_mock_extra_rules(req.description)),
                prompt_version=spec.version,
            )
            # 중복 제거를 상한 적용보다 먼저 — 그래야 겹친 조항이 상한 자리를 차지하지 않는다
            fresh = dedupe_rules(base_rules, [r.rendered() for r in result.extra_rules])
            extra_rules = [
                # 기본 조항 뒤에 조 번호를 이어 붙인다 — 한 문서로 읽혀야 한다
                f"제{len(base_rules) + i}조{r}"
                for i, r in enumerate(fresh[:MAX_EXTRA_RULES], start=1)
            ]
        except Exception:
            logger.exception("policy_drafter 추가 조항 생성 실패 — 기본 조항만 사용")

    dues_note = DUES_NOTE.format(dues=f"{dues:,}") if dues else ""
    suffix = "(회비는 제안값)" if (dues and dues_is_suggested) else ""
    draft = PolicyDraft(
        rules=base_rules + extra_rules,
        recommended_categories=all_categories(),  # 전역 고정 9종 (신규 생성 없음)
        notes=f"'{req.team_name}' ({req.team_type}) 초기예산 {req.initial_budget:,}원{dues_note}"
        f"{suffix} 기준 자동 생성 초안 — 관리자 검토 후 확정",
    )
    return {"draft": draft}


# 승인 기준선을 말하는 조항을 식별 — 이 조항의 금액은 요청의 기준 금액과 반드시 같아야 한다.
# '자동 심사'뿐 아니라 '관리자 승인/확인'까지 보는 이유: 같은 기준을 "8만원 넘으면 관리자가
# 확인한다"처럼 '자동'이라는 말 없이 쓸 수 있고, 그때도 회칙과 심사 기준은 똑같이 갈라진다.
# 기존 조항 28개(5유형 base + 회비 + 목 추가조항) 전수 확인 결과 헛경보 0건.
_AUTO_RULE_HINT = re.compile(r"자동\s*(?:심사|승인)|관리자.{0,4}(?:승인|확인)")
_AMOUNT_RE = re.compile(r"([\d,]+)\s*원")
# DUES_RULE·DUES_NOTE에서 placeholder 앞부분만 — 문구를 고쳐도 따라간다
_DUES_NOTE_MARK = DUES_NOTE.split("{")[0]
# 회비 조항 안의 금액을 뽑는다 — notes 표기와 같은 값인지 대조하기 위해서다.
_DUES_IN_RULE = re.compile(re.escape(DUES_MARK) + r"([\d,]+)\s*원")
_DUES_IN_NOTE = re.compile(re.escape(_DUES_NOTE_MARK) + r"([\d,]+)\s*원")


def _amounts_in(text: str) -> list[int]:
    """조항 문장에 등장하는 '12,000원' 형태의 금액을 모두 정수로."""
    out: list[int] = []
    for raw in _AMOUNT_RE.findall(text):
        digits = raw.replace(",", "")
        if digits.isdigit():
            out.append(int(digits))
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

    # 환각 방어 — 자동 심사를 말하는 조항의 금액은 요청의 기준 금액 하나뿐이어야 한다
    for rule in draft.rules:
        if not _AUTO_RULE_HINT.search(rule):
            continue
        bad = [a for a in _amounts_in(rule) if a != force_escalation_amount]
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
