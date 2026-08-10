"""배포 전 점검 — 자동으로 확인 가능한 것만 모아 한 번에 돌린다.

    uv run python scripts/predeploy_check.py

단위 테스트가 이미 촘촘한 부분(인증 미들웨어·`/readyz` 설정 검사 로직)은 여기서 다시
검증하지 않는다. 여기서 보는 것은 **테스트가 못 잡는 배포 형상**이다 — 문서와 코드가
어긋났는지, 운영 설정으로 띄웠을 때 실제로 거절되는지 같은 것들.

배포 당일에도 그대로 돌려서 전부 OK인지 보면 된다. 실패는 exit 1.

여기서 확인하지 **않는** 것(사람이 해야 함):
- 백엔드 내부 조회 API 8종 준비 여부 — 없으면 심사가 시작되지 않는다
- GCP 환경변수 실제 주입 여부 — 배포 후 `/readyz`가 200인지로 확인
- 브랜치 통합 완료 여부
"""

import io
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f" [{'O' if ok else 'X'}] {name}" + (f"  — {detail}" if detail else ""))


# ── 1. 문서와 코드가 어긋나지 않았는가 ────────────────────────────────────
r = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "dump_openapi.py"), "--check"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
check(
    "OpenAPI 스펙이 코드와 일치",
    r.returncode == 0,
    "" if r.returncode == 0 else "dump_openapi.py로 갱신·커밋 필요",
)

# ── 2. 카탈로그·프롬프트 정합성 ───────────────────────────────────────────
from app.llm.prompts import load_prompt  # noqa: E402
from app.tools.category_catalog import all_categories, fallback_category  # noqa: E402

cats = all_categories()
check("카테고리 9종 고정", len(cats) == 9, f"{len(cats)}종: {', '.join(cats)}")
check("fallback이 목록 안에 있음", fallback_category() in cats, fallback_category())

spec = load_prompt("classifier")
header = f"카테고리 후보(이 중에서만 선택): {', '.join(cats)}"
bad = [
    i for i, s in enumerate(spec.few_shot, 1) if s["input"].rstrip("\n").split("\n")[0] != header
]
check(
    f"분류기 few_shot이 카탈로그와 일치 ({spec.version})",
    not bad,
    "" if not bad else f"어긋난 예시 {bad}",
)

# 15개 전 에이전트의 활성 버전 few_shot에 카탈로그 밖 카테고리 라벨이 없는가.
# tests/test_prompt_fewshot_contract.py::test_all_active_fewshot_category_labels_are_in_catalog와
# 같은 검사를 배포 전에도 돈다. 그 테스트의 _CATEGORY_LABEL_DEBT과 동일한 목록을
# 여기서도 그대로 봐준다 — 지금은 부채가 없다(default_policy·query_rewriter는
# v2로 이미 정합됨). 두 목록은 반드시 같이 업데이트할 것.
import json  # noqa: E402

from app.llm.prompts import DEFAULT_VERSIONS  # noqa: E402

_CATEGORY_LABEL_DEBT: set[tuple[str, str]] = set()


def _collect_category_values(node, out: list) -> None:
    """중첩 dict/list를 재귀 순회하며 키 이름이 정확히 'category'인 값을 out에 모은다."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "category":
                out.append(value)
            _collect_category_values(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_category_values(item, out)


bad_labels: list[str] = []
debt_labels: list[str] = []
for agent_dir in sorted((ROOT / "prompts").iterdir()):
    agent = agent_dir.name
    version = DEFAULT_VERSIONS.get(agent, "v1")
    agent_spec = load_prompt(agent, version)
    for i, ex in enumerate(agent_spec.few_shot, 1):
        for field in ("input", "output"):
            raw = (ex.get(field) or "").strip()
            try:
                parsed, _ = json.JSONDecoder().raw_decode(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            values: list = []
            _collect_category_values(parsed, values)
            for label in values:
                if label not in cats:
                    entry = f"{agent}/{version} 예시{i} {field}: {label!r}"
                    if (agent, version) in _CATEGORY_LABEL_DEBT:
                        debt_labels.append(entry)
                    else:
                        bad_labels.append(entry)
check(
    "전 에이전트 활성 few_shot이 카탈로그와 일치 (부채 제외)",
    not bad_labels,
    "" if not bad_labels else f"어긋난 라벨 {bad_labels}",
)
if debt_labels:
    print(f"     (부채로 등록된 기존 위반 {len(debt_labels)}건, 배포 차단 안 함): {debt_labels}")

# ── 3. 운영 설정 가드가 실제로 거절하는가 ─────────────────────────────────
# check_config_ready는 단위 테스트가 있지만, 여기서는 '실모드 + 기본값' 조합이
# 정말 not_ready로 떨어지는지 한 번 더 본다 — 배포 사고가 났던 지점이라서다.
from app.api.health import (  # noqa: E402
    DEFAULT_BACKEND_SERVICE_TOKEN,
    DEFAULT_SERVICE_TOKEN,
    check_config_ready,
)
from app.config import get_settings  # noqa: E402

s = get_settings()
if s.mock_llm:
    check("운영 설정 가드", True, "목 모드 — 배포 전 MOCK_LLM=false로 재확인할 것")
else:
    ok, status = check_config_ready()
    check("운영 설정 가드(실모드)", ok, status)
    check(
        "서비스 토큰이 기본값이 아님",
        s.service_token != DEFAULT_SERVICE_TOKEN,
        "기본 토큰이면 인증이 없는 것과 같다",
    )
    check(
        "백엔드 발신 토큰이 기본값이 아님",
        s.backend_service_token != DEFAULT_BACKEND_SERVICE_TOKEN,
        "기본 토큰이면 백엔드가 우리를 인증할 수 없다",
    )
    check("실모드에서 목 백엔드를 쓰지 않음", not s.mock_backend)

# ── 4. 배포 이미지에 필요한 파일이 들어가는가 ─────────────────────────────
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
copied = [
    ln.split()[1]
    for ln in dockerfile.splitlines()
    if ln.startswith("COPY ") and not ln.startswith("COPY --from")
]
needed = ["app", "prompts", "templates", "eval"]
missing = [n for n in needed if n not in copied]
check("이미지에 app·prompts·templates 포함", not missing, "" if not missing else f"누락: {missing}")

# ── 5. 테스트 전체 ────────────────────────────────────────────────────────
# 테스트는 목 모드 계약이다(규율 4) — 실모드로 돌리면 고정 응답을 전제한 것들이 깨진다.
# 이 스크립트를 MOCK_LLM=false로 돌리는 경우가 있으므로 여기서만 목 모드를 강제한다.
env = {**os.environ, "MOCK_LLM": "true"}
r = subprocess.run(
    [sys.executable, "-m", "pytest", "-q"],
    cwd=ROOT,
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
tail = (r.stdout or "").strip().splitlines()
check("pytest 전체 통과 (목 모드)", r.returncode == 0, tail[-1] if tail else "")

# ── 결과 ──────────────────────────────────────────────────────────────────
failed = [n for n, ok, _ in results if not ok]
print()
if failed:
    print(f"실패 {len(failed)}건: {failed}")
    sys.exit(1)
print(f"자동 점검 {len(results)}건 전부 통과")
print()
print("남은 것은 사람이 확인해야 한다:")
print("  - 백엔드 내부 조회 API 8종 (없으면 심사가 시작되지 않음)")
print("  - 브랜치 통합 완료 여부")
print("  - 배포 후 GET /readyz 가 200인지 (환경변수 누락은 여기서 잡힌다)")
