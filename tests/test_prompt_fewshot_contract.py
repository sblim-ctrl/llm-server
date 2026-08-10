"""few_shot 예시와 코드 계약의 정합 — 목 모드 테스트가 못 잡던 구멍을 막는다.

**왜 필요한가.** PR #9 리뷰에서 팀장이 `digest_writer/v2`의 결함을 손으로 찾아냈다.
코드는 `DigestText.advice`를 기본값 없는 필수 필드로 두고 `verify_digest_pure`가
비어 있으면 브리핑 전체를 폐기하는데, **프롬프트의 system 규칙에도 few_shot 출력
2건에도 advice가 한 번도 안 나왔다.** 목 모드는 `_mock_advice`가 채워서 통과하고
writers 골든셋 20건은 digest를 다루지 않아, 369건이 전부 통과하는 상태에서
실모드에서만 터질 결함이었다.

그 뒤 같은 계열을 `dashboard_writer`에서 또 발견했다. **두 번 다 사람이 손으로
찾았다는 건 이걸 보는 테스트가 없었다는 뜻이다.** 이 파일이 그 자리다.

여기서 잡는 것 4가지:
  ① few_shot 출력이 유효한 JSON인가
  ② 출력에 선언된 스키마의 **필수 필드가 다 들어 있는가** ← D2를 잡는 검사
  ③ JSON 입력이 런타임 직렬화 형식(한 줄)과 같은가
  ④ few_shot 예시가 자기 검증기를 실제로 통과하는가 ← "모범 예시가 폐기되는" 자기모순
"""

import json
import re

import pytest
import yaml

from app.llm.prompts import _PROMPTS_DIR

# prompts YAML의 `output_schema:` 이름 → 실제 pydantic 모델.
# output_schema는 로더가 해석하지 않는 문서용 주석이라(prompts.py 헤더), 코드와
# 이어주려면 이 표가 필요하다. 프롬프트를 새로 만들 때 여기 한 줄을 추가한다.
_SCHEMA_REGISTRY = {}


def _register():
    from app.eval_judge import JudgeResult
    from app.graphs.review.nodes.adjudicate import AdjudicationResult
    from app.graphs.review.nodes.classify_category import CategoryPrediction
    from app.graphs.review.nodes.rule_auditor import RewrittenQuery
    from app.graphs.writers.briefing import BriefingText
    from app.graphs.writers.budget_planner import BudgetMessage, ProposalText
    from app.graphs.writers.digest import DigestText
    from app.graphs.writers.policy_draft import ExtraRules
    from app.graphs.writers.report import ReportText
    from app.graphs.writers.rule_amendment import AmendmentText
    from app.schemas.common import Opinion, ReceiptData
    from app.schemas.dashboard import DashboardSummary

    for m in (
        JudgeResult,
        AdjudicationResult,
        CategoryPrediction,
        RewrittenQuery,
        BriefingText,
        ProposalText,
        BudgetMessage,
        DigestText,
        ExtraRules,
        ReportText,
        AmendmentText,
        Opinion,
        ReceiptData,
        DashboardSummary,
    ):
        _SCHEMA_REGISTRY[m.__name__] = m


_register()

# ③의 기존 부채 — few_shot input이 여러 줄 JSON인데 런타임은 한 줄로 보내는 파일들.
# 전부 실측으로 승격된 기본 버전이라, 형식을 바꾸면 그 실측 근거가 그대로 적용되지
# 않는다("실측으로 재현된 개선만 승격"). 예정된 재측정 라운드에서 정리한다.
# **새로 추가되는 위반은 이 목록에 없으므로 즉시 실패한다** — 그게 이 테스트의 목적이다.
#
# report_writer/v3(PR-5, 2026-08-08)은 예외: v2의 카탈로그 라벨만 고친 정합 수정이라
# few_shot 구조를 v2와 바이트 단위로 동일하게 유지하기로 했다 — 그래서 이 부채도
# v2 그대로 이어받는다. 새 위반이 아니라 기존 부채의 승계다. report_writer/v4·
# briefing_writer/v3(2026-08-10, A 리뷰)도 같은 이유 — 라벨만 고친 정합 수정이라
# 구조를 손대지 않고 앞 버전의 부채를 그대로 이어받는다.
_MULTILINE_INPUT_DEBT = {
    ("briefing_writer", "v1"),
    ("briefing_writer", "v2"),
    ("briefing_writer", "v3"),
    ("budget_planner", "v1"),
    ("budget_planner", "v2"),
    ("dashboard_writer", "v1"),
    ("dashboard_writer", "v2"),
    # v4 = v2 + 인젝션 방어 한 줄 — 여러 줄 입력을 **의도적으로 보존**한다. v2의 과장
    # 차단 실측(2026-08-04)이 여러 줄 입력 상태에서 재현된 것이라, 형식 정리는 v3
    # 계보(재측정 라운드)의 몫이다 (DEFAULT_VERSIONS의 dashboard_writer 주석 참조).
    ("dashboard_writer", "v4"),
    ("digest_writer", "v2"),
    ("judge", "v1"),
    ("judge", "v2"),
    ("judge", "v3"),
    ("report_writer", "v1"),
    ("report_writer", "v2"),
    ("report_writer", "v3"),
    ("report_writer", "v4"),
}


