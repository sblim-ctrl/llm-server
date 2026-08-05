"""execute_decision — AI 판정 확정. 실행은 백엔드에 위임한다 (C2 콜백 단일화).

전에는 이 노드가 백엔드의 approve/reject API를 직접 호출했다. 그런데 그 API는
백엔드에 존재하지 않고, 만들 예정도 없다(`백엔드_요구_내부API_명세.md` §3 ⑨⑩ —
"현재 미사용 예정", "코드에 유지하되 호출하지 않는다"). 목 모드가 가짜 성공을
돌려주고 있어 골든셋·테스트에서는 드러나지 않았고, 실연동 첫 호출에서 404 →
raise_for_status() → 워커 재시도 3회 소진 → fail-safe 에스컬레이션으로 떨어졌을
것이다. 즉 **자동 승인·반려가 한 건도 성립하지 않고 자동 처리율이 0이 된다.**

C2(승인/반려 실행 주체)는 콜백 단일화로 사실상 확정됐다 — 2026-07-27 DB 스키마가
근거다. 내부 approve/reject API가 없고, `expenses.version` 낙관적 락과
`approved_by`·`processed_by`가 백엔드 소유이며, 명세에 "직접 UPDATE 금지"가 있다.
상태 전이와 예산 차감은 백엔드 트랜잭션 안에서 일어나야 정합이 맞는다.

그래서 우리는 판정만 확정하고 콜백(callback 노드)으로 추천을 보낸다. 규율 3
"AI는 승인/반려를 실행하지 않는다"와 코드가 이제 일치한다.

노드를 그래프에서 빼지 않고 남긴 이유: 체크포인트 재개 경로와 그래프 형태를
바꾸지 않기 위해서다. C2 잔여 2건(콜백 응답에 최종 전이결과 포함 여부, 멱등성
책임 소재)이 확정돼 실행 호출이 필요해지면 이 자리에 다시 붙이면 된다.
"""
import logging

from app.graphs.review.state import ReviewState

logger = logging.getLogger(__name__)


async def execute_decision(state: ReviewState) -> dict:
    """판정을 확정하고 실행 위임 사실을 기록한다. 외부 호출 없음.

    `idempotency_key`로 job_id를 남겨 둔다 — 콜백이 중복 도착했을 때 백엔드가
    이 값으로 이중 처리를 막을 수 있다(C2 잔여 항목). 콜백 페이로드의 `jobId`와
    같은 값이다.
    """
    verdict = state["verdict"]
    result = {
        "status": "delegated_to_backend",
        "verdict": verdict,
        "idempotency_key": state["job_id"],
    }
    logger.info(
        "decision %s for expense=%s — 콜백으로 추천 전달(실행은 백엔드 소유)",
        verdict, state["expense_id"],
    )
    return {"execution_result": result}
