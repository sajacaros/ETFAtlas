"""Cypher 파라미터를 리터럴로 바꿔 끼우는 순수 함수. backend와 airflow가 함께 쓴다.

AGE의 cypher()는 세 번째 인자로 prepared statement 파라미터만 받으므로, 쿼리를 그대로 실행하는
이 프로젝트는 값을 리터럴로 치환한다. 치환은 여기 한 곳에서만 한다.
"""
import math
import re
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

_PARAM_RE = re.compile(r"\$([A-Za-z_]\w*)")
_KEY_RE = re.compile(r"[A-Za-z_]\w*")


def literal(value: Any) -> str:
    """파이썬 값을 Cypher 리터럴로. 문자열은 백슬래시부터 이스케이프해야 따옴표 이스케이프를 무력화할 수 없다."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return "null" if not math.isfinite(value) else str(value)
    if isinstance(value, date):
        value = value.isoformat()  # 그래프의 날짜 키는 'YYYY-MM-DD' 문자열
    if isinstance(value, (list, tuple, set, frozenset)):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{_key(k)}: {literal(v)}" for k, v in value.items()) + "}"
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    # cypher()를 감싼 $$ 인용이 끊기지 않게
    return "'" + escaped.replace("$$", "$ $") + "'"


def _key(key: Any) -> str:
    key = str(key)
    if not _KEY_RE.fullmatch(key):
        raise ValueError(f"맵 키는 식별자여야 합니다: {key!r}")
    return key


def bind(query: str, params: Mapping[str, Any] | None) -> str:
    """$name 자리를 한 번에 치환한다. 이미 넣은 값 안의 $다른키는 다시 치환되지 않고, $code가 $code_name을 건드리지 않는다."""
    if params:
        query = _PARAM_RE.sub(lambda m: literal(params[m[1]]) if m[1] in params else m[0], query)
    if "$$" in query:
        raise ValueError("Cypher query must not contain '$$'")
    return query
