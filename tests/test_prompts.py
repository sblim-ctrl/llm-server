"""프롬프트 로더 (B1) — YAML 4종 로드·version 필드 정합성."""
import pytest

from app.llm.prompts import load_prompt

AGENTS = ["adjudicator", "classifier", "policy_drafter", "precedent_auditor", "rule_auditor"]


@pytest.mark.parametrize("agent", AGENTS)
def test_loads_and_has_required_fields(agent):
    spec = load_prompt(agent)
    assert spec.system.strip()
    assert spec.version == f"{agent}/v1"  # YAML 내부 version: 필드가 진실 원천 (C3)


def test_few_shot_appended_when_present():
    spec = load_prompt("rule_auditor")
    assert spec.system_with_few_shot() == spec.system  # few_shot=[] → 원문 그대로


def test_load_prompt_is_cached():
    assert load_prompt("adjudicator") is load_prompt("adjudicator")
