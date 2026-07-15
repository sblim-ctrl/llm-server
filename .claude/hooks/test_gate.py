"""Stop 훅 — 작업 트리에 .py 변경이 있으면 pytest를 실행하는 테스트 게이트.

실패 시 {"decision": "block", "reason": ...}을 출력해 Claude가 수정을 이어가게 한다.
stop_hook_active가 켜져 있으면 즉시 통과한다(무한 재시도 루프 방지 — 필수).
"""

import json
import subprocess
import sys


def has_python_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        # 포맷: "XY <path>" 또는 이름 변경 시 "XY <old> -> <new>"
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path.endswith(".py"):
            return True
    return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if data.get("stop_hook_active"):
        return
    if not has_python_changes():
        return
    result = subprocess.run(
        ["uv", "run", "pytest", "-q"],
        capture_output=True,
        text=True,
        timeout=150,
    )
    if result.returncode == 0:
        return
    tail = "\n".join((result.stdout + "\n" + result.stderr).strip().splitlines()[-30:])
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": "pytest 게이트 실패 — 아래 실패를 수정하세요.\n" + tail,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
