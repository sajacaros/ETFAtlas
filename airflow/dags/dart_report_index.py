"""
DART Report Index DAG — 정기보고서를 목차 트리로 색인 (챗봇 company_report·company_revenue_mix)

PageIndex 방식: 원문 구조로 목차 트리를 만들고(LLM 없음), 등록된 LLM이 노드마다 '이 절에 든 항목' 한 줄 색인을
붙인다. 챗봇은 그 목차를 보고 질문에 맞는 절을 골라 읽는다. 파서와 요약 프롬프트는 backend의 app.services.report_tree.

1. queue_reports: 그래프 종목의 최근 1년 정기보고서(주요계정·공시 목록의 접수번호, 같은 기간이면 정정본)를
   stock_reports에 pending으로 올린다.
2. build_trees: 원문 zip을 받아(stock_report_docs) 트리를 만든다 → tree. 파서 버전이 바뀐 보고서는 보관한 원문으로
   다시 만들고, 내용이 같은 노드(content_hash)는 요약을 이어받는다.
3. summarize_nodes: 등록된 LLM(관리자 페이지 ai_settings, 추론 끔)으로 노드 요약 → summarized.
   처음에는 보고서가 수천 건이라 실행당 시간 예산 안에서 종목별 최신 보고서부터 한다. 트리만 있어도 챗봇은 제목으로 고른다.
4. prune_reports: 정정본이 색인된 원래 보고서와 1년 지난 보고서(종목마다 최신 1건은 남긴다)를 지운다.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import logging
import time

from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator

from age_utils import get_db_connection, load_ai_config

log = logging.getLogger(__name__)

KEEP_DAYS = 365
BUILD_MINUTES = 90
# 21:00부터 밤새(약 10시간). 처음 밀린 수천 건을 2~3일에 끝내고, 그 뒤로는 새 보고서만이라 금방 끝난다
SUMMARY_MINUTES = 600
# 등록 LLM(H100 한 장, FP8)은 동시 8개에서 처리량이 가장 높고(4개 대비 약 1.3배) 16개면 오히려 느려진다.
# 챗봇이 같은 LLM을 쓰므로 6개로 여유를 둔다
SUMMARY_WORKERS = 6
SUMMARY_TIMEOUT = 180
READY = ('tree', 'summarized')

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=10),
    'email_on_failure': False,
}

dag = DAG(
    'dart_report_index',
    default_args=default_args,
    description='DART 정기보고서 목차 트리 색인 (원문 → 트리 → 등록 LLM 노드 요약)',
    schedule='0 21 * * *',  # 매일 21:00 KST — dart_sync_rdb(평일 19:20)가 공시·주요계정을 받은 뒤. 주말엔 밀린 요약을 한다
    catchup=False,
    max_active_runs=1,
    # 배포하면 바로 21:00부터 돈다 — 색인 전에는 company_report가 답하지 못한다. 이미 색인한 보고서는 다시 하지 않는다
    is_paused_upon_creation=False,
    tags=['dart', 'daily', 'rdb', 'llm'],
)

# 종목별 최신 보고서부터 (처음 색인할 때 모든 종목이 빨리 답할 수 있게)
PRIORITY = "ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY rcept_no DESC)"


def queue_reports(**context):
    from psycopg2.extras import execute_values
    from dart_sync_rdb import graph_stocks
    from app.services.report_tree import latest_reports

    stocks = sorted(graph_stocks())
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT DISTINCT stock_code, rcept_no, bsns_year, reprt_code FROM stock_financials
                       WHERE rcept_no IS NOT NULL AND stock_code = ANY(%s)""", (stocks,))
        financials = cur.fetchall()
        cur.execute("SELECT stock_code, rcept_no, report_nm FROM stock_disclosures WHERE stock_code = ANY(%s)", (stocks,))
        disclosures = cur.fetchall()
        rows = latest_reports(financials, disclosures, datetime.now().date() - timedelta(days=KEEP_DAYS))
        if rows:
            execute_values(cur, """
                INSERT INTO stock_reports (rcept_no, stock_code, report_nm, period, status, created_at) VALUES %s
                ON CONFLICT (rcept_no) DO UPDATE SET report_nm = EXCLUDED.report_nm, period = EXCLUDED.period
            """, [(*r, 'pending', datetime.now()) for r in rows])
        conn.commit()
        cur.execute("SELECT status, count(*) FROM stock_reports GROUP BY status")
        counts = dict(cur.fetchall())
    finally:
        cur.close()
        conn.close()
    log.info("stock_reports: 후보 %d건 (%d개 종목), 상태 %s", len(rows), len(stocks), counts)