# ②의 기존 부채 — 스키마에 필드가 **나중에 추가되면서** 그 이전 버전이 뒤처진 자리.
# 규율상 프롬프트 버전은 지우지 않고 남기므로(버전을 지우지 않고 새로 만든다), 옛 버전은
# 그 시점의 계약을 담은 이력으로 둔다. 대신 **기본으로 쓰이는 버전은 예외 없이 검사한다.**
#
#   digest_writer v1·v2 — DigestText.advice가 코드에 추가됐는데 프롬프트가 따라가지
#     않았다. 이게 PR #9 리뷰 D2로 지적된 결함 자체이고, v3에서 해소했다.
#     v1·v2는 그 시점 기록으로 남긴다.
_SUPERSEDED_OUTPUT_DEBT = {
    ("digest_writer", "v1"),
    ("digest_writer", "v2"),
}


# test_all_active_fewshot_category_labels_are_in_catalog()의 기존 부채 자리 — **현재
# 활성**(DEFAULT_VERSIONS 기준) 버전인데도 few_shot이 카탈로그 밖 라벨을 쓰는 경우.
# 원래 default_policy/v1·query_rewriter/v1이 여기 있었으나, 두 에이전트 모두 이후
# v2로 승격되며 라벨이 정합됐다(다과→식비, 회식비→식비, 도서→교육) — 지금은 부채가
# 없다. 새로 부채가 생기면 (agent, version) 튜플로 여기 추가한다.
_CATEGORY_LABEL_DEBT: set[tuple[str, str]] = set()


def _prompt_files():
    return sorted(_PROMPTS_DIR.glob("*/*.yaml"))


def _cases():
    """(에이전트, 버전, 선언스키마, 예시번호, 예시) 평탄화 — 실패 시 어느 예시인지 보이게."""
    out = []
    for path in _prompt_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = (data.get("output_schema") or "").split("#")[0].strip()
        for i, ex in enumerate(data.get("few_shot") or [], 1):
            out.append(
                pytest.param(
                    path.parent.name,
                    path.stem,
                    schema,
                    i,
                    ex,
                    id=f"{path.parent.name}/{path.stem}-예시{i}",
                )
            )
    return out


_CASES = _cases()


@pytest.mark.parametrize("agent,version,schema,idx,ex", _CASES)
def test_few_shot_output_is_valid_json(agent, version, schema, idx, ex):
    """① 출력이 JSON으로 파싱되는가. 모델이 흉내 낼 본보기이므로 깨져 있으면 안 된다."""
    raw = (ex.get("output") or "").strip()
    if not raw.startswith("{"):
        pytest.skip("JSON 출력이 아닌 프롬프트")
    json.loads(raw)  # 실패하면 그대로 에러


