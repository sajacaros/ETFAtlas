"""
DART Report Index DAG — 정기보고서를 목차 트리로 색인 (챗봇 company_report·company_revenue_mix)

PageIndex 방식: 원문 구조로 목차 트리를 만들고(LLM 없음), 등록된 LLM이 노드마다 '이 절에 든 항목' 한 줄 색인을
붙인다. 챗봇은 그 목차를 보고 질문에 맞는 절을 골라 읽는다. 파서와 요약 프롬프트는 backend의 app.services.report_tree.

1. queue_reports: 그래프 종목의 최근 1년 정기보고서(주요계정·공시 목록의 접수번호, 같은 기간이면 정정본)를
   stock_reports에 pending으로 올린다.
   첨부만 바꾼 공시([첨부정정]·[첨부추가])와 옛 기간의 정정본은 올리지 않고, 이미 올라 있으면 지운다.
2. build_trees: 원문 zip을 받아(stock_report_docs) 트리를 만든다 → tree. 파서 버전이 바뀐 보고서는 보관한 원문으로
   다시 만들고, 내용이 같은 노드(content_hash)는 요약을 이어받는다. DART가 원문을 주지 않는 접수번호(상태 014)는
   missing으로 두고 다시 받지 않는다 — 그 회사의 같은 기간 공시를 DART에서 다시 받아 두어, 다음 실행이 그 전 접수를 올린다.
3. summarize_nodes: 등록된 LLM(관리자 페이지 ai_settings, 추론 끔)으로 노드 요약 → summarized.
   처음에는 보고서가 수천 건이라 실행당 시간 예산 안에서 종목별 최신 보고서부터 한다. 트리만 있어도 챗봇은 제목으로 고른다.
   REPORT_SUMMARY_ENDPOINTS(환경변수, JSON 목록)에 같은 모델을 띄운 서버를 더 적으면 요약을 나눠 보낸다 (밀린 색인을 빨리 끝낼 때).
4. prune_reports: 정정본이 색인된 원래 보고서와 1년 지난 보고서(종목마다 최신 1건은 남긴다)를 지운다.
5. make_overviews: 종목별 최신 보고서(챗봇 company_report가 고르는 것)의 개요(사업 구조·영업 상황·위험 요인·소송)를
   등록된 LLM으로 만들어 stock_reports.overview에 남긴다. 매수 의견(stock_opinion)이 개요를 읽으므로 질문이 오기 전에 채워 둔다.
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
# 요약은 한 줄(40토큰 안팎)이다. 상한이 없으면 드물게 끝없이 이어 쓰는 노드가 시간 초과·재시도까지 묶음 전체를 붙잡는다
SUMMARY_MAX_TOKENS = 256
SUMMARY_RETRIES = 1
# 보고서마다 노드를 다 받은 뒤 다음으로 넘어가면 마지막 몇 개를 기다리는 동안 다른 자리가 논다. 동시 수의 이 배수만큼 노드를 모아 보낸다
SUMMARY_BATCH_FACTOR = 4
READY = ('tree', 'summarized')
# 개요는 보고서당 한 번(입력 최대 4만 8천 자, 출력 글머리표 십여 줄). 처음 수백 건을 채운 뒤로는 새 보고서만이다
OVERVIEW_MINUTES = 180
OVERVIEW_TIMEOUT = 300
OVERVIEW_MAX_TOKENS = 2048
DART_NO_FILE = '014'  # document.xml: '파일이 존재하지 않습니다'


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
    description='DART 정기보고서 목차 트리 색인 (원문 → 트리 → 등록 LLM 노드 요약 → 최신 보고서 개요)',
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
    from app.services.report_tree import attachment_only, latest_reports, stale_period

    stocks = sorted(graph_stocks())
    since = datetime.now().date() - timedelta(days=KEEP_DAYS)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT DISTINCT stock_code, rcept_no, bsns_year, reprt_code FROM stock_financials
                       WHERE rcept_no IS NOT NULL AND stock_code = ANY(%s)""", (stocks,))
        financials = cur.fetchall()
        cur.execute("SELECT stock_code, rcept_no, report_nm FROM stock_disclosures WHERE stock_code = ANY(%s)", (stocks,))
        disclosures = cur.fetchall()
        cur.execute("SELECT rcept_no, report_nm, period, status FROM stock_reports")
        existing = cur.fetchall()
        missing = {r[0] for r in existing if r[3] == 'missing'}
        # 이제는 올리지 않는 보고서 (첨부만 바꾼 공시, 옛 기간의 정정본). 원문·노드는 FK CASCADE
        dropped = [r[0] for r in existing if attachment_only(r[1]) or stale_period(r[2], since)]
        if dropped:
            cur.execute("DELETE FROM stock_reports WHERE rcept_no = ANY(%s)", (dropped,))
            log.info("stock_reports: 첨부 정정·옛 기간 정정본 %d건 지움 %s", len(dropped), dropped[:10])
        rows = latest_reports(financials, disclosures, since, exclude=missing)
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
    from dart_client import DartError
    from dart_sync_rdb import _client
    from app.services.report_tree import PARSER_VERSION, build_tree, parse_document

    client = _client()  # 키가 없어도 보관한 원문으로 다시 만드는 것은 한다
    conn = get_db_connection()
    cur = conn.cursor()
    deadline = time.monotonic() + BUILD_MINUTES * 60
    built = failed = 0
    try:
        cur.execute(f"""
            SELECT r.rcept_no, r.stock_code, r.period, d.rcept_no IS NOT NULL FROM (
                SELECT rcept_no, stock_code, period, status, parser_version, {PRIORITY} AS rank FROM stock_reports) r
            LEFT JOIN stock_report_docs d ON d.rcept_no = r.rcept_no
            WHERE r.status IN ('pending', 'failed')
               OR (r.status IN ('tree', 'summarized') AND coalesce(r.parser_version, 0) < %s)
            ORDER BY r.rank, r.rcept_no DESC
        """, (PARSER_VERSION,))
        queue = cur.fetchall()
        for rcept_no, stock_code, period, stored in queue:
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
            except DartError as e:
                conn.rollback()
                failed += 1
                if f'<status>{DART_NO_FILE}</status>' not in str(e):
                    log.warning("report %s: %s", rcept_no, e)
                    cur.execute("UPDATE stock_reports SET status = 'failed', error = %s WHERE rcept_no = %s",
                                (str(e)[:500], rcept_no))
                else:
                    # 정정 공시 중에는 DART가 원문을 주지 않는 것이 있다. 다시 받아도 같으므로 missing으로 두고,
                    # 같은 기간의 그 전 접수를 다음 실행이 올릴 수 있게 그 회사 공시를 받아 둔다
                    found = _fetch_period_disclosures(cur, client, stock_code, period, rcept_no)
                    log.warning("report %s: DART에 원문이 없습니다 — missing (같은 기간 공시 %d건 받음)", rcept_no, found)
                    cur.execute("UPDATE stock_reports SET status = 'missing', error = %s WHERE rcept_no = %s",
                                (str(e)[:500], rcept_no))
                conn.commit()
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


