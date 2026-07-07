"""로컬 개발용 API 런처 — Windows 전용 이벤트 루프 보정.

psycopg 비동기는 Windows 기본 ProactorEventLoop와 호환되지 않는데,
uvicorn CLI는 Windows에서 Proactor를 강제하므로 서버를 프로그래밍 방식으로
SelectorEventLoop 위에서 직접 실행한다.
Docker(Linux)에서는 이 파일 불필요 — compose는 uvicorn을 직접 실행.

실행: uv run python -m app.run_api
"""
import asyncio
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
