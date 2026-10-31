"""
챗봇 예제 임베딩 DAG

code_examples(agent 해결 절차)와 layout_examples(레이아웃 플래너 화면 설계)에서
status='active'(승인됨, 미임베딩)인 레코드를 찾아 임베딩 생성 후 status='embedded'로 전환.
수동 트리거 전용 — 초기 시드 적재(마이그레이션 포함) 후 또는 새 예제 추가 시 실행.
"""

import logging
from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator

from ai_config import load_ai_config
from generalize_prompt import GENERALIZE_SYSTEM_PROMPT
from rdb import get_db_connection

log = logging.getLogger(__name__)

BATCH_SIZE = 50
TABLES = ("code_examples", "layout_examples")  # 쿼리 문자열에 직접 들어가는 고정 이름

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
    description="승인된 코드·레이아웃 예제 중 미임베딩 건 임베딩 (수동 트리거)",
    schedule=None,
    catchup=False,
    tags=["embedding", "manual"],
)


def _generalize_questions(client, model, questions):
    """LLM으로 질문 목록을 일반화. 개별 호출."""
    results = []
    for q in questions:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": GENERALIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": q},
                ],
                temperature=0,
                max_tokens=2048,  # 추론 모델: reasoning 토큰 포함
            )
            content = resp.choices[0].message.content
            results.append(content.strip() if content else q)
        except Exception as e:
            log.warning("Generalization failed for '%s': %s", q, e)
            results.append(q)
    return results


def embed_and_load(table):
    """DB에서 미임베딩 레코드 조회 -> 일반화 -> 배치 임베딩 -> UPDATE."""
    from openai import OpenAI

    assert table in TABLES

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 승인됨(active) 상태의 미임베딩 예제 조회
        cur.execute(
            f"SELECT id, question, question_generalized FROM {table} "
            "WHERE status = 'active' "
            "ORDER BY id"
        )
        rows = cur.fetchall()

        if not rows:
            log.info("No unembedded active rows in %s. Nothing to do.", table)
            return

        log.info("Found %d unembedded rows in %s to process.", len(rows), table)

        # 관리자 페이지 설정이 우선, 비어 있는 항목은 환경변수 (임베딩은 768차원 모델)
        ai = load_ai_config(conn)
        if not ai["llm_api_key"] or not ai["embedding_api_key"]:
            raise RuntimeError("LLM / embedding API key is not set (admin page or LLM_API_KEY / EMBEDDING_API_KEY)")

        client = OpenAI(base_url=ai["llm_api_base"], api_key=ai["llm_api_key"])  # 질문 일반화
        embed_client = OpenAI(base_url=ai["embedding_api_base"], api_key=ai["embedding_api_key"])

        # question_generalized가 없는 레코드는 LLM으로 생성
        needs_generalization = [r for r in rows if not r[2]]
        if needs_generalization:
            log.info("Generating generalized questions for %d examples.", len(needs_generalization))
            gen_questions = _generalize_questions(client, ai["llm_model"], [r[1] for r in needs_generalization])
            for (row_id, _, _), gen_q in zip(needs_generalization, gen_questions):
                cur.execute(
                    f"UPDATE {table} SET question_generalized = %s WHERE id = %s",
                    (gen_q, row_id),
                )
            conn.commit()
            # 다시 조회하여 최신 question_generalized 반영
            cur.execute(
                f"SELECT id, question, question_generalized FROM {table} "
                "WHERE status = 'active' "
                "ORDER BY id"
            )
            rows = cur.fetchall()

        # 배치 단위로 임베딩 생성 및 업데이트 (question_generalized 우선 사용)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            ids = [r[0] for r in batch]
            embed_inputs = [r[2] or r[1] for r in batch]

            resp = embed_client.embeddings.create(
                model=ai["embedding_model"], input=embed_inputs
            )
            embeddings = [item.embedding for item in resp.data]

            for row_id, emb in zip(ids, embeddings):
                emb_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    f"UPDATE {table} SET embedding = %s::vector, status = 'embedded' WHERE id = %s",
                    (emb_str, row_id),
                )

            log.info("Embedded batch %d-%d (%d items)", i + 1, i + len(batch), len(batch))

        conn.commit()
        log.info("Successfully embedded %d rows in %s.", len(rows), table)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


for _table in TABLES:
    PythonOperator(
        task_id=f"embed_{_table}",
        python_callable=embed_and_load,
        op_kwargs={"table": _table},
        dag=dag,
    )
