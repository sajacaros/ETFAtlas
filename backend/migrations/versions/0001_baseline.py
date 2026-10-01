"""baseline: docker/db/init/02_schema.sql 시점의 스키마

DB를 처음 만들 때 init SQL이 이 상태의 스키마를 만든다. 이 리비전은 아무것도 하지 않고,
이미 있는 DB와 새 DB가 같은 출발점에서 이후 리비전을 적용하도록 기준만 잡는다.

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from typing import Sequence, Union

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
