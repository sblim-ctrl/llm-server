"""라이터 골든셋 평가 로직 — CLI(eval/run_eval_writers.py)와 대시보드 API가 공유.

심사 골든셋(app/eval_support.py)과 같은 구조. 다른 점 하나 — 심사의 하드 게이트가
'오승인 0건'이라면, 라이터 7종의 하드 게이트는 'verified=false 0건'이다
(Generator-Evaluator 검증을 통과 못 한 산출물이 하나라도 나오면 실패).

briefing·digest·rule_amendment 케이스는 실행 전 해당 팀 판례를 DB에 시드한다
(팀 단위 삭제 후 재삽입 — 멱등). 시드가 save_precedent를 그대로 쓰므로
마스킹·임베딩 경로까지 실제 저장 경로와 동일하게 지나간다.
"""

import csv
import json
from pathlib import Path
from typing import Any

from app.db.pool import get_pool
from app.graphs.writers.briefing import briefing_graph
from app.graphs.writers.budget_planner import budget_planner_graph
from app.graphs.writers.dashboard import dashboard_graph
from app.graphs.writers.digest import digest_graph
from app.graphs.writers.policy_draft import policy_draft_graph
from app.graphs.writers.report import report_graph
from app.graphs.writers.rule_amendment import rule_amendment_graph
from app.schemas.dashboard import DashboardSummaryRequest
from app.schemas.proposals import ProposalBudgetRequest, RuleAmendmentRequest
from app.schemas.writers import (
    BriefingRequest,
    DigestRequest,
    PolicyDraftRequest,
    ReportRequest,
)
from app.tools.precedent_store import save_precedent

ACCURACY_THRESHOLD = 0.90  # eval_support와 동일 기준
DEFAULT_GOLDEN_PATH = (
    Path(__file__).resolve().parents[1] / "eval" / "golden" / "writers_golden_v1.json"
)
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"


