"""백엔드 내부 조회 API 8종 — 계약 검증 스크립트 (받는 즉시 실행용).

백엔드가 내부 Agent API를 열어주는 순간, 우리 심사 파이프라인이 기대하는
계약(경로·필드명·타입)과 맞는지 몇 분 안에 확인하기 위한 도구다.

- 전부 읽기 전용 GET만 호출한다 — approve/reject/콜백은 부르지 않는다.
- .env는 건드리지 않는다. MOCK_BACKEND와 무관하게 --base-url을 직접 친다.
- 필드명은 바이트 단위로 검사한다. 백엔드 프론트 API가 camelCase라서
  내부 API도 camelCase로 나올 위험이 있는데, 그 경우 load_context가
  auto_approve를 못 찾아 조용히 전건 에스컬레이션이 된다 (백엔드_대기항목_정리.md
  §1-b와 같은 부류의 실연동 지뢰). camelCase로 온 필드는 힌트로 지적한다.

사용:
  uv run python scripts/verify_backend_contract.py \
      --base-url http://<backend-host>:8080 --token <SERVICE_TOKEN> \
      --team-id 1 --expense-id 1
  # 영수증 경로까지 확인하려면: --receipt-path "/internal/agent/receipts/..."

종료 코드: 심사 차단급(CRITICAL) 실패가 있으면 1, 아니면 0.
"""

import argparse
import sys
from typing import Any

import httpx

# Windows 콘솔 기본 cp949가 '—' 등을 못 찍는다 — 출력만 UTF-8로 강제
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (레벨, 항목, 통과여부, 비고) — 레벨 CRITICAL은 없으면 심사가 시작조차 안 되는 것
_results: list[tuple[str, str, bool, str]] = []


def record(level: str, name: str, ok: bool, note: str = "") -> None:
    _results.append((level, name, ok, note))
    mark = "O" if ok else "X"
    line = f" [{mark}] ({level}) {name}"
    if note:
        line += f"  — {note}"
    print(line)


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(p.title() for p in rest)


def check_keys(
    data: dict[str, Any], keys: list[str], optional: list[str] | None = None
) -> tuple[bool, str]:
    """필수 키 존재 검사. 값이 null인 것은 허용(존재 여부만) — null 처리는 코드 몫."""
    notes: list[str] = []
    ok = True
    for k in keys:
        if k not in data:
            ok = False
            if _camel(k) in data:
                notes.append(f"'{k}'가 camelCase('{_camel(k)}')로 옴 — 명세는 snake_case")
            else:
                notes.append(f"'{k}' 없음")
    for k in optional or []:
        if k not in data and _camel(k) not in data:
            notes.append(f"(선택) '{k}' 없음")
    return ok, "; ".join(notes)


def get_json(client: httpx.Client, path: str, **kw: Any) -> Any:
    r = client.get(path, **kw)
    r.raise_for_status()
    return r.json()


