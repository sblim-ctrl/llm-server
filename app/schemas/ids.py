"""백엔드 BIGINT 기본키를 주고받는 API 공통 타입.

**본문(JSON)용과 쿼리 파라미터용이 나뉘어 있다 — 섞어 쓰면 엔드포인트가 죽는다.**

`BigIntId`의 `strict=True`는 계약이다: 백엔드가 `"expenseId": "4821"`처럼 문자열로
보내면 422로 거절해야 한다(`docs/풀스택_연동_계약.md` §2-1의 타입 표). JSON 본문은
진짜 정수로 도착하므로 strict가 성립한다.

그런데 **쿼리 파라미터는 HTTP상 언제나 문자열**이다. `?team_id=17`은 pydantic에
`'17'`(str)로 도착하고 strict 모드는 이를 절대 통과시키지 않는다 — 즉 strict 타입을
쿼리에 쓰면 **어떤 값을 넣어도 422**가 되어 그 엔드포인트가 통째로 죽는다.
`WithJsonSchema` 때문에 `openapi.json`에는 멀쩡한 `integer/int64`로 나와서
스펙만 봐서는 보이지 않는다 (2026-08-07 실호출로 확인).
"""

from typing import Annotated

from pydantic import WithJsonSchema, conint

BIGINT_MAX = 9_223_372_036_854_775_807

_BIGINT_JSON_SCHEMA = WithJsonSchema(
    {
        "type": "integer",
        "format": "int64",
        "description": "양의 백엔드 BIGINT 기본키",
    }
)

#: 요청 **본문(JSON)**용 — 문자열 ID를 422로 거절한다(계약).
BigIntId = Annotated[conint(strict=True, gt=0, le=BIGINT_MAX), _BIGINT_JSON_SCHEMA]

#: **쿼리 파라미터**용 — 문자열로 도착하므로 strict를 쓰지 않는다.
#: 범위 검사(gt=0·BIGINT 상한)는 그대로라 `?team_id=0`·`?team_id=abc`는 여전히 422다.
BigIntQuery = Annotated[conint(gt=0, le=BIGINT_MAX), _BIGINT_JSON_SCHEMA]
