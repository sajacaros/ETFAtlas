"""layout_examples: write return periods as rank's period argument

rank now takes by="return" with a free-form period ("2w", "45d", "ytd", ...)
instead of five fixed return_1w..return_1y metrics, so questions naming any
period get exactly that period. Existing examples are rewritten to the new
shape (rank still reads the old one). The company analysis example loses its
fixed six-month trend so the planner falls back to the default period instead
of copying a period the question never asked for.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-26 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0035'
down_revision: Union[str, Sequence[str], None] = '0034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYSIS = "삼성전자 기업 분석해줘"


def upgrade() -> None:
    op.execute("""UPDATE layout_examples
                  SET plan = regexp_replace(plan, '"by": "return_(\\w+)"', '"by": "return", "period": "\\1"', 'g')
                  WHERE plan ~ '"by": "return_'""")
    op.execute(f"""UPDATE layout_examples SET plan = replace(plan, ', "period": "6m"}}', '}}')
                   WHERE question = '{ANALYSIS}'""")


def downgrade() -> None:
    op.execute("""UPDATE layout_examples
                  SET plan = regexp_replace(plan, '"by": "return", "period": "(\\w+)"', '"by": "return_\\1"', 'g')
                  WHERE plan ~ '"by": "return", "period"'""")
    op.execute(f"""UPDATE layout_examples
                   SET plan = replace(plan, '"stocks": ["<종목>"]}}', '"stocks": ["<종목>"], "period": "6m"}}')
                   WHERE question = '{ANALYSIS}'""")