@pytest.mark.parametrize("agent,version,schema,idx,ex", _CASES)
def test_few_shot_output_covers_required_schema_fields(agent, version, schema, idx, ex):
    """② 필수 필드가 예시에 다 나오는가 — `digest_writer/v2`의 advice 누락을 잡는 검사.

    기본값이 없는 필드는 모델이 반드시 채워야 하는 값이다. 예시가 그 필드를 한 번도
    안 보여주면 모델은 그런 필드가 있는지 알 수 없고, 실모드에서 누락 → 검증 폐기가 된다.
    """
    model = _SCHEMA_REGISTRY.get(schema)
    if model is None:
        pytest.skip(f"등록되지 않은 스키마: {schema!r} — _SCHEMA_REGISTRY에 추가할 것")
    raw = (ex.get("output") or "").strip()
    if not raw.startswith("{"):
        pytest.skip("JSON 출력이 아닌 프롬프트")

    required = {n for n, f in model.model_fields.items() if f.is_required()}
    missing = required - set(json.loads(raw))
    if missing and (agent, version) in _SUPERSEDED_OUTPUT_DEBT:
        # 기본 버전이면 부채 목록에 있어도 봐주지 않는다 — 실제로 쓰이는 계약이므로.
        from app.llm.prompts import DEFAULT_VERSIONS

        assert DEFAULT_VERSIONS.get(agent, "v1") != version, (
            f"{agent}/{version}은 기본 버전인데 부채 목록에 있다 — 부채가 아니라 결함이다"
        )
        pytest.xfail(f"승격 전 구버전 — {sorted(missing)} 누락 (파일 상단 주석 참조)")
    assert not missing, (
        f"{agent}/{version} 예시{idx}: 스키마 {schema}의 필수 필드 {sorted(missing)}이(가) "
        f"few_shot 출력에 없다. 코드는 요구하는데 예시가 안 보여주면 실모드에서만 터진다."
    )


@pytest.mark.parametrize("agent,version,schema,idx,ex", _CASES)
def test_few_shot_json_input_is_single_line(agent, version, schema, idx, ex):
    """③ JSON 입력이 한 줄인가.

    런타임은 `model_dump_json()`·`json.dumps()`로 **한 줄** JSON을 보낸다. 예시가 여러
    줄이면 모델이 보는 형식과 실제 입력이 달라지고, 이는 에러가 아니라 조용한 품질
    저하로 나타난다(인수인계 §6 "few_shot은 런타임 입력과 바이트 단위로 같아야 한다").
    """
    raw = (ex.get("input") or "").strip()
    if not raw.startswith("{"):
        pytest.skip("JSON 입력이 아닌 프롬프트")
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        pytest.skip("JSON이 아닌 입력")
    if (agent, version) in _MULTILINE_INPUT_DEBT:
        pytest.xfail("기존 부채 — 재측정 라운드에서 정리 (파일 상단 주석 참조)")
    assert "\n" not in raw, (
        f"{agent}/{version} 예시{idx}: JSON 입력이 여러 줄이다. 런타임은 한 줄로 보낸다. "
        f"한 줄로 고치거나, 의도된 것이면 _MULTILINE_INPUT_DEBT에 근거와 함께 추가할 것."
    )


def test_digest_few_shot_passes_its_verifier():
    """④ digest 예시가 verify_digest_pure를 통과하는가.

    v1의 실제 결함이 "모범 예시가 검증에서 폐기되는 것"이었다(예시 2에 '반려 0건'
    누락). 예시가 스스로 불합격이면 모델에게 불합격을 가르치는 셈이다.
    """
    from app.graphs.writers.digest import DigestDoc, DigestFigures, verify_digest_pure
    from app.llm.prompts import load_prompt

    spec = load_prompt("digest_writer")
    assert spec.few_shot, "digest_writer few_shot이 비어 있다"
    for i, ex in enumerate(spec.few_shot, 1):
        fig = DigestFigures(**json.loads(ex["input"].strip()))
        out = json.loads(ex["output"])
        doc = DigestDoc(
            figures=fig,
            summary=out["summary"],
            highlights=out["highlights"],
            advice=out["advice"],
            verified=False,
        )
        assert verify_digest_pure(doc, fig), (
            f"digest_writer 예시{i}이 자기 검증기에서 폐기된다 — 모범 예시가 불합격이면 "
            f"모델에게 불합격을 가르치게 된다"
        )


def test_dashboard_few_shot_passes_its_verifier():
    """④ dashboard 예시가 verify_summary_pure를 통과하는가 (금액·백분율 허용 목록 대조)."""
    from app.graphs.writers.dashboard import verify_summary_pure
    from app.llm.prompts import load_prompt
    from app.schemas.dashboard import DashboardFigures, DashboardSummaryDoc

    spec = load_prompt("dashboard_writer")
    assert spec.few_shot, "dashboard_writer few_shot이 비어 있다"
    for i, ex in enumerate(spec.few_shot, 1):
        fig = DashboardFigures(**json.loads(ex["input"].strip()))
        out = json.loads(ex["output"])
        doc = DashboardSummaryDoc(figures=fig, message=out["message"], verified=False)
        assert verify_summary_pure(doc), f"dashboard_writer 예시{i}이 자기 검증기에서 폐기된다"