def _save_tree(cur, rcept_no: str, nodes) -> int:
    """노드를 새로 쓴다. 내용이 같은 노드는 요약을 이어받는다. 반환: 요약이 더 필요한 노드 수."""
    from psycopg2.extras import execute_values
    from app.services.report_tree import PARSER_VERSION, needs_summary

    cur.execute("SELECT node_id, content_hash, summary, summary_model FROM report_nodes WHERE rcept_no = %s", (rcept_no,))
    previous = {row[0]: row[1:] for row in cur.fetchall()}
    cur.execute("DELETE FROM report_nodes WHERE rcept_no = %s", (rcept_no,))
    rows, missing = [], 0
    for n in nodes:
        old_hash, summary, model = previous.get(n.node_id, (None, None, None))
        if old_hash != n.content_hash:
            summary = model = None
        if summary is None and needs_summary(n):
            missing += 1
        rows.append((rcept_no, n.node_id, n.parent_id, n.seq, n.level, n.title, n.path, n.chars, n.blocks_json(),
                     n.content_hash, summary, model))
    execute_values(cur, """
        INSERT INTO report_nodes (rcept_no, node_id, parent_id, seq, level, title, path, chars, blocks,
                                  content_hash, summary, summary_model) VALUES %s
    """, rows, page_size=200)
    cur.execute("""UPDATE stock_reports SET status = %s, parser_version = %s, indexed_at = %s, error = NULL,
                   summarized_at = CASE WHEN %s THEN %s ELSE NULL END WHERE rcept_no = %s""",
                ('tree' if missing else 'summarized', PARSER_VERSION, datetime.now(), not missing, datetime.now(), rcept_no))
    return missing


def build_trees(**context):
    import psycopg2
    from dart_sync_rdb import _client
    from app.services.report_tree import PARSER_VERSION, build_tree, parse_document

    client = _client()  # 키가 없어도 보관한 원문으로 다시 만드는 것은 한다
    conn = get_db_connection()
    cur = conn.cursor()
    deadline = time.monotonic() + BUILD_MINUTES * 60
    built = failed = 0
    try:
        cur.execute(f"""
            SELECT r.rcept_no, d.rcept_no IS NOT NULL FROM (
                SELECT rcept_no, status, parser_version, {PRIORITY} AS rank FROM stock_reports) r
            LEFT JOIN stock_report_docs d ON d.rcept_no = r.rcept_no
            WHERE r.status IN ('pending', 'failed')
               OR (r.status IN ('tree', 'summarized') AND coalesce(r.parser_version, 0) < %s)
            ORDER BY r.rank, r.rcept_no DESC
        """, (PARSER_VERSION,))
        queue = cur.fetchall()
        for rcept_no, stored in queue:
            if time.monotonic() > deadline:
                log.info("시간 예산(%d분)을 다 써서 멈춥니다 — 남은 %d건은 다음 실행에서", BUILD_MINUTES, len(queue) - built - failed)
                break
            if not stored and client is None:
                continue
            try:
                if stored:
                    cur.execute("SELECT zip FROM stock_report_docs WHERE rcept_no = %s", (rcept_no,))
                    zip_bytes = bytes(cur.fetchone()[0])
                else:
                    zip_bytes = client.document(rcept_no)
                    cur.execute("""INSERT INTO stock_report_docs (rcept_no, zip, fetched_at) VALUES (%s, %s, %s)
                                   ON CONFLICT (rcept_no) DO UPDATE SET zip = EXCLUDED.zip, fetched_at = EXCLUDED.fetched_at""",
                                (rcept_no, psycopg2.Binary(zip_bytes), datetime.now()))
                nodes = build_tree(parse_document(zip_bytes))
                if not nodes:
                    raise ValueError("원문에서 목차를 찾지 못했습니다")
                _save_tree(cur, rcept_no, nodes)
                conn.commit()
                built += 1
            except Exception as e:
                conn.rollback()
                failed += 1
                log.warning("report %s: %s", rcept_no, e)
                cur.execute("UPDATE stock_reports SET status = 'failed', error = %s WHERE rcept_no = %s",
                            (str(e)[:500], rcept_no))
                conn.commit()
    finally:
        cur.close()
        conn.close()
    log.info("report trees: %d건 만듦, 실패 %d", built, failed)


def _summarize(client, model: str, node) -> str | None:
    from app.services.report_tree import SUMMARY_PROMPT, clean_summary, summary_prompt

    try:
        res = client.chat.completions.create(
            model=model, temperature=0, timeout=SUMMARY_TIMEOUT,
            messages=[{'role': 'system', 'content': SUMMARY_PROMPT}, {'role': 'user', 'content': summary_prompt(node)}],
            # 추론을 켜 두면 노드 하나에 몇 분씩 걸린다
            extra_body={'chat_template_kwargs': {'enable_thinking': False}},
        )
        return clean_summary(res.choices[0].message.content) or None
    except Exception as e:
        log.warning("summary %s failed: %s", node.path, e)
        return None


