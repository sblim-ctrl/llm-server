"""풀스택 백엔드 API 클라이언트 (§7.2 '백엔드 제공' 계약).

연동 방식이 확정되지 않았으므로 MOCK_BACKEND=true(기본)로 개발한다.
실제 엔드포인트 경로·인증이 확정되면 이 파일의 URL만 바꾸면 된다 — 노드 코드는 불변.
"""

import asyncio
import copy
import functools
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.writers import normalize_team_type
from app.tools.category_catalog import all_categories, fallback_category

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _PROJECT_ROOT / "eval" / "fixtures" / "mock_backend.json"

_http_client: httpx.AsyncClient | None = None


@functools.cache
def _fixtures() -> dict[str, Any]:
    """MOCK_BACKEND=true 목 데이터 — eval/fixtures/mock_backend.json 1회 로드 (T9).

    두 프로세스(api·worker)가 in-memory 시딩으로는 데이터를 못 주고받아 디스크
    파일을 공유 원천으로 쓴다. 반환값은 절대 그대로 넘기지 않는다 — 아래 조회
    헬퍼가 매번 사본을 만들어, 호출부가 결과를 변형해도 캐시 원본이 오염되지
    않게 한다.
    """
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_org(team_id: Any) -> dict[str, Any] | None:
    # deepcopy — organizations의 "budget"은 중첩 dict라 얕은 복사로는 캐시 원본과
    # 같은 객체를 공유한다(호출부의 변형이 프로세스 수명 내내 캐시를 오염시킴).
    org = _fixtures()["organizations"].get(str(team_id))
    return copy.deepcopy(org) if org is not None else None


def _fixture_expense(expense_id: Any) -> dict[str, Any] | None:
    expense = _fixtures()["expenses"].get(str(expense_id))
    return dict(expense) if expense is not None else None


def _fixture_history(name: str) -> list[dict[str, Any]]:
    rows = _fixtures()["expense_histories"].get(name, [])
    return [dict(r) for r in rows]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().service_token}"}


def _client() -> httpx.AsyncClient:
    """공유 AsyncClient — 호출마다 재생성하지 않는다 (연결 풀·keep-alive·TLS 재사용).

    구현 전에는 백엔드 호출 1건마다 클라이언트를 새로 만들어 매번 커넥션/TLS
    핸드셰이크를 치렀다 — 심사 1건이 백엔드를 5-6회 치므로 실배포 지연에 직결
    (Sprint 2 백로그 'httpx lifespan 공유' 이행). 종료 시 close_backend_client()
    호출 — api는 main.py lifespan, 워커는 main() finally에서.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        s = get_settings()
        _http_client = httpx.AsyncClient(
            base_url=s.backend_base_url, headers=_headers(), timeout=15
        )
    return _http_client


async def close_backend_client() -> None:
    """공유 클라이언트 정리 — 앱/워커 graceful shutdown 시 호출."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


def _normalize_budget(data: dict[str, Any]) -> dict[str, Any]:
    """예산 응답 키 흡수 — DB 표기(used_budget)·프론트 API 표기(usedBudget) 양쪽 수용.

    어느 표기도 없으면 KeyError를 그대로 낸다 — budget_auditor가 error 소견으로
    잡아 에스컬레이션되는 기존 실패 경로를 유지하기 위해서다 (0으로 때우면
    '잔액 0 → 반려'라는 틀린 근거가 만들어진다).
    """

    def pick(*keys: str) -> int:
        for k in keys:
            v = data.get(k)
            if v is not None:
                return int(v)
        raise KeyError(keys[0])

    return {
        "total_budget": pick("total_budget", "totalBudget"),
        "spent": pick("spent", "used_budget", "usedBudget"),
    }


