"""
Python 코드 예제 임베딩 DAG

code_examples.json을 읽어 OpenAI 임베딩 생성 후 code_examples 테이블에 적재.
수동 트리거 전용 — 예제 JSON 변경 시에만 실행.
"""

import json
import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from age_utils import get_db_connection

log = logging.getLogger(__name__)

EXAMPLES_PATH = "/opt/airflow/data/code_examples.json"
EMBEDDING_MODEL = "text-embedding-3-small"

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
    description="Python 코드 예제 임베딩 적재 (수동 트리거)",
    schedule_interval=None,
    catchup=False,
    tags=["embedding", "manual"],
)


def embed_and_load():
    """JSON 읽기 -> 배치 임베딩 -> TRUNCATE + INSERT."""
    from openai import OpenAI

    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        examples = json.load(f)

    if not examples:
        log.warning("No examples found in %s", EXAMPLES_PATH)
        return

    log.info("Embedding %d code examples...", len(examples))

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)

    questions = [ex["question"] for ex in examples]
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=questions)
    embeddings = [item.embedding for item in resp.data]

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE code_examples")

        for ex, emb in zip(examples, embeddings):
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            cur.execute(
                "INSERT INTO code_examples (question, code, description, embedding) "
                "VALUES (%s, %s, %s, %s::vector)",
                (
                    ex["question"],
                    ex["code"],
                    ex.get("description", ""),
                    emb_str,
                ),
            )

        conn.commit()
        log.info("Loaded %d code examples into code_examples table", len(examples))
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
