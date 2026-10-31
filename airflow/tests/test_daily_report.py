"""daily_report: 상위 구성종목 수익률과 보내다 끊긴 리포트 이어 보내기."""
import daily_report
from fakes import FakeConn, FakeCursor


def test_top_holdings_with_returns():
    rows = [{'code': 'S1', 'name': '일', 'weight': 10, 'date': '2026-10-29', 'close': 100},
            {'code': 'S1', 'name': '일', 'weight': 10, 'date': '2026-10-30', 'close': 110},
            {'code': 'S2', 'name': None, 'weight': 20, 'date': None, 'close': None}]
    assert daily_report.top_holdings_with_returns(rows, '2026-10-30') == [
        {'stock_code': 'S2', 'stock_name': 'S2', 'weight': 20, 'return_1d': None},
        {'stock_code': 'S1', 'stock_name': '일', 'weight': 10, 'return_1d': 10.0}]


def test_features_prompt_limits_the_etfs():
    rising = [{'etf_name': f'E{i}', 'return_1d': 5.0, 'holdings': []} for i in range(daily_report.REPORT_LLM_MAX_ETFS + 5)]
    lines = daily_report.features_prompt(rising, 1.234).splitlines()
    assert lines[0] == "시장(KODEX 200) +1.23%"
    assert lines[1] == f"상승 ETF {len(rising)}개 (많이 오른 {daily_report.REPORT_LLM_MAX_ETFS}개만)"
    assert len(lines) == 2 + daily_report.REPORT_LLM_MAX_ETFS


def test_send_daily_report_resumes_with_the_recorded_report(monkeypatch):
    report = {'rising': [{'etf_code': f'{i:06d}', 'etf_name': 'x' * 150, 'return_1d': 9.0} for i in range(12)],
              'market_return': 1.0, 'features': ['f' * 1900]}
    cur = FakeCursor({
        "FROM discord_settings": [(True, "https://hook", 3.0, 2.0, 3.0)],
        "status = 'sent' LIMIT 1": [],
        "SELECT status, message_count, items": [("failed", 1, report)],
    })
    monkeypatch.setattr(daily_report, "connection", lambda: _Ctx(FakeConn(cur)))
    monkeypatch.setattr(daily_report, "collect_daily_report", lambda *a: (_ for _ in ()).throw(AssertionError("recollected")))
    sent = []
    monkeypatch.setattr(daily_report, "deliver", lambda conn, url, kind, d, th, items, messages, start, failure: sent.append(
        (kind, len(messages), start, items)))
    daily_report.send_daily_report("2026-10-30", [])
    kind, total, start, items = sent[0]
    assert kind == 'daily_report' and total == 2 and start == 1 and items is report


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