async def get_budget_status(team_id: int, category: str | None = None) -> dict[str, Any]:
    """GET {BE}/internal/agent/teams/{id}/budget — 총예산·승인 지출 합계.

    [팀 확인 2026-07-09] 예산 = 모임 전체 총액. 잔액 = total_budget − spent(승인 합계).
    category는 내역 조회용 선택 파라미터 (한도 검사 기준 아님).

    응답 키 정규화: 내부 계약은 {total_budget, spent}로 고정하고 여기서만 흡수한다
    (budget_auditor·budget_calculator는 불변). 백엔드 DB 컬럼은 `used_budget`,
    프론트 API-026 응답은 `usedBudget`인데 내부 Agent API는 아직 미문서화라 어느
    표기로 올지 확정 불가 — 양쪽 다 받는다 (풀스택_문서_반영사항_2026-07-27.md §3-1).
    """
    s = get_settings()
    if s.mock_backend:
        org = _fixture_org(team_id)
        if org is not None:
            return dict(org["budget"])
        # fixture 미등재 ID의 기본 폴백: 총예산 30만, 승인 지출 11.8만
        return {"total_budget": 300_000, "spent": 118_000}
    r = await _client().get(
        f"/internal/agent/teams/{team_id}/budget",
        params={"category": category} if category else None,
    )
    r.raise_for_status()
    return _normalize_budget(r.json())


# 구 카테고리 → 전역 9종. 백엔드에서 읽어오는 값에만 쓴다(내보내는 값은 분류기가 이미 9종).
#
# 두 갈래가 섞여 있다. ① 2026-08-04 전역 9종 전환(830f0f7) 전에 우리가 유형별로 쓰던 28종
# ② 백엔드 구 ENUM 7종 중 사라지는 `행사`·`디자인`. 백엔드 마이그레이션 시점이 미정이라
# (2026-08-06 회신: "지출 등록·카테고리 변경 작업과 함께") 그때까지 지출 이력에 구 값이
# 섞여 오는데, 그대로 두면 카테고리별 집계에 9종 밖 버킷이 조용히 생긴다 — 에러가 아니라
# 리포트·브리핑·대시보드 숫자가 한 칸씩 어긋나는 형태라 눈에 잘 안 띈다.
#
# 대응이 애매했던 6건은 팀 결정(2026-08-06): 실습/프로젝트비·홍보/콘텐츠비는 행사_활동,
# 숙박/여행비는 장소_대관, 인쇄/문구비는 비품, 레저/액티비티비는 행사_활동, 선물/기념비는
# 기타. 9종에 자리가 없는 것만 기타로 접는다.
_LEGACY_CATEGORY_ALIASES: dict[str, str] = {
    # 우리가 쓰던 유형별 28종 (830f0f7 이전 카탈로그)
    "식대/회식비": "식비",
    "식비/간식비": "식비",
    "식비/다과비": "식비",
    "식비/모임비": "식비",
    "교통비": "교통",
    "교통/출장비": "교통",
    "온라인/구독비": "IT_인프라",
    "업무도구/소프트웨어비": "IT_인프라",
    "교육/강연비": "교육",
    "교육/도서비": "교육",
    "교재/자료비": "교육",
    "회의/운영비": "회의",
    "회의/워크숍비": "회의",
    "공간/대관비": "장소_대관",
    "장소/예약비": "장소_대관",
    "장소/시설비": "장소_대관",
    "숙박/여행비": "장소_대관",
    "행사/프로그램비": "행사_활동",
    "활동/프로그램비": "행사_활동",
    "대회/참가비": "행사_활동",
    "레저/액티비티비": "행사_활동",
    "실습/프로젝트비": "행사_활동",
    "홍보/콘텐츠비": "행사_활동",
    "물품/소모품비": "비품",
    "비품/소모품비": "비품",
    "장비/용품비": "비품",
    "인쇄/문구비": "비품",
    "선물/기념비": "기타",
    # 백엔드 구 ENUM 중 9종에서 빠지는 2종 (유지 5종은 이름이 같아 손댈 것이 없다)
    "행사": "행사_활동",
    "디자인": "기타",
}


def normalize_expense_category(value: Any) -> str:
    """지출 이력의 category를 전역 9종 중 하나로 접는다.

    이미 9종이면 그대로 두고, 구 값이면 위 대응표로 옮긴다. 둘 다 아니면 `기타`로
    접되 **경고 로그를 남긴다** — 조용히 접으면 계약이 어긋난 사실 자체가 묻힌다
    (지출 요청 category가 채워져 올 때와 같은 처리, T7).
    """
    if not isinstance(value, str) or not value.strip():
        return fallback_category()
    name = value.strip()
    if name in all_categories():
        return name
    mapped = _LEGACY_CATEGORY_ALIASES.get(name)
    if mapped is not None:
        return mapped
    logger.warning("지출 이력에 알 수 없는 카테고리 — 기타로 접는다: %r", name)
    return fallback_category()


