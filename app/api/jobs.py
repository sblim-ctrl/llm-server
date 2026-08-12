"""GET /v1/jobs/{job_id} — 잡 상태·결과 조회 (백엔드 폴링 fallback, §7.1)."""

from typing import Any

from fastapi import APIRouter, HTTPException

from app.db.pool import get_job
from app.graphs.review.nodes.callback import translate_precedent_citation
from app.schemas.analyze import JobStatusResponse

router = APIRouter(prefix="/v1", tags=["jobs"])


def translate_result_terms(result: Any) -> Any:
    """잡 결과의 판례 인용을 콜백과 같은 규칙으로 한국어화 (순수 함수).

    **왜 조회 시점인가** (#71). 용어 치환은 콜백 조립부에만 있었고
    `worker.py`는 치환 전 원본 opinions를 `jobs.result`에 저장한다. 그래서 콜백이
    유실돼 백엔드가 이 폴링 안전망(§7.1)으로 떨어지면 `(reject/ADMIN, override)`가
    그대로 도달했다. 저장 시점이 아니라 조회 시점에 거는 이유는 **이미 저장된 잡
    결과까지 함께 덮기 위해서**다 — 저장 시점에 걸면 이 배포 전에 쌓인 행은 계속
    원본을 내보낸다.

    결과 스키마는 잡 종류마다 다르고(`dead`면 `{"error", "message"}`) 심사 잡이
    아니면 opinions 자체가 없다 — 모양이 다르면 손대지 않고 그대로 돌려준다.
    """
    if not isinstance(result, dict):
        return result
    opinions = result.get("opinions")
    if not isinstance(opinions, list):
        return result
    translated = []
    for op in opinions:
        cases = op.get("similar_cases") if isinstance(op, dict) else None
        if isinstance(cases, list) and cases:
            op = {**op, "similar_cases": [translate_precedent_citation(str(c)) for c in cases]}
        translated.append(op)
    return {**result, "opinions": translated}


@router.get(
    "/jobs/{job_id}", response_model=JobStatusResponse, summary="잡 상태·결과 조회 (콜백 안전망)"
)
async def read_job(job_id: str) -> JobStatusResponse:
    """심사·생성 잡의 진행 상태와 결과를 조회한다.

    콜백이 유실됐을 때의 **폴링 안전망**(§7.1). `job_id`는 우리 내부 id와 백엔드가
    발급한 jobId **둘 다** 받는다.

    `status`: `queued` → `running` → `succeeded` / `failed` / `dead`.
    `succeeded`면 `result`에 심사 결과(verdict·reasons·opinions 등)가 담긴다.
    `dead`(재시도 소진 최종 실패)면 `result`가
    `{"error": "<예외 클래스명>", "message": "<실패 사유>"}`로 채워진다 —
    `message`는 회칙 파싱 실패(`DocumentParseError` 계열)일 때만 원문이고, 그 외
    예외는 정형 문구라 관리자에게 그대로 보여줘도 된다.

    `result`의 판례 인용은 콜백과 **같은 문구**로 나간다 — 두 경로가 같은 심사를
    다르게 표기하면 안 되기 때문이다 (#71, `translate_result_terms` 참조).
    """
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=str(job["id"]),
        status=job["status"],
        attempts=job["attempts"],
        result=translate_result_terms(job["result"]),
        created_at=job["created_at"].isoformat(),
        updated_at=job["updated_at"].isoformat(),
    )
