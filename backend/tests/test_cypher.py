from datetime import date
from decimal import Decimal

import pytest

from app.utils.cypher import bind, literal


def test_backslash_cannot_break_out_of_string():
    # 예전 치환은 '만 이스케이프해서 이 입력이 문자열을 닫고 OR true를 끼워 넣었다
    query = bind("MATCH (e:ETF) WHERE e.name CONTAINS $q RETURN e", {"q": "zzz\\' OR true //"})
    assert query == "MATCH (e:ETF) WHERE e.name CONTAINS 'zzz\\\\\\' OR true //' RETURN e"


def test_dollar_quote_in_value_is_neutralized():
    query = bind("RETURN $q", {"q": "x$$) as (r agtype); SELECT 1; --"})
    assert "$$" not in query


def test_dollar_quote_in_query_is_rejected():
    with pytest.raises(ValueError):
        bind("RETURN 1 $$", {})


def test_substitutes_once_and_respects_word_boundary():
    query = bind("RETURN [$code, $code_name]", {"code": "$code_name", "code_name": "A"})
    assert query == "RETURN ['$code_name', 'A']"


def test_unknown_placeholders_are_left_alone():
    assert bind("RETURN $missing", {"other": 1}) == "RETURN $missing"


def test_literal_types():
    assert literal(None) == "null"
    assert literal(True) == "true"
    assert literal(3) == "3"
    assert literal(Decimal("1.50")) == "1.50"
    assert literal(float("nan")) == "null"
    assert literal(date(2026, 10, 31)) == "'2026-10-31'"
    assert literal(["069500", "a'b"]) == "['069500', 'a\\'b']"
    assert literal({"code": "A", "w": [1, None]}) == "{code: 'A', w: [1, null]}"


def test_map_keys_must_be_identifiers():
    with pytest.raises(ValueError):
        literal({"a}) RETURN 1 //": 1})