def test_budget_planner_few_shot_passes_its_verifier():
    """④ budget_planner 3블록 예시가 verify_budget_message_pure를 통과하는가.

    이 검증기는 금액·백분율·날짜·카테고리명을 한꺼번에 대조하고 잔액 언급까지 요구해서,
    예시를 손으로 쓰면 어딘가 하나는 어긋나기 쉽다. 예시가 스스로 불합격이면 모델에게
    불합격을 가르치는 셈이다.
    """
    from app.graphs.writers.budget_planner import (
        BudgetFigures,
        BudgetMessage,
        verify_budget_message_pure,
    )
    from app.llm.prompts import load_prompt

    spec = load_prompt("budget_planner")
    assert spec.few_shot, "budget_planner few_shot이 비어 있다"
    for i, ex in enumerate(spec.few_shot, 1):
        fig = BudgetFigures.model_validate_json(ex["input"].strip())
        msg = BudgetMessage.model_validate_json(ex["output"].strip())
        assert verify_budget_message_pure(msg, fig), (
            f"budget_planner 예시{i}이 자기 검증기에서 폐기된다"
        )
        # few_shot 입력은 런타임 model_dump_json()과 **바이트 단위로** 같아야 한다.
        assert fig.model_dump_json() == ex["input"].strip(), (
            f"budget_planner 예시{i} 입력이 런타임 직렬화와 다르다 — 필드 순서·float 표기 확인"
        )


def test_report_few_shot_passes_its_verifier():
    """④ report 예시가 verify_report_pure를 통과하는가.

    digest·dashboard·budget_planner에는 있던 자기검증이 report에는 없었다 —
    2026-08-10 A 리뷰로 report_writer/v3 예시1의 by_category 중복 카테고리(식비가
    두 행)가 사람 눈으로만 발견됐다. verify_report_pure는 숫자 존재만 대조해서
    이 결함 자체는 못 잡지만(아래 별도 테스트가 잡는다), 다른 수치 불일치를
    미리 잡기 위해 이 자리를 report에도 채운다.
    """
    from app.schemas.writers import BudgetReport, ReportFigures
    from app.graphs.writers.report import verify_report_pure
    from app.llm.prompts import load_prompt

    spec = load_prompt("report_writer")
    assert spec.few_shot, "report_writer few_shot이 비어 있다"
    for i, ex in enumerate(spec.few_shot, 1):
        fig = ReportFigures(**json.loads(ex["input"].strip()))
        out = json.loads(ex["output"])
        report = BudgetReport(
            figures=fig, summary=out["summary"], recommendations=[], verified=False
        )
        assert verify_report_pure(report, fig), f"report_writer 예시{i}이 자기 검증기에서 폐기된다"


def test_report_few_shot_by_category_has_unique_categories():
    """by_category에 같은 카테고리가 두 번 나올 수 있는가 — 실제로는 불가능한 형태.

    aggregate_pure(report.py)는 카테고리별로 dict에 합산하므로 런타임 출력에서
    같은 카테고리가 두 행으로 갈라지는 일은 없다. report_writer/v3 예시1이
    #37 라벨 치환의 부작용으로 정확히 그 불가능한 형태(식비 두 행)를 정답으로
    가르치고 있었다 — verify_report_pure는 숫자 존재만 봐서 이 결함을 통과시켰다
    (2026-08-10 A 리뷰). 이 테스트가 그 구멍을 직접 막는다.
    """
    from app.llm.prompts import load_prompt

    spec = load_prompt("report_writer")
    for i, ex in enumerate(spec.few_shot, 1):
        raw = ex["input"].strip()
        if not raw.startswith("{"):
            continue
        parsed = json.loads(raw)
        cats = [c["category"] for c in parsed.get("by_category", [])]
        assert len(cats) == len(set(cats)), (
            f"report_writer 예시{i}의 by_category에 중복 카테고리: {cats} — "
            f"aggregate_pure는 카테고리별로 합산하므로 런타임에 나올 수 없는 형태다"
        )


