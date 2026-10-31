"""move few-shot examples off the removed agent tools

The agent no longer has get_etf_info, get_etf_prices, get_stock_prices and
compare_etfs; the skill tools etf_compare, price_trend and stock_trend do that
work now. Examples that still call the old tools are dropped from the prompt, so
this rewrites code_examples.code and chat_logs.generated_code (the source of
future examples) to the new calls.

Rows that are exactly an old seed example get the hand-written new seed text
(docker/db/seed/code_examples.py). Anything else (examples approved from chat
logs) is converted call by call; a line that cannot be converted is left as is
and logged. The question and its embedding do not change.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-31 20:00:00.000000
"""
import ast
import logging
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0040'
down_revision: Union[str, Sequence[str], None] = '0039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

OLD_TOOLS = ("get_etf_info", "get_etf_prices", "get_stock_prices", "compare_etfs")
OLD_CALL = re.compile(r"\b(" + "|".join(OLD_TOOLS) + r")\(")
SQL_PATTERN = "(" + "|".join(OLD_TOOLS) + ")\\("  # Postgres 정규식 (\b는 백스페이스라 쓰지 않는다)

# 이 리비전 시점의 시드 예시 (옛 code → 새 code·description)
SEED_REWRITES = [{'old': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'반도체\'}) RETURN {code: e.code, name: e.name, '
         'net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1m")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'반도체\'}) RETURN {code: e.code, name: e.name, '
         'net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 3")\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>"], period="1m")',
  'description': '태그 → 순자산 상위 N개 → price_trend 한 번에 (ETF 5개까지)'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN [\'고배당\', \'반도체\'] WITH t, e ORDER BY '
         'e.net_assets DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name}")\n'
         'compare_etfs(etf_codes="<고배당 ETF의 code>,<반도체 ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN [\'고배당\', \'반도체\'] WITH t, e ORDER BY '
         'e.net_assets DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name}")\n'
         'etf_compare(etfs=["<고배당 ETF의 code>", "<반도체 ETF의 code>"])',
  'description': '태그별 대표 ETF 1개씩 → etf_compare'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN [\'바이오\', \'금융\'] AND e.return_1m IS '
         'NOT NULL WITH t, e ORDER BY e.return_1m DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: '
         'top.code, name: top.name, return_1m: top.return_1m}")\n'
         'compare_etfs(etf_codes="<바이오 ETF의 code>,<금융 ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN [\'바이오\', \'금융\'] AND e.return_1m IS '
         'NOT NULL WITH t, e ORDER BY e.return_1m DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: '
         'top.code, name: top.name, return_1m: top.return_1m}")\n'
         'etf_compare(etfs=["<바이오 ETF의 code>", "<금융 ETF의 code>"])',
  'description': '태그별 1개월 수익률 1위 → etf_compare'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'방산\'}) RETURN {code: e.code, name: e.name} ORDER '
         'BY e.net_assets DESC")\n'
         '# 결과 ETF마다\n'
         'get_etf_info(etf_code="<ETF의 code>")\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1m")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'방산\'}) RETURN {code: e.code, name: e.name} ORDER '
         'BY e.net_assets DESC")\n'
         '# 결과 ETF를 5개씩 나눠\n'
         'etf_compare(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>", "<ETF4의 code>", "<ETF5의 code>"])\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>", "<ETF4의 code>", "<ETF5의 code>"], '
         'period="1m")',
  'description': '태그 ETF 전체 → 5개씩 etf_compare(기본 정보) + price_trend(가격)'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) RETURN {code: e.code, name: '
         'e.name, weight: h.weight, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'get_etf_info(etf_code="<ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) RETURN {code: e.code, name: '
         'e.name, weight: h.weight, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")\n'
         'etf_compare(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>"])',
  'description': '종목 이름으로 보유 ETF(CURRENT_HOLDS) → 보수율순 → etf_compare로 상세'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN [\'<종목명1>\', \'<종목명2>\'] WITH '
         'e, count(s) AS matched, sum(h.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, '
         'weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'get_etf_info(etf_code="<ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN [\'<종목명1>\', \'<종목명2>\'] WITH '
         'e, count(s) AS matched, sum(h.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, '
         'weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")\n'
         'etf_compare(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>"])',
  'description': '여러 종목 동시 보유(matched = 종목 수) → 보수율순 → etf_compare로 상세'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) WHERE e.return_1m IS NOT '
         'NULL RETURN {code: e.code, name: e.name, weight: h.weight, return_1m: e.return_1m} ORDER BY e.return_1m DESC '
         'LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1m")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) WHERE e.return_1m IS NOT '
         'NULL RETURN {code: e.code, name: e.name, weight: h.weight, return_1m: e.return_1m} ORDER BY e.return_1m DESC '
         'LIMIT 3")\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>"], period="1m")',
  'description': '종목 보유 ETF → 수익률순 → price_trend 한 번에'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) RETURN {stock_code: s.code, '
         'code: e.code, name: e.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 3")\n'
         'get_stock_prices(stock_code="<결과의 stock_code>", period="1m")\n'
         '# 결과 ETF마다\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1m")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: \'<종목명>\'}) RETURN {code: e.code, name: '
         'e.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 3")\n'
         'stock_trend(stocks=["<종목명>"], period="1m")\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>"], period="1m")',
  'description': '보유 비중 상위 ETF → stock_trend(종목 가격) + price_trend(ETF 가격), 같은 기간'},
 {'old': 'stock_search(query="<종목명>")\n'
         'get_stock_prices(stock_code="<종목의 code>", period="1m")\n'
         'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'반도체\'}) RETURN {code: e.code, name: e.name, '
         'return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.net_assets DESC LIMIT 5")',
  'new': 'stock_trend(stocks=["<종목명>"], period="1m")\n'
         'graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: \'반도체\'}) RETURN {code: e.code, name: e.name, '
         'return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.net_assets DESC LIMIT 5")',
  'description': 'stock_trend(종목 가격, 이름 그대로) + 태그 ETF 수익률'},
 {'old': 'etf_search(query="<ETF명>")\n'
         'find_similar_etfs(etf_code="<ETF의 code>")\n'
         'compare_etfs(etf_codes="<유사 ETF 5개의 code, 쉼표 구분>")',
  'new': 'etf_search(query="<ETF명>")\n'
         'find_similar_etfs(etf_code="<ETF의 code>")\n'
         'etf_compare(etfs=["<유사 ETF1의 code>", "<유사 ETF2의 code>", "<유사 ETF3의 code>", "<유사 ETF4의 code>", "<유사 ETF5의 '
         'code>"])',
  'description': 'ETF 코드 확인 → 유사 ETF → etf_compare (5개까지)'},
 {'old': 'graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL RETURN {code: e.code, name: e.name, '
         'return_1w: e.return_1w} ORDER BY e.return_1w DESC LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'get_etf_info(etf_code="<ETF의 code>")\n'
         'find_similar_etfs(etf_code="<ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL RETURN {code: e.code, name: e.name, '
         'return_1w: e.return_1w} ORDER BY e.return_1w DESC LIMIT 3")\n'
         '# 결과 ETF마다\n'
         'holdings(etf="<ETF의 code>")\n'
         'find_similar_etfs(etf_code="<ETF의 code>")',
  'description': '수익률 상위 ETF → ETF별 holdings(보유종목) + 유사 ETF'},
 {'old': 'graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY '
         'e.net_assets DESC LIMIT 5")\n'
         '# 결과 ETF마다\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1w")\n'
         'get_holdings_changes(etf_code="<ETF의 code>", period="1w")',
  'new': 'graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY '
         'e.net_assets DESC LIMIT 5")\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>", "<ETF4의 code>", "<ETF5의 code>"], '
         'period="1w")\n'
         '# 결과 ETF마다\n'
         'get_holdings_changes(etf_code="<ETF의 code>", period="1w")',
  'description': '순자산순 → price_trend 한 번에 + ETF별 보유종목 변동'},
 {'old': 'graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH \'TIGER\' AND e.expense_ratio <= 0.1 RETURN '
         '{code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC")\n'
         '# 결과 ETF마다\n'
         'get_etf_prices(etf_code="<ETF의 code>", period="1m")',
  'new': 'graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH \'TIGER\' AND e.expense_ratio <= 0.1 RETURN '
         '{code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC")\n'
         '# 결과 ETF를 5개씩 나눠\n'
         'price_trend(etfs=["<ETF1의 code>", "<ETF2의 code>", "<ETF3의 code>", "<ETF4의 code>", "<ETF5의 code>"], '
         'period="1m")',
  'description': '브랜드 + 보수율 조건 → price_trend (5개씩)'},
 {'old': 'graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: \'<운용사>\'}) WHERE e.return_1m IS NOT NULL '
         'RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 5")\n'
         '# 결과 ETF마다\n'
         'get_etf_info(etf_code="<ETF의 code>")',
  'new': 'graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: \'<운용사>\'}) WHERE e.return_1m IS NOT NULL '
         'RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 5")\n'
         '# 결과 ETF마다\n'
         'holdings(etf="<ETF의 code>")',
  'description': '운용사 → 수익률순 → ETF별 holdings(보유종목)'}]


def _call(name: str, **kwargs) -> str:
    return f"{name}(" + ", ".join(f"{k}={_literal(v)}" for k, v in kwargs.items()) + ")"


def _literal(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _codes(value: str) -> list:
    """compare_etfs의 쉼표 구분 코드 → 목록. <…, 쉼표 구분> 같은 자리표시자 하나는 통째로 둔다."""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return [value]
    return [v.strip() for v in value.split(",") if v.strip()]


def convert_line(line: str) -> str:
    """옛 도구 호출 한 줄을 새 호출로. 바꿀 수 없으면 ValueError."""
    stripped = line.strip()
    if not OLD_CALL.match(stripped):
        return line
    call = ast.parse(stripped, mode="eval").body
    if not isinstance(call, ast.Call) or call.args:
        raise ValueError(line)
    kw = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    name = call.func.id
    period = {"period": kw["period"]} if "period" in kw else {}
    if name == "get_etf_info" and set(kw) == {"etf_code"}:
        new = _call("etf_compare", etfs=[kw["etf_code"]])
    elif name == "get_etf_prices" and set(kw) <= {"etf_code", "period"} and "etf_code" in kw:
        new = _call("price_trend", etfs=[kw["etf_code"]], **period)
    elif name == "get_stock_prices" and set(kw) <= {"stock_code", "period"} and "stock_code" in kw:
        new = _call("stock_trend", stocks=[kw["stock_code"]], **period)
    elif name == "compare_etfs" and set(kw) == {"etf_codes"}:
        new = _call("etf_compare", etfs=_codes(kw["etf_codes"]))
    else:
        raise ValueError(line)
    return line[: len(line) - len(line.lstrip())] + new


def convert_code(code: str) -> str:
    return "\n".join(convert_line(line) for line in code.split("\n"))


def _rewrite(conn, table: str, column: str, extra: str = "") -> None:
    rows = conn.execute(sa.text(
        f"SELECT id, {column} FROM {table} WHERE {column} ~ :pattern {extra}"
    ), {"pattern": SQL_PATTERN}).fetchall()
    seed = {r["old"]: r for r in SEED_REWRITES}
    for row_id, code in rows:
        if code in seed and table == "code_examples":
            conn.execute(sa.text("UPDATE code_examples SET code = :code, description = :description WHERE id = :id"),
                         {"code": seed[code]["new"], "description": seed[code]["description"], "id": row_id})
            continue
        try:
            new = convert_code(code)
        except (ValueError, SyntaxError) as e:
            logger.warning("%s.%s id=%s left as is (cannot convert %r)", table, column, row_id, str(e)[:120])
            continue
        conn.execute(sa.text(f"UPDATE {table} SET {column} = :code WHERE id = :id"), {"code": new, "id": row_id})
    logger.info("%s.%s: %d rows used removed tools", table, column, len(rows))


def upgrade() -> None:
    conn = op.get_bind()
    _rewrite(conn, "code_examples", "code")
    _rewrite(conn, "chat_logs", "generated_code")


def downgrade() -> None:
    # 옛 도구가 없어졌으므로 되돌리지 않는다
    pass