def evaluate_expectations(expect: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """expect 대 actual 대조 — 실패한 검사 설명 목록 반환 (통과 시 빈 목록). 순수 함수.

    규칙: `<필드>_contain`은 actual의 `<필드>_text`에 부분 문자열이 모두 있어야 하고,
    `<필드>_not_contain`은 하나도 없어야 한다. 그 외 키는 동등 비교.
    """
    failures: list[str] = []
    for key, want in expect.items():
        if key.endswith("_not_contain"):
            text = actual.get(key[: -len("_not_contain")] + "_text", "")
            failures += [f"{key}: '{s}' 포함되면 안 됨" for s in want if s in text]
        elif key.endswith("_contain"):
            text = actual.get(key[: -len("_contain")] + "_text", "")
            failures += [f"{key}: '{s}' 없음" for s in want if s not in text]
        elif actual.get(key) != want:
            failures.append(f"{key}: 기대={want!r} 실제={actual.get(key)!r}")
    return failures


async def _run_policy_draft_case(case: dict[str, Any]) -> dict[str, Any]:
    req = PolicyDraftRequest.model_validate(case["input"])
    state = await policy_draft_graph.ainvoke({"request": req})
    draft = state["draft"]
    return {
        "verified": state.get("verified"),
        "verify_error": state.get("verify_error"),
        "rules_count": len(draft.rules),
        "categories_count": len(draft.recommended_categories),
        "rules_text": "\n".join(draft.rules),
    }


async def _run_report_case(case: dict[str, Any]) -> dict[str, Any]:
    req = ReportRequest.model_validate(case["input"])
    state = await report_graph.ainvoke({"request": req})
    report = state["report"]
    figures = report.figures
    return {
        "verified": report.verified,
        "total_spent": figures.total_spent,
        "expense_count": figures.expense_count,
        "top_category": figures.by_category[0].category if figures.by_category else None,
        "recommendations_count": len(report.recommendations),
        "recommendations_text": "\n".join(report.recommendations),
    }


async def _seed_briefing_precedents(team_id: int, precedents: list[dict[str, Any]]) -> None:
    """케이스 판례를 DB에 시드 — 팀 단위 삭제 후 재삽입이라 재실행해도 결과 동일."""
    async with get_pool().connection() as conn:
        await conn.execute("DELETE FROM precedents WHERE team_id = %s", (team_id,))
    for p in precedents:
        summary = f"[{p['category']}] {p['title']} — {p['amount']:,}원."
        await save_precedent(
            team_id,
            summary,
            p["decision"],
            p["decided_by"],
            reason=p.get("reason"),
            is_override=p.get("is_override", False),
            # digest 케이스는 판례가 **그 주에** 있어야 주간 집계에 잡힌다.
            # briefing은 기간을 안 보므로 이 키가 없어도 된다.
            created_at=p.get("date"),
        )


async def _run_briefing_case(case: dict[str, Any]) -> dict[str, Any]:
    await _seed_briefing_precedents(case["team_id"], case["precedents"])
    state = await briefing_graph.ainvoke({"request": BriefingRequest(team_id=case["team_id"])})
    briefing = state["briefing"]
    figures = briefing.figures
    return {
        "verified": briefing.verified,
        "total_precedents": figures.total_precedents,
        "agent_decisions": figures.agent_decisions,
        "admin_decisions": figures.admin_decisions,
        "override_count": figures.override_count,
        "escalated_count": figures.escalated_count,
        "gap_categories": figures.gap_categories,
        "notes_text": "\n".join(briefing.handover_notes),
    }


async def _run_digest_case(case: dict[str, Any]) -> dict[str, Any]:
    """주간 브리핑 — 판례를 그 주에 심고 집계·문장을 함께 본다.

    2026-08-07까지 골든셋에 없던 종이다. 그래서 판례(=승인·반려·에스컬레이션 건수)와
    지출(=주간 지출)의 시간축이 어긋나 어떤 주를 골라도 한쪽이 0으로 나오던 것이
    평가에 한 번도 잡히지 않았다.
    """
    await _seed_briefing_precedents(case["team_id"], case.get("precedents", []))
    state = await digest_graph.ainvoke({"request": DigestRequest.model_validate(case["input"])})
    doc = state["digest"]
    f = doc.figures
    return {
        "verified": doc.verified,
        "auto_approved": f.auto_approved,
        "auto_rejected": f.auto_rejected,
        "escalated": f.escalated,
        "weekly_spent": f.weekly_spent,
        "projected_period_end_spent": f.forecast.projected_period_end_spent,
        "highlights_count": len(doc.highlights),
        "summary_text": doc.summary,
        "highlights_text": "\n".join(doc.highlights),
        "advice_text": doc.advice or "",
    }


async def _run_budget_proposal_case(case: dict[str, Any]) -> dict[str, Any]:
    """예산 제안 3블록 — T4(LLM-016)로 계약이 바뀐 뒤 골든셋에 편입되지 않았던 종."""
    req = ProposalBudgetRequest.model_validate(case["input"])
    state = await budget_planner_graph.ainvoke({"request": req})
    payload = state["payload"]
    figures = payload["figures"]
    return {
        "verified": state.get("verified"),
        "usage_ratio_pct": round(figures["usage_ratio"] * 100),
        "remaining": figures["remaining"],
        "category_analysis_text": payload["category_analysis"],
        "budget_status_analysis_text": payload["budget_status_analysis"],
        "recommendation_text": payload["recommendation"],
    }


async def _run_dashboard_case(case: dict[str, Any]) -> dict[str, Any]:
    """대시보드 AI 요약 — 검증 실패 시 집계로 조립한 안전한 문장으로 교체된다."""
    req = DashboardSummaryRequest.model_validate(case["input"])
    state = await dashboard_graph.ainvoke({"request": req})
    doc = state["doc"]
    return {
        "verified": doc.verified,
        "message_text": doc.message,
        "pending_count": doc.figures.pending_count,
        "pending_amount": doc.figures.pending_amount,
    }


async def _run_rule_amendment_case(case: dict[str, Any]) -> dict[str, Any]:
    """회칙 개정 제안 — 판례를 **바이트 동일 요약**으로 심어 군집을 만든다.

    목 임베딩은 해시 기반이라 의미 유사도가 없고 동일 문자열만 distance 0이다
    (detect_repeated_overrides [C10]). 그래서 군집으로 묶일 판례는 시드의
    category·title·amount가 전부 같아야 한다. 임계(3건) 미달이면 그래프가 초안
    없이 reason으로 정상 종료하며, verified는 null로 남는다(하드 게이트 미해당) —
    그 경로도 케이스로 본다.
    """
    await _seed_briefing_precedents(case["team_id"], case.get("precedents", []))
    async with get_pool().connection() as conn:
        # save 노드가 proposals에 행을 쓴다 — 재실행 누적을 막는다 (시드와 같은 멱등 규칙).
        await conn.execute(
            "DELETE FROM proposals WHERE team_id = %s AND type = 'rule_amendment'",
            (case["team_id"],),
        )
    state = await rule_amendment_graph.ainvoke(
        {"request": RuleAmendmentRequest(team_id=case["team_id"])}
    )
    clusters = state.get("clusters", [])
    drafts = state.get("drafts", [])
    return {
        "verified": state.get("verified"),
        "reason": state.get("reason"),
        "cluster_counts": [c["count"] for c in clusters],
        "proposals_count": len(state.get("proposal_ids", [])),
        "amendment_text": "\n".join(d.amendment for d in drafts),
        "rationale_text": "\n".join(d.rationale for d in drafts),
    }


# 2026-08-07: 종전에는 3종(policy_draft·report·briefing)만 돌았다. 나머지 4종은
# 단위 테스트만 있고 **출력 품질을 채점하는 그물이 없었다** — `GET /v1/eval/writers`가
# "라이터 품질"로 보고하는 수치가 절반도 안 보던 셈이다. 같은 날 digest·
# budget_proposal·dashboard에 이어 rule_amendment까지 편입해 7종 전부가 들어왔다.
_RUNNERS = [
    ("policy_draft", "policy_draft_cases", _run_policy_draft_case),
    ("report", "report_cases", _run_report_case),
    ("briefing", "briefing_cases", _run_briefing_case),
    ("digest", "digest_cases", _run_digest_case),
    ("budget_proposal", "budget_proposal_cases", _run_budget_proposal_case),
    ("dashboard", "dashboard_cases", _run_dashboard_case),
    ("rule_amendment", "rule_amendment_cases", _run_rule_amendment_case),
]


async def run_writers_golden_set(golden_path: Path | None = None) -> dict[str, Any]:
    golden_path = golden_path or DEFAULT_GOLDEN_PATH
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    results: list[dict[str, Any]] = []
    for kind, section, runner in _RUNNERS:
        for case in golden.get(section, []):
            actual = await runner(case)
            failures = evaluate_expectations(case["expect"], actual)
            results.append(
                {
                    "kind": kind,
                    "id": case["id"],
                    "scenario": case.get("scenario", ""),
                    "passed": not failures,
                    "verified": actual.get("verified"),
                    "failures": failures,
                }
            )

    correct = sum(r["passed"] for r in results)
    unverified = [r["id"] for r in results if r["verified"] is False]
    accuracy = correct / len(results) if results else 0.0

    summary = {
        "version": golden["version"],
        "total": len(results),
        "correct": correct,
        "accuracy": accuracy,
        "accuracy_threshold": ACCURACY_THRESHOLD,
        "unverified_count": len(unverified),  # 하드 게이트 — 검증 불통과 산출물 0건
        "unverified_ids": unverified,
        "passed": not unverified and accuracy >= ACCURACY_THRESHOLD,
        "results": results,
    }
    summary["csv_path"] = str(export_writers_csv(results))
    return summary


def export_writers_csv(results: list[dict[str, Any]]) -> Path:
    """평가 결과 CSV — 심사 골든셋의 golden_run.csv와 나란히 저장. 매 실행 시 덮어씀."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "writers_golden_run.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM — 엑셀 한글 호환
        writer = csv.writer(f)
        writer.writerow(["kind", "id", "scenario", "passed", "verified", "failures"])
        for r in results:
            writer.writerow(
                [
                    r["kind"],
                    r["id"],
                    r["scenario"],
                    r["passed"],
                    r["verified"],
                    " | ".join(r["failures"]),
                ]
            )
    return path
