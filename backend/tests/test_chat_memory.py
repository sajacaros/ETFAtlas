from types import SimpleNamespace

import pytest

from app.services.chat_memory import ChatMemory, ConversationContext, Turn


class FakeDB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _memory(logs, reply="", window=5):
    """DB·LLM 없이 ChatMemory를 만든다. logs는 세션의 전체 로그(id 오름차순)."""
    mem = ChatMemory.__new__(ChatMemory)
    mem.db = FakeDB()
    mem.window = window
    mem.calls = []
    mem._session_logs = lambda session, after_id=0: [log for log in logs if log.id > after_id]

    def complete(system, user, max_tokens):
        mem.calls.append(user)
        if isinstance(reply, Exception):
            raise reply
        return reply
    mem._complete = complete
    return mem


def _logs(n):
    return [SimpleNamespace(id=i, question=f"질문{i}", refined_question=None, answer=f"답변{i}") for i in range(1, n + 1)]


def _session(**kw):
    return SimpleNamespace(id=1, summary=None, summarized_until_log_id=None, **kw)


def test_summary_skipped_within_window():
    mem = _memory(_logs(5), reply="요약")
    session = _session()
    assert mem.update_summary(session) is False
    assert mem.calls == [] and session.summary is None


def test_summary_folds_turns_outside_window():
    mem = _memory(_logs(7), reply="- 요약")
    session = _session()
    assert mem.update_summary(session) is True
    assert session.summary == "- 요약" and session.summarized_until_log_id == 2
    assert "질문1" in mem.calls[0] and "질문2" in mem.calls[0] and "질문3" not in mem.calls[0]

    # 다음 턴: 이미 요약한 1~2는 빼고 새로 밀려난 3만 기존 요약과 합친다
    mem2 = _memory(_logs(8), reply="- 새 요약")
    assert mem2.update_summary(session) is True
    assert session.summarized_until_log_id == 3
    assert "- 요약" in mem2.calls[0] and "질문2" not in mem2.calls[0] and "질문3" in mem2.calls[0]


def test_summary_failure_keeps_pending_turns():
    mem = _memory(_logs(7), reply=RuntimeError("llm down"))
    session = _session()
    assert mem.update_summary(session) is False
    assert session.summarized_until_log_id is None and mem.db.commits == 0


def test_refine_skips_llm_without_context():
    mem = _memory([], reply="바뀐 질문")
    assert mem.refine("보수율은?", ConversationContext()) == "보수율은?"
    assert mem.calls == []


CONTEXT = ConversationContext(summary="- KODEX 200(069500) 조회", turns=[Turn("KODEX 200 정보", "보수율 0.15%")])


@pytest.mark.parametrize("reply,expected", [
    ("KODEX 200(069500)의 보수율은?", "KODEX 200(069500)의 보수율은?"),
    ('출력: "KODEX 200(069500)의 보수율은?"', "KODEX 200(069500)의 보수율은?"),
    ("", "보수율은?"),                               # 빈 응답
    ("KODEX 200의 보수율은 0.15%입니다.\n추가로…", "보수율은?"),  # 답변을 늘어놓음
    (RuntimeError("llm down"), "보수율은?"),
])
def test_refine_sanitizes_output(reply, expected):
    mem = _memory([], reply=reply)
    assert mem.refine("보수율은?", CONTEXT) == expected
    assert "KODEX 200(069500) 조회" in mem.calls[0]


def test_context_render_uses_refined_question_and_clips_answer():
    from app.services.chat_memory import _turn
    log = SimpleNamespace(question="그거 보수율은?", refined_question="KODEX 200의 보수율은?", answer="x" * 3000)
    text = ConversationContext(turns=[_turn(log)]).render()
    assert "KODEX 200의 보수율은?" in text and "그거" not in text
    assert "(생략)" in text and len(text) < 2000
