"""chat_reviewer: 규칙 신호와 보내다 끊긴 점검의 이어 보내기."""
import chat_reviewer
from chat_reviewer import Issue
from fakes import FakeConn, FakeCursor


def _turn(i, session=1, result='completed', skill='rank', question='질문'):
    return {'id': i, 'session_id': session, 'question': question, 'refined': None, 'answer': '답', 'result': result,
            'feedback': None, 'slots': [{'id': 's1', 'skill': skill, 'status': 'complete', 'message': None,
                                          'summary': None, 'title': '', 'display': 'table'}], 'agent_errors': []}


def test_rule_signals():
    signals = chat_reviewer.rule_signals([_turn(1, result='failed'), _turn(2, skill='agent'), _turn(3)])
    assert signals[1][0] == "답변 failed"
    assert "같은 질문인데 구성 다름" in signals[2]


def test_notice_items_round_trip_and_old_records():
    issue = Issue(log_id=1, cause='routing', problem='p', suggestion='s', skills=['rank'])
    items = chat_reviewer.notice_items([issue], [7])
    assert chat_reviewer.issues_from_items(items) == ([issue], [7])
    assert chat_reviewer.issues_from_items([issue.model_dump()]) == ([issue], [])


def test_run_review_resumes_from_the_recorded_review(monkeypatch):
    issue = Issue(log_id=1, cause='skill', problem='p' * 1500, suggestion='s' * 1500)
    cur = FakeCursor({
        "FROM discord_settings": [(True, "https://hook", 3.0, 2.0, 3.0)],
        "status = 'sent' LIMIT 1": [],
        "SELECT status, message_count, items": [("failed", 1, chat_reviewer.notice_items([issue], []))],
    })
    conn = FakeConn(cur)
    monkeypatch.setattr(chat_reviewer, "connection", lambda: _Ctx(conn))
    monkeypatch.setattr(chat_reviewer, "collect_turns", lambda c, d: [_turn(1)])
    monkeypatch.setattr(chat_reviewer, "review_turns", lambda *a: (_ for _ in ()).throw(AssertionError("LLM called")))
    sent = []
    monkeypatch.setattr(chat_reviewer, "deliver", lambda conn, url, kind, d, th, items, messages, start: sent.append(
        (kind, len(messages), start, items)))
    chat_reviewer.run_review("2026-10-30")
    kind, total, start, items = sent[0]
    assert kind == 'chat_review' and total > 1 and start == 1
    assert items['issues'][0]['log_id'] == 1


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