def _fetch_period_disclosures(cur, client, stock_code: str, period: str | None, rcept_no: str) -> int:
    """stock_code 회사가 period 기간이 끝난 뒤부터 rcept_no 접수일까지 낸 공시를 stock_disclosures에 넣는다."""
    from dart_sync_rdb import _save_disclosures
    from app.services.report_tree import filed_date, period_end

    if not period:
        return 0
    cur.execute("SELECT corp_code FROM dart_corps WHERE stock_code = %s", (stock_code,))
    row = cur.fetchone()
    if not row:
        return 0
    start = period_end(period).strftime('%Y%m%d')
    items = list(client.disclosures(start, filed_date(rcept_no).strftime('%Y%m%d'), row[0]))
    return _save_disclosures(cur, items, {stock_code: stock_code})


def summary_endpoints(ai: dict, extra: str | None = None) -> list[dict]:
    """요약을 보낼 LLM 서버들: 등록된 LLM(SUMMARY_WORKERS개) + 더 쓸 서버(Airflow Variable report_summary_endpoints,
    없으면 환경변수 REPORT_SUMMARY_ENDPOINTS). Variable은 컨테이너를 다시 띄우지 않고 바꿀 수 있다.

    예: [{"base_url": "http://host:7900/qwen38/v1", "api_key": "...", "model": "qwen38-27b", "workers": 8}]
    모두 같은 모델(가중치)이어야 한다 — 요약이 섞여도 목차 색인의 결이 같게.
    """
    endpoints = [{'base_url': ai['llm_api_base'], 'api_key': ai['llm_api_key'], 'model': ai['llm_model'],
                  'workers': SUMMARY_WORKERS}]
    raw = (_extra_endpoints() if extra is None else extra).strip()
    if raw:
        for e in json.loads(raw):
            endpoints.append({'base_url': e['base_url'], 'api_key': e.get('api_key') or 'EMPTY',
                              'model': e.get('model') or ai['llm_model'], 'workers': int(e.get('workers', SUMMARY_WORKERS))})
    return endpoints