async def get_expense_history(team_id: int, **filters: Any) -> list[dict[str, Any]]:
    """GET {BE}/internal/agent/teams/{id}/expenses — 중복 탐지·리포트 집계용.

    실모드 응답의 `category`는 9종으로 정규화해서 돌려준다(위 `normalize_expense_category`).
    이 경계에서 접어 두면 이력을 쓰는 네 곳(digest·budget_planner·dashboard·report)이
    각자 구 값을 신경 쓸 필요가 없다.
    """
    s = get_settings()
    if s.mock_backend:
        org = _fixture_org(team_id)
        history_name = org["expense_history"] if org is not None else "default"
        return _fixture_history(history_name)
    r = await _client().get(f"/internal/agent/teams/{team_id}/expenses", params=filters)
    r.raise_for_status()
    rows = r.json()
    for row in rows:
        if isinstance(row, dict):
            row["category"] = normalize_expense_category(row.get("category"))
    return rows


async def approve_expense(expense_id: int, idempotency_key: str, reason: str) -> dict[str, Any]:
    """POST {BE}/internal/agent/expenses/{id}/approve — 멱등성 키 필수 (REQ-023)."""
    s = get_settings()
    if s.mock_backend:
        logger.info("MOCK approve: expense=%s key=%s", expense_id, idempotency_key)
        return {"status": "AI_APPROVED", "mock": True}
    r = await _client().post(
        f"/internal/agent/expenses/{expense_id}/approve",
        headers={"Idempotency-Key": idempotency_key},
        json={"reason": reason},
    )
    if r.status_code == 409:  # 이미 처리됨 — 이중 차감 없음 (§8)
        return {"status": "duplicate", "idempotent": True}
    r.raise_for_status()
    return r.json()


async def reject_expense(expense_id: int, idempotency_key: str, reason: str) -> dict[str, Any]:
    """POST {BE}/internal/agent/expenses/{id}/reject."""
    s = get_settings()
    if s.mock_backend:
        logger.info("MOCK reject: expense=%s key=%s", expense_id, idempotency_key)
        return {"status": "AI_REJECTED", "mock": True}
    r = await _client().post(
        f"/internal/agent/expenses/{expense_id}/reject",
        headers={"Idempotency-Key": idempotency_key},
        json={"reason": reason},
    )
    if r.status_code == 409:
        return {"status": "duplicate", "idempotent": True}
    r.raise_for_status()
    return r.json()


async def get_expense_detail(organization_id: int, expense_id: int) -> dict[str, Any]:
    """지출 상세 조회 — pull 모델의 핵심 (bravo 설계서 TABLE 18).

    백엔드 심사 요청에는 jobId·expenseId·organizationId·심사목표·영수증 경로만 오고
    제목·금액·카테고리는 없다 — 이 함수로 되물어 가져온다. 정확한 엔드포인트 경로는
    풀스택 질의요청서 회신 대기 중 — 확정되면 아래 URL만 교체.

    목 데이터는 eval/fixtures/mock_backend.json에서 조회한다(T9). fixture는 이미
    9종 카탈로그 값만 담으므로 실모드처럼 접을 필요가 없다 — 접기·안 접기
    비대칭이 여기서 자연히 사라진다(tests/test_mock_fixture.py가 강제).

    실모드 응답의 `category`는 **값이 있을 때만** 9종으로 정규화한다
    (`normalize_expense_category`). load_context가 claim.category를 만드는 출처가
    이 함수라, 여기서 접지 않으면 백엔드 ENUM 마이그레이션 전까지 구 값이 심사
    그래프 안까지 들어온다.
    """
    s = get_settings()
    if s.mock_backend:
        expense = _fixture_expense(expense_id)
        if expense is not None:
            return {
                "title": expense["title"],
                "amount": expense["amount"],
                # fixture의 expenses에는 category가 없다 — 심사 전 지출은 카테고리가
                # 정해지지 않은 것이 백엔드 계약이고(BE-001 등록 시 null), 사람이 매긴
                # 정답은 골든셋의 expected_category로 옮겼다(2026-08-06). 아래 폴백과 같은 값.
                "category": expense.get("category", ""),
                "date": expense["date"],
                "description": expense["description"],
            }
        # fixture 미등재 ID의 기본 폴백
        return {
            "title": "모의 지출",
            "amount": 30_000,
            "category": "",
            "date": "2026-07-01",
            "description": "",
        }
    r = await _client().get(
        f"/internal/agent/organizations/{organization_id}/expenses/{expense_id}"
    )
    r.raise_for_status()
    detail = r.json()
    # 값이 있을 때만 접는다 — 빈 값은 '기타'가 아니라 **빈 값 그대로** 둬야 한다.
    # 이력과 갈리는 지점이다: 이력의 빈 값은 집계 버킷이 필요해 '기타'로 접지만,
    # 상세의 빈 값은 "분류기를 돌려라"는 신호다(BE-001 계약상 null이 정상 경로).
    # 여기서 '기타'로 채우면 claim.category가 비어 있지 않게 되어 AI 분류가 통째로
    # 무력화된다 — 모든 지출이 조용히 '기타'로 확정된다.
    if isinstance(detail, dict) and str(detail.get("category") or "").strip():
        detail["category"] = normalize_expense_category(detail["category"])
    return detail


