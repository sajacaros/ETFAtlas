"""age_db: Cypher 실행이 값을 app.utils.cypher로 끼워 넣는지."""
import age_db
from fakes import FakeCursor


def test_execute_cypher_escapes_values_and_wraps_the_query():
    cur = FakeCursor()
    age_db.execute_cypher(cur, "MATCH (e:ETF {code: $code}) RETURN e", {'code': "x' OR true //"})
    sql = cur.sql[0][0]
    assert sql.startswith("SELECT * FROM cypher('etf_graph', $$")
    assert "{code: 'x\\' OR true //'}" in sql


def test_execute_cypher_neutralizes_dollar_quotes():
    cur = FakeCursor()
    age_db.execute_cypher(cur, "RETURN $v", {'v': "a$$) as (r agtype); DROP TABLE etfs; --"})
    assert cur.sql[0][0].count("$$") == 2


def test_batch_unwinds_items_and_does_not_rebind_values():
    cur = FakeCursor()
    items = [{'code': str(i), 'name': '$today'} for i in range(250)]
    age_db.execute_cypher_batch(cur, "MATCH (e:ETF {code: item.code}) SET e.d = $today RETURN 1", items,
                                params={'today': '2026-10-31'})
    assert len(cur.sql) == 3  # 100개씩
    first = cur.sql[0][0]
    assert first.count("name: '$today'") == 100
    assert "SET e.d = '2026-10-31'" in first


def test_batch_with_no_items_runs_nothing():
    cur = FakeCursor()
    assert age_db.execute_cypher_batch(cur, "RETURN 1", []) == []
    assert cur.sql == []


def test_parse_age_value_and_fetch_helpers():
    assert age_db.parse_age_value('"069500"') == "069500"
    assert age_db.parse_age_value('12.5::numeric') == "12.5"
    cur = FakeCursor({"cypher": [('"A"',), (None,), ('""',), ('"B"',)]})
    assert age_db.fetch_values(cur, "MATCH (e:ETF) RETURN e.code") == ["A", "B"]
    cur = FakeCursor({"cypher": [('{"code": "A", "w": 1.5::numeric}',), (None,)]})
    assert age_db.fetch_maps(cur, "RETURN {code: 'A'}") == [{"code": "A", "w": 1.5}]


def test_price_keys_split_code_and_date():
    cur = FakeCursor({"cypher": [('"069500|2026-10-30"',), ('"bad"',)]})
    keys = age_db.fetch_price_keys(cur, 'ETF', '2026-10-01', '2026-10-30')
    assert keys == {("069500", "2026-10-30")}
    assert "p.date >= '2026-10-01'" in cur.sql[0][0]


def test_lookup_helpers_reuse_the_given_cursor(monkeypatch):
    monkeypatch.setattr(age_db, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("new connection")))
    cur = FakeCursor({"cypher": [('"069500"',)]})
    assert age_db.get_etf_codes_from_age(cur) == {"069500"}
    assert age_db.get_stock_codes_from_age(cur, exclude_etfs=True) == {"069500"}
    assert "s.is_etf = false" in cur.sql[-1][0]
