"""OpenAPI 스펙을 docs/openapi.json으로 덤프 (Sprint 2 'OpenAPI 커밋').

실행:  uv run python scripts/dump_openapi.py            # 덤프
       uv run python scripts/dump_openapi.py --check    # drift 검사 (CI용, exit 1)

FastAPI가 런타임에 생성하는 스펙을 파일로 고정해 풀스택 팀이 리포에서 우리 API
계약(엔드포인트·스키마)을 코드 실행 없이 확인할 수 있게 한다. --check는 커밋된
파일이 현재 코드와 일치하는지 검사 — API를 바꾸고 스펙을 안 갱신하면 CI가 잡는다.

앱 import만으로 생성되며 DB·lifespan은 불필요하다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp949 콘솔 대응

from app.main import app  # noqa: E402

OUT = ROOT / "docs" / "openapi.json"


def current_spec() -> str:
    # sort_keys — 딕셔너리 순서 흔들림으로 인한 헛 diff 방지 (drift 검사 안정화)
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    spec = current_spec()
    if "--check" in sys.argv:
        if not OUT.exists():
            print(f"{OUT.relative_to(ROOT)} 없음 — dump_openapi.py로 생성·커밋하세요")
            return 1
        if OUT.read_text(encoding="utf-8") != spec:
            print(f"{OUT.relative_to(ROOT)}가 현재 API와 불일치 — "
                  "`uv run python scripts/dump_openapi.py`로 갱신·커밋하세요")
            return 1
        print("OpenAPI 스펙 최신 — drift 없음")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(spec, encoding="utf-8")
    paths = len(app.openapi()["paths"])
    print(f"덤프 완료: {OUT.relative_to(ROOT)} ({paths}개 경로)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
