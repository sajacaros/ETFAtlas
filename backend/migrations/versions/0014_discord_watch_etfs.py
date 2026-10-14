"""discord_watch_etfs: ETFs to monitor for Discord alerts, seeded from admin watchlists

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14 10:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _admin_watches(bind) -> list[tuple[str, str]]:
    """지금까지 알림 대상이던 관리자 즐겨찾기(AGE WATCHES)를 읽는다. 그래프가 없으면 빈 목록."""
    admin_ids = [r[0] for r in bind.execute(sa.text(
        "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE r.name = 'admin'"
    ))]
    if not admin_ids:
        return []
    ids = ", ".join(str(int(i)) for i in admin_ids)
    try:
        with bind.begin_nested():
            bind.execute(sa.text("LOAD 'age'"))
            bind.execute(sa.text('SET LOCAL search_path = ag_catalog, "$user", public'))
            # sa.text는 [:WATCHES]를 바인드 파라미터로 읽으므로 드라이버에 그대로 넘긴다
            rows = bind.exec_driver_sql(
                "SELECT * FROM cypher('etf_graph', $$ "
                f"MATCH (u:User)-[:WATCHES]->(e:ETF) WHERE u.user_id IN [{ids}] "
                "RETURN DISTINCT {code: e.code, name: e.name} $$) AS (result agtype)"
            ).fetchall()
    except Exception:
        return []
    watches = []
    for (raw,) in rows:
        data = json.loads(str(raw).split('::')[0])
        watches.append((data['code'], data['name']))
    return watches


def upgrade() -> None:
    op.create_table(
        'discord_watch_etfs',
        sa.Column('etf_code', sa.String(20), nullable=False),
        sa.Column('etf_name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('etf_code'),
    )
    bind = op.get_bind()
    search_path = bind.execute(sa.text("SHOW search_path")).scalar()
    watches = _admin_watches(bind)
    bind.execute(sa.text("SELECT set_config('search_path', :p, true)"), {"p": search_path})
    for code, name in watches:
        bind.execute(
            sa.text("INSERT INTO discord_watch_etfs (etf_code, etf_name, created_at) VALUES (:c, :n, now())"),
            {"c": code, "n": name},
        )


def downgrade() -> None:
    op.drop_table('discord_watch_etfs')
