"""백엔드 BIGINT 기본키를 주고받는 API 공통 타입."""

from typing import Annotated

from pydantic import WithJsonSchema, conint

BIGINT_MAX = 9_223_372_036_854_775_807

BigIntId = Annotated[
    conint(strict=True, gt=0, le=BIGINT_MAX),
    WithJsonSchema(
        {
            "type": "integer",
            "format": "int64",
            "description": "양의 백엔드 BIGINT 기본키",
        }
    ),
]