async def get_team_settings(organization_id: int) -> dict[str, Any]:
    """team_settings 조회 — auto_approve 최상위 게이트용 (bravo 설계서 4절).

    실계약에서 auto_approve 기본값은 FALSE(꺼짐) — 꺼져 있으면 금액·판단과 무관하게
    무조건 ESCALATED. 값 자체는 백엔드 DB가 진실 원천이고 우리는 읽기만 한다.

    auto_approve_limit은 마법사 2단계 화면의 '관리자 승인 필수 금액' 한 칸이다 —
    "이 금액 이상은 무조건 관리자 검토". 2026-08-05 화면 개편으로 금액 칸이 2개에서
    1개로 줄면서 escalation_threshold 컬럼은 백엔드에서 삭제하기로 했고, 목 응답도
    실제 형태에 맞춰 그 키를 빼둔다 — 목이 실제와 다르면 목 모드에서 드러나지 않는
    버그가 생긴다(2026-07-31 θ 오염이 목의 0.8에 가려졌던 것과 같은 구조).
    키가 없을 때의 해석은 map_team_settings가 담당한다.

    목 데이터는 fixture 조회(T9) — 미등재 조직은 auto_approve=True/limit 50,000
    (골든셋·데모의 자동판정 흐름을 보존하기 위한 목 전용 기본값이며 실서비스
    기본값(False)과 다르다는 점에 주의). `escalation_threshold` 키는 fixture에도
    절대 넣지 않는다 — 위 문단의 실제 형태(키 부재)를 그대로 재현해야 한다.
    """
    s = get_settings()
    if s.mock_backend:
        org = _fixture_org(organization_id)
        if org is not None:
            return {
                "auto_approve": org["auto_approve"],
                "auto_approve_limit": org["auto_approve_limit"],
            }
        return {"auto_approve": True, "auto_approve_limit": 50_000}
    r = await _client().get(f"/internal/agent/organizations/{organization_id}/team-settings")
    r.raise_for_status()
    return r.json()


async def get_receipt_by_path(receipt_path: str) -> bytes | None:
    """영수증 이미지 조회 — 백엔드가 준 '조회 경로'로 Spring에 재요청 (동적 참조).

    signed URL 직접 fetch 방식이 아니라 Agent 전용 토큰으로 백엔드에 되묻는 방식
    (bravo 설계서 4절 'Agent 전용 토큰'). 목 모드에서는 None을 반환하고
    intake_receipt가 청구 일치 영수증을 생성한다(mock://receipt?... 오버라이드는
    intake 쪽 규약 그대로).

    file:// 스킴은 로컬 파일을 그대로 읽어 반환한다 — 골든셋 실키 검증용
    (eval/golden/receipts/, scripts/generate_golden_receipts.py) 실제 이미지 fixture
    경로. 외부 호스팅 없이 Vision이 실제 픽셀 데이터를 읽도록 하기 위함이며,
    mock_backend 여부와 무관하게 적용된다(로컬 파일은 항상 실재하므로). 상대경로는
    저장소 루트 기준(팀원 간 절대경로 불일치 방지) — 절대경로도 그대로 허용.
    """
    if receipt_path.startswith("file://"):
        rel = receipt_path[len("file://") :]
        path = Path(rel)
        if not path.is_absolute():
            path = _PROJECT_ROOT / rel
        return path.read_bytes()
    s = get_settings()
    if s.mock_backend:
        return None
    r = await _client().get(receipt_path)
    r.raise_for_status()
    return r.content


