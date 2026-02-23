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


from generalize_prompt import GENERALIZE_SYSTEM_PROMPT


def _generalize_questions(client, questions):
    """LLM으로 질문 목록을 일반화. 개별 호출."""
    results = []
    for q in questions:
        try:
            resp = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": GENERALIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": q},
                ],
                temperature=0,
                max_tokens=200,
            )
            results.append(resp.choices[0].message.content.strip())
        except Exception as e:
            log.warning("Generalization failed for '%s': %s", q, e)
            results.append(q)
    return results


def embed_and_load():
    """DB에서 미임베딩 레코드 조회 -> 일반화 -> 배치 임베딩 -> UPDATE."""
    from openai import OpenAI

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 승인됨(active) 상태의 미임베딩 예제 조회
        cur.execute(
            "SELECT id, question, question_generalized FROM code_examples "
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

        # question_generalized가 없는 레코드는 LLM으로 생성
        needs_generalization = [r for r in rows if not r[2]]
        if needs_generalization:
            log.info("Generating generalized questions for %d examples.", len(needs_generalization))
            gen_questions = _generalize_questions(client, [r[1] for r in needs_generalization])
            for (row_id, _, _), gen_q in zip(needs_generalization, gen_questions):
                cur.execute(
                    "UPDATE code_examples SET question_generalized = %s WHERE id = %s",
                    (gen_q, row_id),
                )
            conn.commit()
            # 다시 조회하여 최신 question_generalized 반영
            cur.execute(
                "SELECT id, question, question_generalized FROM code_examples "
                "WHERE status = 'active' "
                "ORDER BY id"
            )
            rows = cur.fetchall()

        # 배치 단위로 임베딩 생성 및 업데이트 (question_generalized 우선 사용)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            ids = [r[0] for r in batch]
            embed_inputs = [r[2] or r[1] for r in batch]

            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=embed_inputs)
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
