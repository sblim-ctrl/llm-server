"""initial schema

app/db/schema.sql이 SSOT — 테이블 정의를 여기에 따로 다시 쓰지 않고 schema.sql
전체를 그대로 실행한다. schema.sql은 CREATE TABLE/INDEX IF NOT EXISTS로 완전히
idempotent하므로, 이미 apply_schema()로 부트스트랩된 DB에 대해서도 안전하게
재적용된다.

Revision ID: 0001
Revises:
Create Date: 2026-07-22 14:27:06.266033

"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA_SQL = Path(__file__).parents[2] / "app" / "db" / "schema.sql"


def upgrade() -> None:
    """schema.sql을 그대로 실행 (SSOT 유지)."""
    op.execute(_SCHEMA_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    """초기 스키마 되돌리기 (신규 4개 테이블 DROP) — 되돌린 뒤 재적용 시
    alembic_version이 초기화되어야 함."""
    op.execute("DROP TABLE IF EXISTS proposals")
    op.execute("DROP TABLE IF EXISTS precedents")
    op.execute("DROP TABLE IF EXISTS context_chunks")
    op.execute("DROP TABLE IF EXISTS jobs")