async def get_team_profile(team_id: int) -> dict[str, Any]:
    """팀 프로필(모임 유형 등) 조회 — 유형별 카테고리 카탈로그 선택에 사용.

    목 데이터는 fixture 조회(T9). 실제 엔드포인트 경로는 풀스택 팀과 미확정.
    """
    s = get_settings()
    if s.mock_backend:
        org = _fixture_org(team_id)
        if org is not None:
            return {"team_type": org["team_type"]}
        return {"team_type": "동아리/학생회"}  # 기본값
    r = await _client().get(f"/internal/agent/teams/{team_id}/profile")
    r.raise_for_status()
    profile = r.json()
    # 백엔드 ENUM은 언더바 표기(2026-08-06 확정) — 템플릿·카탈로그 키는 슬래시라
    # 경계에서 접는다. 접지 않으면 유형별 카탈로그가 조용히 기본 유형으로 fallback.
    if "team_type" in profile:
        profile["team_type"] = normalize_team_type(profile["team_type"])
    return profile


async def get_team_members(team_id: int) -> list[dict[str, Any]]:
    """팀 멤버 명단(실명·역할) — PIIMasker 치환용 (§4.3).

    엔드포인트 경로는 풀스택 팀과 미확정. 목: 고정 명단.
    """
    s = get_settings()
    if s.mock_backend:
        return [
            {"name": "김철수", "role": "총무"},
            {"name": "이영희", "role": "회원"},
            {"name": "박민준", "role": "회원"},
        ]
    r = await _client().get(f"/internal/agent/teams/{team_id}/members")
    r.raise_for_status()
    return r.json()


@dataclass(frozen=True)
class PolicyDocumentSource:
    """회칙 원본 — **텍스트이거나 파일이거나** 둘 중 하나다 (T2, 회의 4번).

    관리자는 마법사 3단계에서 회칙을 ① 직접 입력하거나 ② PDF·docx로 올릴 수 있다.
    ①이면 `text`, ②면 `file_bytes`가 채워진다. 어느 쪽인지는 백엔드만 아는 사실이라
    같은 엔드포인트가 형식만 달리 답하게 두고, 분기를 이 경계에서 흡수한다.
    """

    text: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None


