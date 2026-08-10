"""rule_amendment 단위 테스트 — 군집 그룹핑·검증 순수 함수 + 목 노드 (DB 무접촉)."""

from langgraph.graph import END

import app.graphs.writers.rule_amendment as ra
from app.graphs.writers.rule_amendment import (
    NO_CLUSTER_REASON,
    AmendmentText,
    _has_clusters,
    _mock_amendment,
    detect,
    summarize_gap_pure,
    verify_amendment_pure,
)
from app.schemas.proposals import RuleAmendmentRequest
from app.tools.detect_repeated_overrides import _group_clusters


def _rows(ids_decisions):
    return [{"id": i, "expense_summary": f"요약-{i}", "decision": d} for i, d in ids_decisions]


def _cluster(count=3, ids=None):
    return {
        "cluster_summary": "[식비] 정기 회식 — 35,000원. 회식비 3.5만원",
        "count": count,
        "precedent_ids": ids if ids is not None else ["a", "b", "c"],
        "decisions": ["approve"] * count,
    }


def test_group_clusters_connected_component():
    rows = _rows([("a", "approve"), ("b", "approve"), ("c", "approve"), ("d", "reject")])
    clusters = _group_clusters(rows, [("a", "b"), ("b", "c")], threshold=3)  # d는 유일 건
    assert len(clusters) == 1
    assert clusters[0]["count"] == 3
    assert clusters[0]["precedent_ids"] == ["a", "b", "c"]
    assert clusters[0]["cluster_summary"] == "요약-a"


def test_group_clusters_below_threshold_filtered():
    rows = _rows([("a", "approve"), ("b", "approve")])
    assert _group_clusters(rows, [("a", "b")], threshold=3) == []


def test_group_clusters_sorted_by_count_desc():
    rows = _rows([(x, "approve") for x in "abcdefg"])
    edges = [("a", "b"), ("b", "c"), ("d", "e"), ("e", "f"), ("f", "g")]
    clusters = _group_clusters(rows, edges, threshold=3)
    assert [c["count"] for c in clusters] == [4, 3]


def test_mock_amendment_passes_verification():
    c = _cluster()
    d = _mock_amendment(c)
    assert "{" not in d.amendment + d.rationale  # placeholder 잔존 불가
    assert verify_amendment_pure([d], [c]) is None


def test_summarize_gap_deterministic():
    c = _cluster()
    assert summarize_gap_pure(c) == summarize_gap_pure(c)
    assert "3회" in summarize_gap_pure(c)


def test_verify_failure_reasons():
    c = _cluster()
    bad = AmendmentText(amendment="조항 {placeholder}", rationale="근거")
    assert verify_amendment_pure([bad], [c]) == "치환되지 않은 placeholder 존재"
    good = _mock_amendment(c)
    assert verify_amendment_pure([good], [_cluster(ids=[])]) == "근거 판례 id 없는 군집 존재"
    assert verify_amendment_pure([], [c]) == "초안 수가 군집 수와 다름"


async def test_detect_empty_returns_reason(monkeypatch):
    async def _none(team_id, threshold=3):
        return []

    monkeypatch.setattr(ra, "detect_repeated_overrides", _none)
    out = await detect({"request": RuleAmendmentRequest(team_id=1)})
    assert out == {"clusters": [], "reason": NO_CLUSTER_REASON}


def test_has_clusters_routing():
    assert _has_clusters({"clusters": [_cluster()]}) == "summarize_gap"
    assert _has_clusters({"clusters": []}) == END


async def test_draft_amendment_mock_meta():
    c = _cluster()
    out = await ra.draft_amendment({"clusters": [c], "gap_summaries": [summarize_gap_pure(c)]})
    assert out["drafts"][0].amendment
    meta = out["llm_meta"]["rule_amendment_0"]
    assert meta.mock is True
    assert meta.model == "gpt-4o"  # models.yaml rule_amendment 라우팅
    assert meta.prompt_version == "rule_amendment/v3"


async def test_save_skips_persistence_when_not_verified(monkeypatch):
    """검증 실패 시 save_proposal이 호출되지 않아야 한다 — 환각 문안 차단의 마지막 방어선."""
    calls = []

    async def fake_save_proposal(team_id, proposal_type, payload):
        calls.append((team_id, proposal_type, payload))
        return "should-not-be-reached"

    monkeypatch.setattr(ra, "save_proposal", fake_save_proposal)
    out = await ra.save({"verified": False})
    assert out == {"proposal_ids": []}
    assert calls == []


async def test_save_persists_per_cluster_when_verified(monkeypatch):
    calls = []

    async def fake_save_proposal(team_id, proposal_type, payload):
        calls.append((team_id, proposal_type, payload))
        return f"pid-{len(calls)}"

    monkeypatch.setattr(ra, "save_proposal", fake_save_proposal)
    c = _cluster()
    d = _mock_amendment(c)
    out = await ra.save(
        {
            "request": RuleAmendmentRequest(team_id=1),
            "clusters": [c],
            "drafts": [d],
            "verified": True,
        }
    )
    assert out["proposal_ids"] == ["pid-1"]
    assert len(calls) == 1
    assert calls[0][0] == 1
    assert calls[0][1] == "rule_amendment"
    assert calls[0][2]["precedent_ids"] == c["precedent_ids"]  # 근거 판례 id 배열
