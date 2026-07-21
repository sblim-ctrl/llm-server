"""B-8 — 예산·개정 제안 실모드 검증 하네스 (구 B7a).

BudgetPlanner·rule_amendment 그래프의 실키 연동(C4), detect_repeated_overrides의
의미 유사 군집 탐지(목 해시 임베딩으론 불가한 검증), jobs 테이블 cost/tokens 실측
기록(B-7 계측), LangSmith C9 태깅 배선(run_name·tags·prompt_version)을 실키·실DB로
검증한다.

전제: `docker compose up -d llm-postgres` 기동 + 실 OPENAI_API_KEY 확보.
.env의 MOCK_LLM=true는 그대로 두고, 이 스크립트 실행 시에만 프로세스 환경변수로
MOCK_LLM=false를 주입한다(A-9 실모드 검증과 동일 패턴, README 참고) — .env를 통째로
바꾸면 전체 pytest가 실과금을 시도한다.

실행: MOCK_LLM=false OPENAI_API_KEY=sk-... uv run python scripts/verify_realmode_proposals.py
(LangSmith 트레이스까지 확인하려면 LANGSMITH_TRACING=true LANGSMITH_API_KEY=... 추가)

주의: 실행하면 실제 OpenAI 과금이 발생한다 (LLM 호출 2회 + 임베딩 호출 4회).
"""

import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402
from app.db.pool import apply_schema, close_pool, get_job, get_pool, insert_job, open_pool  # noqa: E402
from app.llm.client import _mock_embedding  # noqa: E402
from app.observability import setup_langsmith  # noqa: E402
from app.schemas.proposals import ProposalBudgetRequest, RuleAmendmentRequest  # noqa: E402
from app.tools.detect_repeated_overrides import SIMILARITY_THRESHOLD, detect_repeated_overrides  # noqa: E402
from app.tools.precedent_store import save_precedent  # noqa: E402
from app.worker import handle_job  # noqa: E402

TEAM = "b8-verify"

# 의미 유사·바이트 비동일 ADMIN override 요약 4건 (B-8 ② — 목 해시 임베딩으론 군집
# 불가하고, 실임베딩만 의미 유사도를 잡아낸다는 것을 증명하는 시드).
# 대조: seed_demo.py의 B-6 시드는 바이트 동일 요약이라 목 임베딩(distance 0)으로도
# 군집된다 — B-8은 그보다 강한 "의미만 같고 바이트는 다른" 케이스를 검증한다.
SEMANTIC_OVERRIDE_SUMMARIES = [
    "[식비] 마감 야근 야식 — 42,000원. 마감 임박 심야 작업 중 야식 주문, 정기 회식 한도 초과분 관리자 재량 승인",
    "[식비] 프로젝트 마감 저녁 식사 — 41,500원. 늦은 시간까지 근무하며 저녁 식사비가 한도를 넘어 재량 승인",
    "[식비] 밤샘 작업 간식·야식 — 43,000원. 마감 압박으로 심야 작업 중 발생한 식비 한도 초과를 예외 승인",
    "[식비] 늦은 업무 식사비 — 40,800원. 마감 대응 야근으로 식사비가 한도를 초과해 재량으로 승인",
]


def _guard_realmode() -> None:
    """MOCK_LLM=false + 실키가 아니면 즉시 종료 — 목 모드가 실검증인 척하는 것을 차단."""
    s = get_settings()
    if s.mock_llm or not s.openai_api_key:
        print(
            "실모드 검증은 MOCK_LLM=false + OPENAI_API_KEY가 필요합니다. 예:\n"
            "  MOCK_LLM=false OPENAI_API_KEY=sk-... uv run python "
            "scripts/verify_realmode_proposals.py\n"
            "(.env 자체는 MOCK_LLM=true로 유지 — 프로세스 환경변수로만 주입, README 참고)"
        )
        sys.exit(1)


async def _reset_team(team_id: str) -> None:
    async with get_pool().connection() as conn:
        await conn.execute("DELETE FROM precedents WHERE team_id = %s", (team_id,))
        await conn.execute("DELETE FROM proposals WHERE team_id = %s", (team_id,))
        await conn.execute("DELETE FROM jobs WHERE team_id = %s", (team_id,))


