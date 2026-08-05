"""프롬프트 로더 (B1) — YAML 4종 로드·version 필드 정합성."""

import pytest

from app.llm.prompts import DEFAULT_VERSIONS, load_prompt

AGENTS = [
    "adjudicator",
    "briefing_writer",
    "budget_planner",
    "classifier",
    "dashboard_writer",
    "default_policy",
    "digest_writer",
    "intake",
    "judge",
    "policy_drafter",
    "precedent_auditor",
    "query_rewriter",
    "report_writer",
    "rule_amendment",
    "rule_auditor",
]  # 15종 전수 — prompts/ 하위 에이전트 디렉터리와 1:1 (브랜치 통합 합집합)


@pytest.mark.parametrize("agent", AGENTS)
def test_loads_and_has_required_fields(agent):
    spec = load_prompt(agent)
    assert spec.system.strip()
    # YAML 내부 version: 필드가 진실 원천 (C3). 기본 버전은 승격 테이블 기준
    expected = DEFAULT_VERSIONS.get(agent, "v1")
    assert spec.version == f"{agent}/{expected}"


def test_few_shot_appended_when_present():
    spec = load_prompt("rule_auditor")  # 2026-07-15 보강으로 few_shot 2건 보유
    assembled = spec.system_with_few_shot()
    assert assembled != spec.system and assembled.startswith(spec.system)
    assert "예시 1" in assembled and "예시 2" in assembled


def test_empty_few_shot_returns_system_unchanged():
    # v1을 명시 — v2 승격(few_shot 3종)으로 기본 로드는 더 이상 빈 few_shot이 아님
    spec = load_prompt("policy_drafter", "v1")
    assert spec.few_shot == []
    assert spec.system_with_few_shot() == spec.system


def test_load_prompt_is_cached():
    assert load_prompt("adjudicator") is load_prompt("adjudicator")


def test_every_prompt_yaml_loads_and_is_consistent():
    """prompts/*/*.yaml 전수 — 미승격 신규 버전 파일도 로드·C3 계약(4키·version 정합) 검증."""
    import yaml

    from app.llm.prompts import _PROMPTS_DIR

    files = sorted(_PROMPTS_DIR.glob("*/*.yaml"))
    assert files, "prompts/ 하위에 YAML이 없음"
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["version"] == f"{path.parent.name}/{path.stem}", path
        assert data["system"].strip(), path
        few_shot = data.get("few_shot") or []
        assert isinstance(few_shot, list), path
        for ex in few_shot:
            assert "input" in ex and "output" in ex, path


def test_env_override_selects_version(monkeypatch, tmp_path):
    """PROMPT_VERSION_{AGENT} 오버라이드 — A/B 비교 러너(eval/compare_prompts.py)의 기반."""
    monkeypatch.setenv("PROMPT_VERSION_ADJUDICATOR", "v1")  # v1뿐이라 같은 파일로 검증
    assert load_prompt("adjudicator").version == "adjudicator/v1"
    monkeypatch.setenv("PROMPT_VERSION_ADJUDICATOR", "v999")
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        load_prompt("adjudicator")  # 없는 버전이면 조용히 폴백하지 않고 즉시 실패
