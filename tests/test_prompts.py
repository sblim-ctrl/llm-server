"""프롬프트 로더 (B1) — YAML 4종 로드·version 필드 정합성."""

import pytest

from app.llm.prompts import load_prompt

AGENTS = [
    "adjudicator",
    "budget_planner",
    "classifier",
    "digest_writer",
    "intake",
    "policy_drafter",
    "precedent_auditor",
    "rule_amendment",
    "rule_auditor",
]  # 9종 union — B-5 크로스 수정(C3) + A-7 digest_writer


@pytest.mark.parametrize("agent", AGENTS)
def test_loads_and_has_required_fields(agent):
    spec = load_prompt(agent)
    assert spec.system.strip()
    assert spec.version == f"{agent}/v1"  # YAML 내부 version: 필드가 진실 원천 (C3)


def test_few_shot_appended_when_present():
    spec = load_prompt("rule_auditor")  # 2026-07-15 보강으로 few_shot 2건 보유
    assembled = spec.system_with_few_shot()
    assert assembled != spec.system and assembled.startswith(spec.system)
    assert "예시 1" in assembled and "예시 2" in assembled


def test_empty_few_shot_returns_system_unchanged():
    spec = load_prompt("policy_drafter")  # few_shot=[] 유지 중
    assert spec.system_with_few_shot() == spec.system


def test_load_prompt_is_cached():
    assert load_prompt("adjudicator") is load_prompt("adjudicator")


def test_env_override_selects_version(monkeypatch, tmp_path):
    """PROMPT_VERSION_{AGENT} 오버라이드 — A/B 비교 러너(eval/compare_prompts.py)의 기반."""
    monkeypatch.setenv("PROMPT_VERSION_ADJUDICATOR", "v1")  # v1뿐이라 같은 파일로 검증
    assert load_prompt("adjudicator").version == "adjudicator/v1"
    monkeypatch.setenv("PROMPT_VERSION_ADJUDICATOR", "v999")
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        load_prompt("adjudicator")  # 없는 버전이면 조용히 폴백하지 않고 즉시 실패
