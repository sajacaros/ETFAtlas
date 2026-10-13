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
