# BudgetOps LLM Server

지출 자동 심사 LLM 에이전트 서버 (FastAPI + LangGraph + Postgres/pgvector). Python 3.12, uv 관리.

## 응답 언어

- 이 저장소에서는 한국어로 응답한다. 코드·명령어·파일 경로·에러 메시지는 원문 유지.

## 명령어

- 의존성 설치: `uv sync`
- API 서버(로컬): `uv run python -m app.run_api` — Windows는 반드시 이 방식(이벤트 루프 보정)
- 워커: `uv run python -m app.worker`
- DB만 기동: `docker compose up -d llm-postgres`
- 테스트: `uv run pytest`
- 스모크(무DB E2E): `uv run python scripts/smoke_review.py`
- 골든셋 평가: `uv run python -m eval.run_eval`
- 포맷/린트: `uv run ruff format .` / `uv run ruff check .`
- 머지 게이트: `uv run pytest` 전체 통과 + `run_eval` 오승인 0건·정확도 ≥90%

## 구조

- `app/main.py` FastAPI 조립(LLM 호출 없음) / `app/worker.py` LangGraph 실행 워커 / `app/config.py` 설정(.env)
- `app/graphs/review/` 심사 그래프(노드 1파일 1책임) · `indexing/` 인덱싱 · `writers/` 문서 생성
- `app/api/` 라우터, `app/tools/` 도구, `app/llm/` 모델 라우팅(models.yaml), `app/middleware/`, `app/schemas/`, `app/db/`
- `prompts/{agent}/{version}.yaml` 프롬프트 · `templates/` 카탈로그 · `tests/` · `eval/`
- 모의 모드: `MOCK_LLM` / `MOCK_BACKEND` (기본 켜짐, 실연동은 .env만 변경 — README 참조)

## 참고 문서 (팀 확정 결정사항의 원천)

- 아키텍처·ADR: `docs/internal/설계서_v1.2_개정안_협의중.md` - 아직 협의가 완료되지 않은 사항은 고려하지 말 것.
- 업무분장·파일 소유권·공유 계약: `docs/_private/LLM팀_작업리스트_MVP_2026-08-05.md` — 파일 소유 경계는 §7이 정본. 구판 `docs/internal/업무분장_스프린트1_작업명세_v2.md`는 §7이 다루지 않는 파일의 보조 근거로만 참고.