def test_briefing_few_shot_passes_its_verifier():
    """④ briefing 예시가 verify_briefing_pure를 통과하는가 (digest·dashboard·
    budget_planner에는 있던 자기검증이 briefing에는 없었다 — 2026-08-10 A 리뷰)."""
    from app.graphs.writers.briefing import verify_briefing_pure
    from app.llm.prompts import load_prompt
    from app.schemas.writers import BriefingDoc, BriefingFigures

    spec = load_prompt("briefing_writer")
    assert spec.few_shot, "briefing_writer few_shot이 비어 있다"
    for i, ex in enumerate(spec.few_shot, 1):
        fig = BriefingFigures(**json.loads(ex["input"].strip()))
        out = json.loads(ex["output"])
        doc = BriefingDoc(figures=fig, summary=out["summary"], handover_notes=[], verified=False)
        assert verify_briefing_pure(doc, fig), f"briefing_writer 예시{i}이 자기 검증기에서 폐기된다"


def test_classifier_few_shot_labels_are_in_catalog():
    """분류기 예시의 정답 라벨이 카탈로그 안의 값인가.

    카탈로그 밖 값은 `classify_category`가 폐기하고 키워드로 교정한다. 예시가 카탈로그
    밖 라벨을 가르치면 그 예시는 학습이 아니라 잡음이 된다. 2026-08-05 카테고리
    이름을 ENUM 저장값(밑줄)으로 바꾸면서 실제로 전 예시를 손봐야 했던 자리다.
    """
    from app.llm.prompts import DEFAULT_VERSIONS, load_prompt
    from app.tools.category_catalog import all_categories

    cats = set(all_categories())
    # **버전 목록을 손으로 적지 않는다.** 종전에는 ("v3","v4","v5","v6") 하드코딩이라
    # 새 버전을 만들 때마다 여기를 같이 늘려야 했고, 실제로 v6 승격 때 그걸 빠뜨려
    # "정작 런타임이 쓰는 버전만 무검사"인 상태가 된 적이 있다(2026-08-06 T7 후속).
    # 파일에서 직접 읽어 그 함정을 없앤다 — v7 추가(2026-08-10) 때 재발할 뻔했다.
    legacy = {"v1", "v2"}  # 9종 확정(v3) 이전 어휘 — 그 시점 이력으로 남긴 버전
    versions = sorted(p.stem for p in (_PROMPTS_DIR / "classifier").glob("*.yaml"))
    checked = [v for v in versions if v not in legacy]
    assert checked, "classifier 프롬프트를 하나도 못 찾았다"

    active = DEFAULT_VERSIONS.get("classifier", "v1")
    assert active in checked, (
        f"기본 버전 classifier/{active}이 검사 대상에 없다 — 런타임이 쓰는 버전이 "
        f"무검사면 이 테스트의 의미가 없다 (검사 대상: {checked})"
    )

    for v in checked:
        spec = load_prompt("classifier", v)
        for i, ex in enumerate(spec.few_shot, 1):
            label = json.loads(ex["output"])["category"]
            assert label in cats, (
                f"classifier/{v} 예시{i}의 라벨 {label!r}이 카탈로그에 없다 "
                f"(카탈로그: {sorted(cats)})"
            )


