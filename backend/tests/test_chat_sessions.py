from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers.chat import parse_session_cursor, session_cursor


def test_session_cursor_round_trips_time_and_id():
    session = SimpleNamespace(updated_at=datetime(2026, 10, 13, 8, 59, 27, 599396), id=123)
    assert parse_session_cursor(session_cursor(session)) == (session.updated_at, 123)


@pytest.mark.parametrize("cursor", ["", "abc", "2026-10-13T08:59:27_x", "nope_12"])
def test_session_cursor_rejects_garbage(cursor):
    with pytest.raises(HTTPException) as e:
        parse_session_cursor(cursor)
    assert e.value.status_code == 400


def test_chat_log_ownership_is_checked_in_one_place():
    from app.routers.chat import _own_log

    class Query:
        def __init__(self, log):
            self.log = log

        def filter(self, *conditions):
            return self

        def first(self):
            return self.log

    class DB:
        def __init__(self, log):
            self.log = log

        def query(self, model):
            return Query(self.log)

    log = SimpleNamespace(id=3, user_id=1)
    assert _own_log(DB(log), 1, 3) is log
    for db, user, code in ((DB(None), 1, 404), (DB(log), 2, 403)):
        with pytest.raises(HTTPException) as e:
            _own_log(db, user, 3)
        assert e.value.status_code == code


def test_sse_event_is_one_json_data_line():
    from app.utils.sse import DONE, sse_event
    assert sse_event({"type": "session", "data": {"title": "삼성"}}) == 'data: {"type": "session", "data": {"title": "삼성"}}\n\n'
    assert DONE == "data: [DONE]\n\n"