def summarize_nodes(**context):
    from openai import OpenAI
    from psycopg2.extras import execute_batch
    from app.services.report_tree import Block, Node, needs_summary

    conn = get_db_connection()
    ai = load_ai_config(conn)
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping report summaries")
        conn.close()
        return
    client = OpenAI(base_url=ai['llm_api_base'], api_key=ai['llm_api_key'])
    model = ai['llm_model']
    cur = conn.cursor()
    deadline = time.monotonic() + SUMMARY_MINUTES * 60
    reports = summarized = 0
    try:
        cur.execute(f"""SELECT rcept_no FROM (SELECT rcept_no, status, {PRIORITY} AS rank FROM stock_reports) r
                        WHERE status = 'tree' ORDER BY rank, rcept_no DESC""")
        queue = [row[0] for row in cur.fetchall()]
        with ThreadPoolExecutor(SUMMARY_WORKERS) as pool:
            for rcept_no in queue:
                if time.monotonic() > deadline:
                    log.info("시간 예산(%d분)을 다 써서 멈춥니다 — 남은 %d건은 다음 실행에서", SUMMARY_MINUTES, len(queue) - reports)
                    break
                cur.execute("""SELECT node_id, parent_id, seq, level, title, path, blocks FROM report_nodes
                               WHERE rcept_no = %s AND summary IS NULL ORDER BY seq""", (rcept_no,))
                nodes = [Node(r[0], r[1], r[2], r[3], r[4], r[5], [Block.from_json(b) for b in json.loads(r[6])])
                         for r in cur.fetchall()]
                targets = [n for n in nodes if needs_summary(n)]
                results = list(pool.map(lambda n: _summarize(client, model, n), targets))
                done = [(s, model, rcept_no, n.node_id) for n, s in zip(targets, results) if s]
                execute_batch(cur, "UPDATE report_nodes SET summary = %s, summary_model = %s WHERE rcept_no = %s AND node_id = %s",
                              done)
                if len(done) == len(targets):  # 하나라도 실패하면 tree로 두고 다음 실행에서 남은 노드만 다시
                    cur.execute("UPDATE stock_reports SET status = 'summarized', summarized_at = %s WHERE rcept_no = %s",
                                (datetime.now(), rcept_no))
                conn.commit()
                reports += 1
                summarized += len(done)
    finally:
        cur.close()
        conn.close()
    log.info("report summaries: 보고서 %d건, 노드 %d개 (모델 %s)", reports, summarized, model)


def prune_reports(**context):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 정정본이 색인되면 같은 기간의 원래 보고서는 지운다 (원문·노드는 FK CASCADE)
        cur.execute("""
            DELETE FROM stock_reports o USING stock_reports n
            WHERE o.stock_code = n.stock_code AND o.period = n.period AND o.rcept_no < n.rcept_no
              AND n.status IN ('tree', 'summarized')
        """)
        superseded = cur.rowcount
        # 1년 지난 보고서. 종목마다 가장 최근에 색인된 1건은 남긴다 (새 보고서가 늦어져도 답할 수 있게)
        cur.execute("""
            DELETE FROM stock_reports r
            WHERE to_date(left(r.rcept_no, 8), 'YYYYMMDD') < current_date - %s
              AND r.rcept_no <> (SELECT max(x.rcept_no) FROM stock_reports x
                                 WHERE x.stock_code = r.stock_code AND x.status IN ('tree', 'summarized'))
        """, (KEEP_DAYS,))
        expired = cur.rowcount
        conn.commit()
    finally:
        cur.close()
        conn.close()
    log.info("stock_reports 정리: 정정으로 대체 %d건, 1년 지남 %d건", superseded, expired)


t_queue = PythonOperator(task_id='queue_reports', python_callable=queue_reports, dag=dag)
t_trees = PythonOperator(task_id='build_trees', python_callable=build_trees, dag=dag,
                         execution_timeout=timedelta(minutes=BUILD_MINUTES + 30))
t_summaries = PythonOperator(task_id='summarize_nodes', python_callable=summarize_nodes, dag=dag,
                             execution_timeout=timedelta(minutes=SUMMARY_MINUTES + 30))
t_prune = PythonOperator(task_id='prune_reports', python_callable=prune_reports, dag=dag)

t_queue >> t_trees >> t_summaries >> t_prune