def _collect_category_values(node, out: list) -> None:
    """중첩 dict/list를 재귀 순회하며 카테고리 라벨을 담는 키의 값을 out에 모은다.

    'category'는 단일 라벨, 'gap_categories'는 라벨 리스트다(briefing_writer의
    figures 필드 — 2026-08-10 A 리뷰: 원래 'category' 키만 봐서 이 자리에 남아
    있던 구 라벨을 놓쳤다)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "category":
                out.append(value)
            elif key == "gap_categories" and isinstance(value, list):
                out.extend(value)
            _collect_category_values(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_category_values(item, out)


def test_all_active_fewshot_category_labels_are_in_catalog():
    """15개 전 에이전트의 **현재 활성**(DEFAULT_VERSIONS 기준) few_shot이 카탈로그
    밖 카테고리 라벨을 가르치고 있지 않은가.

    위 `test_classifier_few_shot_labels_are_in_catalog`은 classifier 하나에만
    적용돼, report_writer·rule_auditor·precedent_auditor·default_policy·
    query_rewriter의 라벨 드리프트가 지금까지 감지되지 못했다(앞의 셋은 PR-5가
    카탈로그 라벨 정합 수정으로 해소). 이 테스트는 그 검사를 프롬프트 디렉터리를
    가진 모든 에이전트로 일반화한다.

    **한계 (알려진 것이지 버그가 아님)**: input/output을 JSON으로 파싱할 수 있을
    때만 그 안의 "category" 키를 본다. `rule_amendment`처럼 의도적으로 평문
    few_shot을 쓰는 에이전트나, JSON이 아니라 산문 속에서만("…다과로…") 카테고리를
    언급하는 경우는 잡지 못한다. 또한 few_shot 중에는 JSON 객체 뒤에 회칙 조항
    같은 평문이 이어붙는 형식(rule_auditor·precedent_auditor·default_policy)도
    있어, 전체 문자열이 아니라 **선두 JSON 값만** 관대하게 파싱한다
    (`json.JSONDecoder().raw_decode`) — 그래도 맨 앞부터 JSON이 아니면 조용히
    스킵한다(파싱 실패는 실패가 아니다).
    """
    from app.llm.prompts import DEFAULT_VERSIONS, load_prompt
    from app.tools.category_catalog import all_categories

    cats = set(all_categories())
    agents = sorted({path.parent.name for path in _prompt_files()})

    for agent in agents:
        version = DEFAULT_VERSIONS.get(agent, "v1")
        spec = load_prompt(agent, version)
        bad = []
        for i, ex in enumerate(spec.few_shot, 1):
            for field in ("input", "output"):
                raw = (ex.get(field) or "").strip()
                try:
                    parsed, _ = json.JSONDecoder().raw_decode(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                values: list = []
                _collect_category_values(parsed, values)
                for label in values:
                    if label not in cats:
                        bad.append((i, field, label))

        if (agent, version) in _CATEGORY_LABEL_DEBT:
            assert bad, (
                f"{agent}/{version}은 _CATEGORY_LABEL_DEBT에 있지만 카탈로그 밖 "
                f"라벨이 실제로는 없다 — 이미 고쳐졌다면 부채 목록에서 뺄 것"
            )
            continue
        assert not bad, (
            f"{agent}/{version} few_shot에 카탈로그 밖 카테고리 라벨: {bad} "
            f"(카탈로그: {sorted(cats)})"
        )


# adjudicator·rule_amendment는 few_shot 전체가 평문이라(판정 임계값·군집 요약으로
# 시작) 위 test_all_active_fewshot_category_labels_are_in_catalog의
# `json.JSONDecoder().raw_decode`가 맨 앞부터 실패해 아예 스캔되지 않는다.
# 카테고리 라벨은 "(approve/ADMIN) [라벨] ..." 판례 인용이나 "군집 요약: [라벨] ..."
# 형태로 대괄호 안에 박혀 있다 — 2026-08-10 A 리뷰에서 이 사각지대에 남아 있던
# 구 라벨 2건(adjudicator/v4 예시3·4)을 사람이 직접 찾았다. 이 테스트가 그 형태
# 두 가지를 정규식으로 직접 찾아 카탈로그와 대조한다.
_BRACKET_CATEGORY_RE = re.compile(
    r"\((?:approve|reject)/\w+\)\s*\[([^\]]+)\]|군집 요약:\s*\[([^\]]+)\]"
)


def test_active_plaintext_fewshot_category_labels_are_in_catalog():
    """평문 few_shot(adjudicator·rule_amendment)의 대괄호 라벨이 카탈로그 안의 값인가."""
    from app.llm.prompts import DEFAULT_VERSIONS, load_prompt
    from app.tools.category_catalog import all_categories

    cats = set(all_categories())
    for agent in ("adjudicator", "rule_amendment"):
        version = DEFAULT_VERSIONS.get(agent, "v1")
        spec = load_prompt(agent, version)
        for i, ex in enumerate(spec.few_shot, 1):
            for field in ("input", "output"):
                raw = ex.get(field) or ""
                for m in _BRACKET_CATEGORY_RE.finditer(raw):
                    label = m.group(1) or m.group(2)
                    assert label in cats, (
                        f"{agent}/{version} 예시{i}({field})의 대괄호 라벨 {label!r}이 "
                        f"카탈로그에 없다 (카탈로그: {sorted(cats)})"
                    )