def _extra_endpoints() -> str:
    import os
    from airflow.sdk import Variable

    try:
        value = Variable.get('report_summary_endpoints', default='')
    except Exception:  # 태스크 밖(테스트 등)에서는 Variable을 못 읽는다
        value = ''
    return value or os.environ.get('REPORT_SUMMARY_ENDPOINTS', '')


class SummarySlots:
    """LLM 서버마다 workers개의 자리. 노드 하나를 요약할 때 빈 자리를 빌려 쓰고 돌려준다 —
    빠른 서버의 자리가 먼저 돌아오므로 서버마다 처리량에 맞게 나뉜다."""

    def __init__(self, endpoints: list[dict]):
        import queue
        from openai import OpenAI

        self.size = sum(e['workers'] for e in endpoints)
        self.free = queue.Queue()
        for e in endpoints:
            client = OpenAI(base_url=e['base_url'], api_key=e['api_key'], max_retries=SUMMARY_RETRIES)
            for _ in range(e['workers']):
                self.free.put((client, e['model']))

    def call(self, fn, *args):
        """(fn(client, model, *args), model)."""
        client, model = self.free.get()
        try:
            return fn(client, model, *args), model
        finally:
            self.free.put((client, model))

    def summarize(self, node) -> tuple[str | None, str]:
        return self.call(_summarize, node)


def _summarize(client, model: str, node) -> str | None:
    from app.services.report_tree import SUMMARY_PROMPT, clean_summary, summary_prompt

    try:
        res = client.chat.completions.create(
            model=model, temperature=0, timeout=SUMMARY_TIMEOUT, max_tokens=SUMMARY_MAX_TOKENS,
            messages=[{'role': 'system', 'content': SUMMARY_PROMPT}, {'role': 'user', 'content': summary_prompt(node)}],
            # 추론을 켜 두면 노드 하나에 몇 분씩 걸린다
            extra_body={'chat_template_kwargs': {'enable_thinking': False}},
        )
        return clean_summary(res.choices[0].message.content) or None
    except Exception as e:
        log.warning("summary %s failed: %s", node.path, e)
        return None


