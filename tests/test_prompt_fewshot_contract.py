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

    for m in (JudgeResult, AdjudicationResult, CategoryPrediction, RewrittenQuery,
              BriefingText, ProposalText, BudgetMessage, DigestText, ExtraRules, ReportText,
              AmendmentText, Opinion, ReceiptData, DashboardSummary):
        _SCHEMA_REGISTRY[m.__name__] = m


_register()

# ③의 기존 부채 — few_shot input이 여러 줄 JSON인데 런타임은 한 줄로 보내는 파일들.
# 전부 실측으로 승격된 기본 버전이라, 형식을 바꾸면 그 실측 근거가 그대로 적용되지
# 않는다("실측으로 재현된 개선만 승격"). 예정된 재측정 라운드에서 정리한다.
# **새로 추가되는 위반은 이 목록에 없으므로 즉시 실패한다** — 그게 이 테스트의 목적이다.
_MULTILINE_INPUT_DEBT = {
    ("briefing_writer", "v1"), ("briefing_writer", "v2"),
    ("budget_planner", "v1"), ("budget_planner", "v2"),
    ("dashboard_writer", "v1"), ("dashboard_writer", "v2"),
    ("digest_writer", "v2"),
    ("judge", "v1"), ("judge", "v2"), ("judge", "v3"),
    ("report_writer", "v1"), ("report_writer", "v2"),
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


def _prompt_files():
    return sorted(_PROMPTS_DIR.glob("*/*.yaml"))


def _cases():
    """(에이전트, 버전, 선언스키마, 예시번호, 예시) 평탄화 — 실패 시 어느 예시인지 보이게."""
    out = []
    for path in _prompt_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = (data.get("output_schema") or "").split("#")[0].strip()
        for i, ex in enumerate(data.get("few_shot") or [], 1):
            out.append(pytest.param(path.parent.name, path.stem, schema, i, ex,
                                    id=f"{path.parent.name}/{path.stem}-예시{i}"))
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
        doc = DigestDoc(figures=fig, summary=out["summary"], highlights=out["highlights"],
                        advice=out["advice"], verified=False)
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


def test_classifier_few_shot_labels_are_in_catalog():
    """분류기 예시의 정답 라벨이 카탈로그 안의 값인가.

    카탈로그 밖 값은 `classify_category`가 폐기하고 키워드로 교정한다. 예시가 카탈로그
    밖 라벨을 가르치면 그 예시는 학습이 아니라 잡음이 된다. 2026-08-05 카테고리
    이름을 ENUM 저장값(밑줄)으로 바꾸면서 실제로 전 예시를 손봐야 했던 자리다.
    """
    from app.llm.prompts import load_prompt
    from app.tools.category_catalog import all_categories

    cats = set(all_categories())
    for v in ("v3", "v4", "v5"):
        spec = load_prompt("classifier", v)
        for i, ex in enumerate(spec.few_shot, 1):
            label = json.loads(ex["output"])["category"]
            assert label in cats, (
                f"classifier/{v} 예시{i}의 라벨 {label!r}이 카탈로그에 없다 "
                f"(카탈로그: {sorted(cats)})"
            )