async def get_policy_document(team_id: int, doc_type: str, version: int) -> PolicyDocumentSource:
    """회칙·카테고리 원본 조회 — 인덱싱 파이프라인 1단계 (REQ-041, §4.4-a).

    /v1/context/refresh 이벤트에는 원문이 없고 team_id·변경유형·버전만 오므로,
    실제 내용은 이 함수로 백엔드에 되물어야 한다.

    반환은 텍스트일 수도 파일 바이트일 수도 있다(`PolicyDocumentSource`). 파일이면
    호출부가 `document_parser.extract_text`로 텍스트를 뽑는다 — 파싱을 우리가 맡는
    이유는 백엔드가 텍스트만 주면 파싱 실패가 "회칙 등록했는데 심사엔 반영 안 됨"이라는
    조용한 실패로 나타나서다(회신요청 6-3).
    """
    s = get_settings()
    if s.mock_backend:
        if doc_type == "rule":
            # 제5조 이후는 실모드 골든셋 1차 실측(2026-07-20) 결과 반영 — 카테고리
            # 미커버로 rule_ambiguous escalate가 지배적 실패 원인이라 유형 공통
            # 카테고리 조항을 확장 (골든 시나리오 카테고리 커버). 목 골든셋은
            # 회칙 미인덱싱 팀이라 영향 없음(no_rules 경로).
            return PolicyDocumentSource(
                text=(
                    "제1조 (목적) 이 회칙은 모임 활동비 집행 기준을 정한다.\n\n"
                    "제2조 (회식비 한도) 1인당 회식비는 3만원을 초과할 수 없다.\n\n"
                    "제3조 (금지 항목) 개인 용도 물품 구입은 지출로 인정하지 않는다.\n\n"
                    "제4조 (도서 구입) 스터디 관련 도서는 인당 연 5만원 한도로 인정한다.\n\n"
                    "제5조 (비품·물품) 모임 공동 사용 목적의 비품·물품·장비 구입은 인정한다.\n\n"
                    "제6조 (장소 대관) 모임 활동을 위한 장소 대관료는 인정한다.\n\n"
                    "제7조 (홍보·행사) 모임 홍보물 제작비와 행사 운영 경비는 인정한다.\n\n"
                    "제8조 (다과·간식) 모임 진행 중의 다과·간식 구입은 인정한다.\n\n"
                    "제9조 (교통·이동) 모임 활동 목적의 교통비는 인정한다.\n\n"
                    "제10조 (교육·수강) 모임 주제와 관련된 교육·강연·수강료는 인정한다.\n\n"
                    "제11조 (숙박·여행) 모임 공식 일정의 숙박·여행 경비는 인정한다.\n\n"
                    f"(mock rule text, team={team_id}, version={version})"
                )
            )
        return PolicyDocumentSource(
            text=f"(mock {doc_type} text, team={team_id}, version={version})"
        )
    r = await _client().get(
        f"/internal/agent/teams/{team_id}/policy-document",
        params={"doc_type": doc_type, "version": version},
    )
    r.raise_for_status()
    # 응답이 JSON이면 텍스트 회칙, 아니면 파일 원본이다 (BE-005 확장 — T2).
    # **이 분기 덕에 LLM-006 계약도 워커도 안 바뀐다.** 회칙이 파일로 등록된 팀인지
    # 아닌지는 백엔드만 아는 사실이라, 굳이 refresh 이벤트에 필드를 늘려 프론트·백엔드
    # 양쪽 계약을 흔들 필요가 없다. 같은 엔드포인트가 형식만 달리 답하면 된다.
    if "json" in r.headers.get("content-type", ""):
        return PolicyDocumentSource(text=r.json()["text"])
    filename = None
    disposition = r.headers.get("content-disposition", "")
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"; ') or None
    return PolicyDocumentSource(file_bytes=r.content, filename=filename)


CALLBACK_MAX_ATTEMPTS = 3
CALLBACK_BACKOFF_BASE_SEC = 1.0  # 1s → 2s → (4s는 없음: 3회째 실패 시 포기)


async def _post_callback(payload: dict[str, Any]) -> None:
    """콜백 1회 전송 — 실패는 예외로 전파 (재시도 루프가 잡는다). 테스트 대체 지점."""
    r = await _client().post("/agent-callback", json=payload, timeout=10)
    r.raise_for_status()


async def send_callback(payload: dict[str, Any]) -> bool:
    """POST {BE}/agent-callback — 지수 백오프 3회 재시도 (A-5).

    최종 실패해도 예외 없이 False — 백엔드의 폴링 fallback이 설계상 최종 안전망
    (§7.1)이므로 콜백 실패가 심사 잡을 죽이면 안 된다. 반환은 지금 bool이지만,
    늦은 콜백 규칙(질의요청서 C6②) 확정 시 백엔드 응답 status('저장만 됨' 등)를
    실어 나를 수 있도록 이 함수에서만 확장하면 되는 구조를 유지할 것.
    """
    s = get_settings()
    if s.mock_backend:
        logger.info(
            "MOCK callback: verdict=%s expense=%s", payload.get("verdict"), payload.get("expenseId")
        )
        return True
    for attempt in range(1, CALLBACK_MAX_ATTEMPTS + 1):
        try:
            await _post_callback(payload)
            return True
        except httpx.HTTPError:
            if attempt == CALLBACK_MAX_ATTEMPTS:
                logger.error(
                    "callback failed after %d attempts (job=%s) — 백엔드 폴링 fallback에 위임",
                    CALLBACK_MAX_ATTEMPTS,
                    payload.get("jobId"),
                    exc_info=True,
                )
                return False
            delay = CALLBACK_BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            logger.warning(
                "callback attempt %d/%d failed (job=%s) — %.0fs 후 재시도",
                attempt,
                CALLBACK_MAX_ATTEMPTS,
                payload.get("jobId"),
                delay,
            )
            await asyncio.sleep(delay)
    return False  # 도달 불가 — 타입 체커용