async def _seed_semantic_overrides(team_id: str) -> None:
    for summary in SEMANTIC_OVERRIDE_SUMMARIES:
        await save_precedent(
            team_id=team_id,
            summary=summary,
            decision="approve",
            decided_by="ADMIN",
            is_override=True,
            reason="마감 대응 야근 식비 한도 초과 재량 승인",
        )


async def _pairwise_real_distances(team_id: str) -> list[float]:
    """방금 심은 override 판례들의 실측 코사인 거리(pgvector <=>) — 군집 임계 대비 진단용."""
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT (a.embedding <=> b.embedding) AS distance
               FROM precedents a JOIN precedents b
                 ON b.team_id = a.team_id AND a.id < b.id
               WHERE a.team_id = %s AND a.decided_by = 'ADMIN' AND a.is_override
                 AND b.decided_by = 'ADMIN' AND b.is_override""",
                (team_id,),
            )
        ).fetchall()
    return [float(r["distance"]) for r in rows]


def _mock_pairwise_distances() -> list[float]:
    """같은 요약들의 목 해시 임베딩 쌍거리 — 목으론 의미 유사 군집이 불가함을 보이는 대조군."""
    vectors = [_mock_embedding(s) for s in SEMANTIC_OVERRIDE_SUMMARIES]
    out = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            a, b = vectors[i], vectors[j]
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(y * y for y in b) ** 0.5
            out.append(1 - dot / (na * nb))
    return out


async def _run_proposal_job(job_type: str, payload: dict) -> dict:
    """proposal_budget|proposal_rule_amendment 잡을 워커 handle_job 경로로 실행하고
    (B-7 실측 계측 포함) 최종 jobs 행을 반환한다. GET /v1/jobs는 cost/tokens를
    노출하지 않으므로(app/api/jobs.py) jobs 테이블을 직접 조회해 확인한다."""
    job_id = await insert_job(team_id=TEAM, job_type=job_type, payload=payload)
    job = await get_job(job_id)
    await handle_job(job)
    return await get_job(job_id)


async def main() -> int:
    _guard_realmode()
    failures: list[str] = []
    langsmith_on = setup_langsmith()
    await open_pool()
    await apply_schema()

    try:
        await _reset_team(TEAM)

        # ── ② 의미 유사 군집 — 목 vs 실 임베딩 대조 ──────────────────────
        print("[1] 의미 유사·바이트 비동일 override 판례 4건 시드 (실임베딩)")
        await _seed_semantic_overrides(TEAM)

        mock_dists = _mock_pairwise_distances()
        print(
            f"    목 해시 임베딩 쌍거리: {[round(d, 3) for d in mock_dists]} "
            f"(임계 {SIMILARITY_THRESHOLD} 이내가 없어야 함 — 의미 유사도 없음)"
        )
        if any(d < SIMILARITY_THRESHOLD for d in mock_dists):
            failures.append(
                "목 해시 임베딩이 의미 유사 판례를 군집시킴 (기대와 다름 — "
                "_mock_embedding 변경 여부 확인, C10)"
            )

        real_dists = await _pairwise_real_distances(TEAM)
        print(f"    실 임베딩 쌍거리: {[round(d, 3) for d in real_dists]}")

        clusters = await detect_repeated_overrides(TEAM, threshold=3)
        if not clusters or clusters[0]["count"] < 3:
            failures.append(
                f"detect_repeated_overrides가 의미 유사 판례를 군집시키지 못함 "
                f"(실거리={[round(d, 3) for d in real_dists]}, 임계={SIMILARITY_THRESHOLD} — "
                "실측 거리가 임계 부근이면 detect_repeated_overrides.py의 "
                "SIMILARITY_THRESHOLD 튜닝 검토, A-9의 RELEVANCE_MAX_DISTANCE 0.5→0.65 선례 참고)"
            )
        else:
            print(
                f"    detect_repeated_overrides 군집 검출: count={clusters[0]['count']} "
                "(의미 유사 군집 실키 검증 통과 — 목 해시로는 불가능한 결과)"
            )

        # ── ①③ BudgetPlanner 실모드 + jobs 계측 ──────────────────────────
        print("\n[2] BudgetPlanner 실모드 잡 실행 (proposal_budget)")
        req = ProposalBudgetRequest(team_id=TEAM)
        job = await _run_proposal_job("proposal_budget", req.model_dump(mode="json"))
        print(
            f"    status={job['status']} cost_usd={job['cost_usd']} "
            f"tokens_in={job['tokens_in']} tokens_out={job['tokens_out']} "
            f"proposal_id={(job['result'] or {}).get('proposal_id')}"
        )
        if job["status"] != "succeeded":
            failures.append(
                f"proposal_budget 잡 실패: status={job['status']} result={job['result']}"
            )
        if not (job["cost_usd"] and job["cost_usd"] > 0):
            failures.append("proposal_budget 잡의 jobs.cost_usd가 실측되지 않음 (B-7 계측)")
        if not (job["tokens_in"] and job["tokens_out"]):
            failures.append("proposal_budget 잡의 jobs.tokens_in/out이 실측되지 않음 (B-7 계측)")

        # ── ①③ rule_amendment 실모드 + jobs 계측 ─────────────────────────
        print("\n[3] rule_amendment 실모드 잡 실행 (proposal_rule_amendment)")
        req2 = RuleAmendmentRequest(team_id=TEAM)
        job2 = await _run_proposal_job("proposal_rule_amendment", req2.model_dump(mode="json"))
        proposals = (job2["result"] or {}).get("proposals") or []
        print(
            f"    status={job2['status']} cost_usd={job2['cost_usd']} "
            f"tokens_in={job2['tokens_in']} tokens_out={job2['tokens_out']} "
            f"proposals={len(proposals)}건"
        )
        if job2["status"] != "succeeded":
            failures.append(
                f"proposal_rule_amendment 잡 실패: status={job2['status']} result={job2['result']}"
            )
        if not proposals:
            failures.append(
                f"rule_amendment이 제안을 생성하지 못함 "
                f"(reason={(job2['result'] or {}).get('reason')}) — [1] 군집 검출 실패와 연동된 결과일 수 있음"
            )
        if not (job2["cost_usd"] and job2["cost_usd"] > 0):
            failures.append("proposal_rule_amendment 잡의 jobs.cost_usd가 실측되지 않음 (B-7 계측)")
        if not (job2["tokens_in"] and job2["tokens_out"]):
            failures.append(
                "proposal_rule_amendment 잡의 jobs.tokens_in/out이 실측되지 않음 (B-7 계측)"
            )

        # ── ④ LangSmith C9 태깅 ───────────────────────────────────────────
        print("\n[4] LangSmith C9 태깅 (run_name·tags·prompt_version)")
        print(f"    tracing={'ON' if langsmith_on else 'OFF (LANGSMITH_TRACING=true 필요)'}")
        print(f"    run_name=proposal_budget:{job['id']} tags=[{TEAM}]")
        print(f"    run_name=proposal_rule_amendment:{job2['id']} tags=[{TEAM}]")
        if langsmith_on:
            try:
                from langsmith import Client

                client = Client()
                for job_type, jid in (
                    ("proposal_budget", job["id"]),
                    ("proposal_rule_amendment", job2["id"]),
                ):
                    run_name = f"{job_type}:{jid}"
                    runs = list(
                        client.list_runs(
                            project_name=get_settings().langsmith_project,
                            filter=f'eq(name, "{run_name}")',
                            limit=1,
                        )
                    )
                    if not runs:
                        failures.append(f"LangSmith에서 run_name={run_name} 트레이스를 찾지 못함")
                    else:
                        print(f"    확인됨: {run_name} tags={runs[0].tags}")
            except ImportError:
                print(
                    "    langsmith 패키지 미설치 — 위 run_name으로 LangSmith UI에서 수동 확인하세요."
                )
            except Exception as e:
                print(f"    LangSmith 역조회 실패(수동 확인 필요): {e}")
        else:
            print("    위 run_name으로 LangSmith UI에서 수동 확인하세요.")

        print(f"\n총 실측 비용: ${(job['cost_usd'] or 0) + (job2['cost_usd'] or 0):.6f}")
    finally:
        await close_pool()

    if failures:
        print("\n!! 실패:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("\n통과 — BudgetPlanner·rule_amendment 실모드, 의미 유사 군집, jobs 계측 전부 확인됨.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
