"""discord_notice: 메시지 나누기, 보내다 끊긴 발송 이어 보내기, 비중변화 알림 묶기."""
import pytest

import discord_notice
from discord_notice import split_messages
from fakes import FakeConn, FakeCursor


def test_split_messages_keeps_one_message_when_it_fits():
    assert split_messages("H", ["a", "b"]) == ["H\n\na\n\nb"]


def test_split_messages_pages_and_limits_every_message():
    blocks = [f"**ETF{i}**\n" + "\n".join(f"  line {j} " + "x" * 50 for j in range(10)) for i in range(20)]
    messages = split_messages("📊 header", blocks, limit=2000)
    assert len(messages) > 1
    assert all(len(m) <= 2000 for m in messages)
    assert messages[0].startswith(f"📊 header (1/{len(messages)})")
    # 블록은 쪼개지 않는다
    joined = "\n\n".join(m.split("\n\n", 1)[1] for m in messages)
    assert joined == "\n\n".join(blocks)


def test_split_messages_breaks_a_block_too_long_by_lines():
    block = "**긴 ETF**\n" + "\n".join("  " + "y" * 100 for _ in range(40))
    messages = split_messages("H", [block], limit=1000)
    assert all(len(m) <= 1000 for m in messages)
    assert "**긴 ETF** (계속)" in messages[1]


def test_resume_start_skips_what_was_sent():
    assert discord_notice.resume_start(None, ["a", "b", "c"]) == 0
    assert discord_notice.resume_start({'sent': 2, 'items': []}, ["a", "b", "c"]) == 2
    # 예전 기록(message_count = 전체 수)이면 처음부터
    assert discord_notice.resume_start({'sent': 3, 'items': []}, ["a", "b", "c"]) == 0


def test_interrupted_send_reads_only_a_failed_last_attempt():
    conn = FakeConn(FakeCursor({"discord_notification_logs": [("failed", 2, {"rising": []})]}))
    assert discord_notice.interrupted_send(conn, 'daily_report', '2026-10-30') == {'sent': 2, 'items': {"rising": []}}
    assert discord_notice.interrupted_send(
        FakeConn(FakeCursor({"discord_notification_logs": [("failed", 0, [])]})), 'x', 'd') is None
    assert discord_notice.interrupted_send(
        FakeConn(FakeCursor({"discord_notification_logs": [("sent", 3, [])]})), 'x', 'd') is None


def test_deliver_records_how_many_went_out_and_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(discord_notice, "post_messages",
                        lambda url, messages, start: calls.append(start) or (start + 1, "HTTPStatusError status=500"))
    conn = FakeConn()
    with pytest.raises(RuntimeError, match="status=500"):
        discord_notice.deliver(conn, "https://hook", 'weight_change', '2026-10-30', 3.0, [], ["a", "b", "c"], start=1)
    assert calls == [1]
    sql, params = conn.cur.sql[-1]
    assert sql.startswith("INSERT INTO discord_notification_logs")
    assert params[2] == 'failed' and params[5] == 2  # 앞의 1개 + 이번에 1개


def test_deliver_records_the_full_count_on_success(monkeypatch):
    monkeypatch.setattr(discord_notice, "post_messages", lambda url, messages, start: (len(messages), None))
    conn = FakeConn()
    discord_notice.deliver(conn, "https://hook", 'daily_report', '2026-10-30', 3.0, {}, ["a", "b"], start=1)
    params = conn.cur.sql[-1][1]
    assert params[2] == 'sent' and params[5] == 2 and params[0] == 'daily_report'


def test_load_discord_settings_prefers_the_db_and_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://env-hook")
    conn = FakeConn(FakeCursor({"discord_settings": [(True, "", 4.0, 2.5, 3.0)]}))
    s = discord_notice.load_discord_settings(conn)
    assert s['webhook_url'] == "https://env-hook" and s['threshold'] == 4.0
    off = discord_notice.load_discord_settings(FakeConn(FakeCursor({"discord_settings": [(False, "https://db", 1, 1, 1)]})))
    assert off['enabled'] is False and off['webhook_url'] is None


def test_group_weight_changes_and_blocks():
    rows = [("A", "에이", "2026-10-29", "005930", "삼성전자", "increased", 10.0, 15.0, 5.0),
            ("B", "비", "2026-10-29", "000660", "SK하이닉스", "added", 0, 4.0, 4.0),
            ("A", "에이", "2026-10-29", "035420", "NAVER", "removed", 3.5, 0, -3.5)]
    items = discord_notice.group_weight_changes(rows)
    assert [i['etf_code'] for i in items] == ["A", "B"]
    assert [c['stock_code'] for c in items[0]['changes']] == ["005930", "035420"]
    blocks = discord_notice.weight_change_blocks(items)
    assert blocks[0] == ("**에이** (A)\n  증가 삼성전자: 10.0% → 15.0% (+5.0%p)\n"
                         "  편출 NAVER: 3.5% → 0.0% (-3.5%p)")


def test_send_discord_notification_resumes_after_the_sent_messages(monkeypatch):
    rows = [(f"E{i}", f"ETF {i}", "2026-10-29", f"{j:06d}", f"종목{j}", "increased", 1.0, 9.0, 8.0)
            for i in range(30) for j in range(8)]
    cur = FakeCursor({
        "FROM discord_settings": [(True, "https://hook", 3.0, 2.0, 3.0)],
        "SELECT items FROM discord_notification_logs": [],
        "SELECT status, message_count, items": [("failed", 1, [])],
        "FROM weight_changes WHERE base_date": rows,
    })
    monkeypatch.setattr(discord_notice, "connection", lambda: _Ctx(FakeConn(cur)))
    sent = []
    monkeypatch.setattr(discord_notice, "post_messages",
                        lambda url, messages, start: sent.append((len(messages), start)) or (len(messages), None))
    discord_notice.send_discord_notification("2026-10-30")
    total, start = sent[0]
    assert total > 1 and start == 1
    assert cur.sql[-1][1][2] == 'sent' and cur.sql[-1][1][5] == total


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