def summarize_nodes(**context):
    from psycopg2.extras import execute_batch
    from app.services.report_tree import Block, Node, needs_summary

    conn = get_db_connection()
    ai = load_ai_config(conn)
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping report summaries")
        conn.close()
        return
    endpoints = summary_endpoints(ai)
    slots = SummarySlots(endpoints)
    log.info("요약 서버 %d곳, 동시 %d개: %s", len(endpoints), slots.size,
             ", ".join(f"{e['base_url']} ×{e['workers']}" for e in endpoints))
    cur = conn.cursor()
    deadline = time.monotonic() + SUMMARY_MINUTES * 60
    reports = summarized = 0
    try:
        cur.execute(f"""SELECT rcept_no FROM (SELECT rcept_no, status, {PRIORITY} AS rank FROM stock_reports) r
                        WHERE status = 'tree' ORDER BY rank, rcept_no DESC""")
        queue = [row[0] for row in cur.fetchall()]
        with ThreadPoolExecutor(slots.size) as pool:
            pos = 0
            while pos < len(queue):
                if time.monotonic() > deadline:
                    log.info("시간 예산(%d분)을 다 써서 멈춥니다 — 남은 %d건은 다음 실행에서", SUMMARY_MINUTES, len(queue) - reports)
                    break
                batch = []  # (보고서, 요약할 노드) — 노드가 동시 수의 몇 배가 될 때까지 보고서를 모은다
                while pos < len(queue) and sum(len(t) for _, t in batch) < slots.size * SUMMARY_BATCH_FACTOR:
                    rcept_no = queue[pos]
                    pos += 1
                    cur.execute("""SELECT node_id, parent_id, seq, level, title, path, blocks FROM report_nodes
                                   WHERE rcept_no = %s AND summary IS NULL ORDER BY seq""", (rcept_no,))
                    nodes = [Node(r[0], r[1], r[2], r[3], r[4], r[5], [Block.from_json(b) for b in json.loads(r[6])])
                             for r in cur.fetchall()]
                    batch.append((rcept_no, [n for n in nodes if needs_summary(n)]))
                jobs = [(rcept_no, n) for rcept_no, targets in batch for n in targets]
                results = list(pool.map(lambda job: slots.summarize(job[1]), jobs))
                done = [(s, model, rcept_no, n.node_id) for (rcept_no, n), (s, model) in zip(jobs, results) if s]
                execute_batch(cur, "UPDATE report_nodes SET summary = %s, summary_model = %s WHERE rcept_no = %s AND node_id = %s",
                              done)
                finished = {}
                for (rcept_no, _), (s, _) in zip(jobs, results):
                    finished[rcept_no] = finished.get(rcept_no, True) and bool(s)
                for rcept_no, targets in batch:
                    if finished.get(rcept_no, True):  # 하나라도 실패하면 tree로 두고 다음 실행에서 남은 노드만 다시
                        cur.execute("UPDATE stock_reports SET status = 'summarized', summarized_at = %s WHERE rcept_no = %s",
                                    (datetime.now(), rcept_no))
                conn.commit()
                reports += len(batch)
                summarized += len(done)
    finally:
        cur.close()
        conn.close()
    log.info("report summaries: 보고서 %d건, 노드 %d개 (모델 %s)", reports, summarized,
             ", ".join(sorted({e['model'] for e in endpoints})))


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
              AND r.rcept_no <> (SELECT x.rcept_no FROM stock_reports x
                                 WHERE x.stock_code = r.stock_code AND x.status IN ('tree', 'summarized')
                                 ORDER BY x.period DESC NULLS LAST, x.rcept_no DESC LIMIT 1)
        """, (KEEP_DAYS,))
        expired = cur.rowcount
        conn.commit()
    finally:
        cur.close()
        conn.close()
    log.info("stock_reports 정리: 정정으로 대체 %d건, 1년 지남 %d건", superseded, expired)


def _overview(client, model: str, prompt: str) -> str | None:
    from app.services.report_tree import OVERVIEW_PROMPT

    try:
        res = client.chat.completions.create(
            model=model, temperature=0, timeout=OVERVIEW_TIMEOUT, max_tokens=OVERVIEW_MAX_TOKENS,
            messages=[{'role': 'system', 'content': OVERVIEW_PROMPT}, {'role': 'user', 'content': prompt}],
            extra_body={'chat_template_kwargs': {'enable_thinking': False}},
        )
        return (res.choices[0].message.content or '').strip() or None
    except Exception as e:
        log.warning("overview failed: %s", e)
        return None


def overview_queue(cur) -> list[tuple[str, str, str]]:
    """개요가 없는 종목별 최신 보고서 [(접수번호, 회사 이름, 보고서 이름)]. 고르는 기준은 company_report.pick_report와 같다
    (색인을 마친 보고서 중 가장 최근 기간, 같은 기간이면 가장 최근 접수)."""
    cur.execute("""
        SELECT r.rcept_no, coalesce(c.corp_name, r.stock_code), r.report_nm FROM (
            SELECT DISTINCT ON (stock_code) rcept_no, stock_code, report_nm, overview FROM stock_reports
            WHERE status = ANY(%s) ORDER BY stock_code, period DESC NULLS LAST, rcept_no DESC
        ) r
        LEFT JOIN LATERAL (SELECT corp_name FROM dart_corps WHERE stock_code = r.stock_code LIMIT 1) c ON true
        WHERE r.overview IS NULL ORDER BY r.rcept_no DESC
    """, (list(READY),))
    return cur.fetchall()


def make_overviews(**context):
    from psycopg2.extras import execute_batch
    from app.services.report_tree import Block, Node, overview_entries, overview_prompt, overview_source

    conn = get_db_connection()
    ai = load_ai_config(conn)
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping report overviews")
        conn.close()
        return
    # 챗봇이 만드는 개요와 같은 모델로 — 노드 요약에 더 붙인 서버(report_summary_endpoints)는 쓰지 않는다
    slots = SummarySlots(summary_endpoints(ai, extra=''))
    cur = conn.cursor()
    deadline = time.monotonic() + OVERVIEW_MINUTES * 60
    made = failed = 0
    try:
        queue = overview_queue(cur)
        log.info("개요를 만들 보고서 %d건", len(queue))
        with ThreadPoolExecutor(slots.size) as pool:
            for start in range(0, len(queue), slots.size):
                if time.monotonic() > deadline:
                    log.info("시간 예산(%d분)을 다 써서 멈춥니다 — 남은 %d건은 다음 실행에서", OVERVIEW_MINUTES, len(queue) - start)
                    break
                jobs = []  # (접수번호, 프롬프트)
                for rcept_no, name, report_nm in queue[start:start + slots.size]:
                    cur.execute("""SELECT node_id, parent_id, seq, level, title, path, blocks FROM report_nodes
                                   WHERE rcept_no = %s ORDER BY seq""", (rcept_no,))
                    nodes = [Node(r[0], r[1], r[2], r[3], r[4], r[5], [Block.from_json(b) for b in json.loads(r[6])])
                             for r in cur.fetchall()]
                    source = overview_source(overview_entries(nodes), {n.node_id: n.blocks for n in nodes})
                    if source:
                        jobs.append((rcept_no, overview_prompt(name, report_nm, source)))
                    else:
                        log.info("%s %s: 사업의 내용을 찾지 못해 개요를 건너뜁니다", name, report_nm)
                results = list(pool.map(lambda job: slots.call(_overview, job[1]), jobs))
                done = [(text, model, rcept_no) for (rcept_no, _), (text, model) in zip(jobs, results) if text]
                # 그사이 챗봇이 만들었으면 그것을 둔다
                execute_batch(cur, "UPDATE stock_reports SET overview = %s, model = %s WHERE rcept_no = %s AND overview IS NULL",
                              done)
                conn.commit()
                made += len(done)
                failed += len(jobs) - len(done)
    finally:
        cur.close()
        conn.close()
    log.info("report overviews: %d건 만듦, 실패 %d건 (다음 실행에서 다시)", made, failed)


t_queue = PythonOperator(task_id='queue_reports', python_callable=queue_reports, dag=dag)
t_trees = PythonOperator(task_id='build_trees', python_callable=build_trees, dag=dag,
                         execution_timeout=timedelta(minutes=BUILD_MINUTES + 30))
t_summaries = PythonOperator(task_id='summarize_nodes', python_callable=summarize_nodes, dag=dag,
                             execution_timeout=timedelta(minutes=SUMMARY_MINUTES + 30))
t_prune = PythonOperator(task_id='prune_reports', python_callable=prune_reports, dag=dag)
t_overviews = PythonOperator(task_id='make_overviews', python_callable=make_overviews, dag=dag,
                             execution_timeout=timedelta(minutes=OVERVIEW_MINUTES + 30))

t_queue >> t_trees >> t_summaries >> t_prune >> t_overviews