def run_checks(args: argparse.Namespace, client: httpx.Client) -> None:
    tid, eid = args.team_id, args.expense_id

    # 1. 지출 상세 — 없으면 심사 불가 (load_context가 예외 → fail-safe ESCALATED)
    try:
        d = get_json(client, f"/internal/agent/organizations/{tid}/expenses/{eid}")
        ok, note = check_keys(d, ["title", "amount"], ["category", "date", "description"])
        if ok and not isinstance(d.get("amount"), int):
            ok, note = False, f"amount가 int가 아님: {type(d.get('amount')).__name__}"
        record("CRITICAL", "지출 상세 GET /organizations/{org}/expenses/{id}", ok, note)
    except Exception as e:  # noqa: BLE001 — 계약 검증 도구는 전 오류를 보고로 수렴
        record("CRITICAL", "지출 상세 GET /organizations/{org}/expenses/{id}", False, repr(e))

    # 2. team_settings — 없으면 auto_approve=False fail-safe → 전건 에스컬레이션
    #
    # escalation_threshold는 PR #12(마법사 2단계 개편)로 백엔드가 삭제하기로 한
    # 컬럼이라 필수에서 뺐다 — policy_params.py가 이미 이 키 없이도
    # auto_approve_limit과 같은 값으로 읽는다. 필수로 두면 컬럼 삭제 후 배포
    # 당일 CRITICAL 오탐이 난다.
    try:
        d = get_json(client, f"/internal/agent/organizations/{tid}/team-settings")
        ok, note = check_keys(d, ["auto_approve", "auto_approve_limit"], ["escalation_threshold"])
        record("CRITICAL", "설정 GET /organizations/{org}/team-settings", ok, note)
    except Exception as e:  # noqa: BLE001
        record("CRITICAL", "설정 GET /organizations/{org}/team-settings", False, repr(e))

    # 3. 예산 — 실패 시 budget_auditor error 소견 → 에스컬레이션 (심사는 되나 자동율 0)
    try:
        d = get_json(client, f"/internal/agent/teams/{tid}/budget")
        total = d.get("total_budget", d.get("totalBudget"))
        spent = d.get("spent", d.get("used_budget", d.get("usedBudget")))
        ok = total is not None and spent is not None
        note = "" if ok else f"키 확인 필요 — 받은 키: {sorted(d)}"
        record("DEGRADED", "예산 GET /teams/{id}/budget", ok, note)
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "예산 GET /teams/{id}/budget", False, repr(e))

    # 4. 지출 이력 — 중복 탐지·리포트 집계용
    try:
        d = get_json(client, f"/internal/agent/teams/{tid}/expenses")
        if not isinstance(d, list):
            record("DEGRADED", "이력 GET /teams/{id}/expenses", False, "list가 아님")
        elif d:
            ok, note = check_keys(d[0], ["title", "amount", "date", "status"], ["category"])
            record("DEGRADED", "이력 GET /teams/{id}/expenses", ok, note)
        else:
            record("DEGRADED", "이력 GET /teams/{id}/expenses", True, "빈 목록 (형태 검사 생략)")
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "이력 GET /teams/{id}/expenses", False, repr(e))

    # 5. 팀 프로필 — 카테고리 카탈로그 선택용 (실패 시 기본 유형 fail-open)
    try:
        d = get_json(client, f"/internal/agent/teams/{tid}/profile")
        ok, note = check_keys(d, ["team_type"])
        record("DEGRADED", "프로필 GET /teams/{id}/profile", ok, note)
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "프로필 GET /teams/{id}/profile", False, repr(e))

    # 6. 멤버 명단 — PII 마스킹용 (실패 시 마스킹 없이 진행)
    try:
        d = get_json(client, f"/internal/agent/teams/{tid}/members")
        if not isinstance(d, list):
            record("DEGRADED", "멤버 GET /teams/{id}/members", False, "list가 아님")
        elif d:
            ok, note = check_keys(d[0], ["name", "role"])
            record("DEGRADED", "멤버 GET /teams/{id}/members", ok, note)
        else:
            record("DEGRADED", "멤버 GET /teams/{id}/members", True, "빈 목록 (형태 검사 생략)")
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "멤버 GET /teams/{id}/members", False, repr(e))

    # 7. 회칙 원문 — 인덱싱 파이프라인용. 회칙 없는 팀이면 404가 정상일 수 있다
    try:
        r = client.get(
            f"/internal/agent/teams/{tid}/policy-document",
            params={"doc_type": "rule"},
        )
        if r.status_code == 404:
            record(
                "DEGRADED",
                "회칙 GET /teams/{id}/policy-document",
                True,
                "404 — 회칙 없는 팀이면 정상",
            )
        else:
            r.raise_for_status()
            ok, note = check_keys(r.json(), ["text"])
            record("DEGRADED", "회칙 GET /teams/{id}/policy-document", ok, note)
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "회칙 GET /teams/{id}/policy-document", False, repr(e))

    # 8. 영수증 조회 — 경로를 받아야만 검사 가능
    if args.receipt_path:
        try:
            r = client.get(args.receipt_path)
            r.raise_for_status()
            ok = len(r.content) > 0
            record(
                "DEGRADED",
                f"영수증 GET {args.receipt_path}",
                ok,
                f"{len(r.content)} bytes, {r.headers.get('content-type', '?')}",
            )
        except Exception as e:  # noqa: BLE001
            record("DEGRADED", f"영수증 GET {args.receipt_path}", False, repr(e))
    else:
        record("DEGRADED", "영수증 조회", True, "--receipt-path 미지정 — 검사 생략")

    # 보너스: 인증이 실제로 걸려 있는지 — 토큰 없이 치면 401/403이어야 한다
    try:
        r = httpx.get(
            f"{args.base_url}/internal/agent/organizations/{tid}/team-settings", timeout=10
        )
        ok = r.status_code in (401, 403)
        note = "" if ok else f"무토큰 요청이 {r.status_code} — 내부 API 인증 미적용 의심"
        record("DEGRADED", "인증 강제 여부 (무토큰 → 401/403)", ok, note)
    except Exception as e:  # noqa: BLE001
        record("DEGRADED", "인증 강제 여부 (무토큰 → 401/403)", False, repr(e))


def main() -> int:
    ap = argparse.ArgumentParser(description="백엔드 내부 조회 API 8종 계약 검증")
    ap.add_argument("--base-url", help="백엔드 base URL (기본: 설정의 backend_base_url)")
    ap.add_argument("--token", help="SERVICE_TOKEN (기본: 설정값)")
    ap.add_argument("--team-id", type=int, required=True, help="백엔드에 실재하는 팀(모임) ID")
    ap.add_argument("--expense-id", type=int, required=True, help="그 팀에 실재하는 지출 ID")
    ap.add_argument("--receipt-path", help="영수증 조회 경로 (백엔드가 주는 receipt_path 형식)")
    args = ap.parse_args()

    if not args.base_url or not args.token:
        from app.config import get_settings  # 지연 import — CLI만 쓸 때 앱 의존 없이 -h 가능

        s = get_settings()
        args.base_url = args.base_url or s.backend_base_url
        args.token = args.token or s.service_token

    print(f"대상: {args.base_url} (team={args.team_id}, expense={args.expense_id})\n")
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=15,
    ) as client:
        run_checks(args, client)

    critical_fail = [r for r in _results if r[0] == "CRITICAL" and not r[2]]
    degraded_fail = [r for r in _results if r[0] == "DEGRADED" and not r[2]]
    print()
    if critical_fail:
        print(f"CRITICAL 실패 {len(critical_fail)}건 — 이 상태로 배포하면 심사가 시작되지 않는다.")
    if degraded_fail:
        print(f"DEGRADED 실패 {len(degraded_fail)}건 — 심사는 되지만 자동 처리율·품질이 떨어진다.")
    if not critical_fail and not degraded_fail:
        print(
            "전부 통과 — 계약 일치. 다음 단계: 실지출 1건 E2E (POST /v1/analyze → 콜백 수신 확인)."
        )
    return 1 if critical_fail else 0


if __name__ == "__main__":
    sys.exit(main())
