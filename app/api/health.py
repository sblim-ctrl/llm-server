"""/healthz (liveness) · /readyz (readiness — DB + LLM 준비) (§10.2).

readyz는 배포 오케스트레이터의 readiness probe 대상이라 자주 호출된다:
- 기본: DB 도달성 + LLM '설정' 확인 (실모드인데 키가 없으면 not_ready) — 빠름, 무비용.
- deep=true: 실제 OpenAI 도달성까지 확인(models.list — 토큰 과금 없음). 배포 직후
  수동 점검용 — probe가 매번 외부 API를 치지 않도록 기본은 얕은 확인.
"""
from fastapi import APIRouter, Response

from app.config import DEFAULT_SERVICE_TOKEN, get_settings
from app.db.pool import get_pool

router = APIRouter(tags=["health"])


def check_config_ready() -> tuple[bool, str]:
    """운영 설정 점검 — (ready, 상태문자열). 순수 헬퍼(단위 테스트 대상).

    설정 기본값이 전부 '개발에서 바로 뜨는' 쪽으로 잡혀 있어, 배포 시 환경변수를
    빠뜨리면 조용히 통과한다. 그 실패가 겉으로는 정상 동작처럼 보이는 것이 문제다.

    - 기본 서비스 토큰: 리포를 볼 수 있으면 누구나 아는 값이라 인증이 없는 것과 같다
    - 목 백엔드: 실모드 LLM이 목 데이터로 진짜 판정을 내리게 된다

    실모드(mock_llm=False)만 운영으로 간주해 검사한다. 목 모드는 개발·테스트라
    기본값이 정상이다. 실모드 평가 러너(run_eval_real)는 서버를 띄우지 않으므로
    이 검사에 걸리지 않는다.
    """
    s = get_settings()
    if s.mock_llm:
        return True, "mock"
    if s.service_token == DEFAULT_SERVICE_TOKEN:
        return False, "default_service_token"
    if s.mock_backend:
        return False, "mock_backend_in_real_mode"
    return True, "ok"


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


async def check_llm_ready(deep: bool = False) -> tuple[bool, str]:
    """LLM 준비 상태 — (ready, 상태문자열). 순수 헬퍼(단위 테스트 대상).

    목 모드: 키 없이도 ready("mock"). 실모드: 키 없으면 not_ready("missing_key"),
    deep이면 실제 도달성까지("configured" | "unreachable").
    """
    s = get_settings()
    if s.mock_llm:
        return True, "mock"
    if not s.openai_api_key:
        return False, "missing_key"
    if deep:
        try:
            from openai import AsyncOpenAI  # 지연 임포트 — 목 모드 부팅엔 불필요
            await AsyncOpenAI(api_key=s.openai_api_key).models.list()
        except Exception:
            return False, "unreachable"
    return True, "configured"


@router.get("/readyz")
async def readyz(response: Response, deep: bool = False):
    db_ok = True
    try:
        async with get_pool().connection() as conn:
            await conn.execute("SELECT 1")
    except Exception:
        db_ok = False

    llm_ok, llm_status = await check_llm_ready(deep)
    cfg_ok, cfg_status = check_config_ready()

    if not (db_ok and llm_ok and cfg_ok):
        response.status_code = 503
        return {"status": "not_ready",
                "db": "ok" if db_ok else "unreachable",
                "llm": llm_status,
                "config": cfg_status}
    return {"status": "ready", "db": "ok", "llm": llm_status, "config": cfg_status}
