"""POST /v1/dashboard/summary — 대시보드 AI 요약 (풀스택 협의 2026-08-04 5번).

**동기 방식**이다. 리포트·브리핑처럼 202로 접수하고 폴링하지 않는다 — 대시보드는
페이지를 열 때 뜨는 요약이라, 폴링하면 화면이 비어 있는 시간이 생긴다.
`POST /v1/policy-draft`와 같은 결정이다.

응답의 `verified`가 false면 요약문의 수치가 집계와 어긋난다는 뜻이다. 그때는 화면에
띄우지 마시거나 '확인 필요'로 표시해 주시면 된다 — 대시보드는 관리자가 예산 판단을
하는 화면이라 틀린 숫자가 그대로 보이는 것이 가장 나쁘다.
"""
from fastapi import APIRouter

from app.graphs.writers.dashboard import dashboard_graph
from app.schemas.dashboard import DashboardSummaryDoc, DashboardSummaryRequest

router = APIRouter(prefix="/v1", tags=["dashboard"])


@router.post("/dashboard/summary", response_model=DashboardSummaryDoc,
             summary="대시보드 AI 요약 생성")
async def create_dashboard_summary(req: DashboardSummaryRequest) -> DashboardSummaryDoc:
    """이번 달 지출 집계를 바탕으로 대시보드에 띄울 요약 2~4문장을 만든다.

    `message`를 화면에 그대로 띄우시면 된다. 함께 오는 `figures`는 그 문장이 어떤
    수치에서 나왔는지 대조할 재료이고, 화면에 꼭 쓰실 필요는 없다.

    수치는 전부 집계에서 나온다 — AI가 새 숫자를 만들지 않는다. 만들면 `verified`가
    false로 내려온다.

    지출이 없는 달이면 그 사실과 총예산만 담은 문장이 온다(빈 문자열이 아니다).
    """
    final = await dashboard_graph.ainvoke({"request": req})
    return final["doc"]
