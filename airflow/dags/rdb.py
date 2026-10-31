"""
rdb — 앱 DB(PostgreSQL) 연결

모든 DAG가 같은 연결 함수를 쓴다. DATABASE_URL을 그대로 libpq에 넘긴다(직접 나누지 않는다).
"""

import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = 'postgresql://postgres:postgres@db:5432/etf_atlas'


def get_db_connection():
    """DATABASE_URL로 새 연결. 닫는 것은 부르는 쪽이 한다 (connection() 컨텍스트 매니저를 쓰면 저절로 닫힌다)."""
    import psycopg2

    return psycopg2.connect(os.environ.get('DATABASE_URL') or DEFAULT_DATABASE_URL)


@contextmanager
def connection():
    """with connection() as conn: — 나올 때 연결을 닫는다. 커밋은 부르는 쪽이 한다."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def record_collection_run(date_str: str) -> bool:
    """collection_runs 테이블에 수집 완료 기록 + pg_notify 발행.

    Returns: True if new record inserted, False if already existed.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO collection_runs (collected_at) VALUES (%s) "
            "ON CONFLICT (collected_at) DO NOTHING",
            (date_str,)
        )
        inserted = cur.rowcount > 0
        if inserted:
            cur.execute("NOTIFY new_collection, %s", (date_str,))
            log.info(f"Collection run recorded + notified: {date_str}")
        else:
            log.info(f"Collection run already exists: {date_str} — skipping notify")
        conn.commit()
        return inserted
