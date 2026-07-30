"""동시요청·멱등성 스트레스 테스트 (PROGRESS §6-5) — Idempotency 설계 실증.

같은 expense_id로 POST /v1/analyze를 동시에 20번 쏘면:
  ① 20개 응답의 job_id가 전부 동일해야 하고 (멱등 수락 — uq_jobs_active_review)
  ② 워커 처리 후에도 결과(verdict)가 1건만 존재해야 하며
  ③ 잡 완료 뒤 같은 지출을 다시 제출하면 새 잡이 생겨야 한다 (재심사 허용).
대조군: 서로 다른 expense_id 5건 동시 제출 → 5건 모두 개별 잡.

전제: docker compose up -d (API 8000 + 워커 + postgres) 또는 로컬 API·워커 기동.
실행: uv run python scripts/stress_idempotency.py
"""
import asyncio
import sys
import uuid
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402

BASE_URL = "http://localhost:8000"
CONCURRENCY = 20
JOB_TIMEOUT_SEC = 60


def _payload(expense_id: int) -> dict:
    # pull 모델 5필드 (bravo 설계서 TABLE 18). jobId는 매 제출마다 새로 발급된다고
    # 가정(백엔드 재제출 시나리오) — 그래도 같은 expense_id면 내부 잡은 1개여야 한다.
    return {
        "jobId": f"be-job-{uuid.uuid4().hex[:12]}",
        "expenseId": expense_id,
        "organizationId": 1,
        "reviewGoal": "회칙·예산·판례에 근거해 이 지출의 승인 여부를 심사하라",
        "receiptPath": f"https://example.com/r/{expense_id}",
    }


async def _submit(client: httpx.AsyncClient, expense_id: int) -> str:
    r = await client.post("/v1/analyze", json=_payload(expense_id))
    r.raise_for_status()
    return r.json()["job_id"]


async def _wait_done(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(JOB_TIMEOUT_SEC * 2):
        r = await client.get(f"/v1/jobs/{job_id}")
        r.raise_for_status()
        job = r.json()
        if job["status"] in ("succeeded", "failed", "dead"):
            return job
        await asyncio.sleep(0.5)
    raise TimeoutError(f"job {job_id} 미완료 ({JOB_TIMEOUT_SEC}s)")


async def main() -> int:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.service_token}"}
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30) as client:
        # ① 같은 expense_id 동시 제출 → 단일 잡
        dup_expense = uuid.uuid4().int % 9_000_000_000 + 1
        job_ids = await asyncio.gather(
            *[_submit(client, dup_expense) for _ in range(CONCURRENCY)])
        unique_ids = set(job_ids)
        print(f"[1] 동일 지출 {CONCURRENCY}건 동시 제출 → 잡 {len(unique_ids)}개: {unique_ids}")
        if len(unique_ids) != 1:
            failures.append(f"동시 제출이 잡 {len(unique_ids)}개 생성 (기대 1개)")

        # ② 처리 완료 후 결과 1건
        job = await _wait_done(client, job_ids[0])
        print(f"[2] 잡 완료 status={job['status']} verdict={ (job.get('result') or {}).get('verdict') }")
        if job["status"] != "succeeded":
            failures.append(f"잡 상태 {job['status']} (기대 succeeded)")

        # ③ 완료 뒤 재제출 → 새 잡 (재심사 허용)
        rerun_id = await _submit(client, dup_expense)
        print(f"[3] 완료 후 재제출 → 새 잡 {rerun_id} (기존과 다름: {rerun_id not in unique_ids})")
        if rerun_id in unique_ids:
            failures.append("완료된 지출 재제출이 기존 job_id를 반환 (재심사 불가)")
        await _wait_done(client, rerun_id)  # 다음 실행에 활성 잡을 남기지 않는다

        # ④ 대조군 — 서로 다른 expense_id는 각각 잡 생성
        ctrl_ids = await asyncio.gather(
            *[_submit(client, uuid.uuid4().int % 9_000_000_000 + 1) for _ in range(5)])
        print(f"[4] 개별 지출 5건 동시 제출 → 잡 {len(set(ctrl_ids))}개")
        if len(set(ctrl_ids)) != 5:
            failures.append(f"개별 지출 5건이 잡 {len(set(ctrl_ids))}개 생성 (기대 5개)")
        await asyncio.gather(*[_wait_done(client, j) for j in ctrl_ids])

    if failures:
        print("\n!! 실패:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("\n통과 — 동시 중복 제출은 단일 잡으로 수렴하고, 완료 후 재심사는 허용된다.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
