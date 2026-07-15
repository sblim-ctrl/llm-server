"""PostToolUse(Write|Edit) 훅 — 편집된 .py 파일에 ruff format 자동 적용.

stdin으로 훅 입력 JSON을 받는다. 실패해도 작업을 막지 않는다(항상 exit 0).
macOS/Windows 공통 동작을 위해 셸 문법 없이 Python으로 처리.
"""

import json
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    tool_input = data.get("tool_input") or {}
    tool_response = data.get("tool_response") or {}
    path = tool_input.get("file_path") or tool_response.get("filePath")
    if not path or not str(path).endswith(".py"):
        return
    subprocess.run(
        ["uv", "run", "ruff", "format", str(path)],
        capture_output=True,
        timeout=20,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
