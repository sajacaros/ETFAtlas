"""
Python 코드 예제 임베딩 DAG

DB에서 status='active'(승인됨, 미임베딩)인 레코드를 찾아 임베딩 생성 후 status='embedded'로 전환.
수동 트리거 전용 — 초기 시드 적재 후 또는 새 예제 추가 시 실행.
"""

import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from age_utils import get_db_connection

log = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50

default_args = {
    "owner": "etf-atlas",
    "depends_on_past": False,
    "start_date": datetime(2025, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "email_on_failure": False,
}

dag = DAG(
    "embed_code_examples",
    default_args=default_args,
    description="승인된 코드 예제 중 미임베딩 건 임베딩 (수동 트리거)",
    schedule_interval=None,
    catchup=False,
    tags=["embedding", "manual"],
)


def embed_and_load():
    """DB에서 미임베딩 레코드 조회 -> 배치 임베딩 -> UPDATE."""
    from openai import OpenAI

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 승인됨(active) 상태의 미임베딩 예제 조회
        cur.execute(
            "SELECT id, question FROM code_examples "
            "WHERE status = 'active' "
            "ORDER BY id"
        )
        rows = cur.fetchall()

        if not rows:
            log.info("No unembedded active examples found. Nothing to do.")
            return

        log.info("Found %d unembedded examples to process.", len(rows))

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=api_key)

        # 배치 단위로 임베딩 생성 및 업데이트
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            ids = [r[0] for r in batch]
            questions = [r[1] for r in batch]

            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=questions)
            embeddings = [item.embedding for item in resp.data]

            for row_id, emb in zip(ids, embeddings):
                emb_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    "UPDATE code_examples SET embedding = %s::vector, status = 'embedded' WHERE id = %s",
                    (emb_str, row_id),
                )

            log.info("Embedded batch %d-%d (%d items)", i + 1, i + len(batch), len(batch))

        conn.commit()
        log.info("Successfully embedded %d code examples.", len(rows))
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


PythonOperator(
    task_id="embed_code_examples",
    python_callable=embed_and_load,
    dag=dag,
)
