"""dart_report_index: 요약 서버 목록과 자리 배분."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

AI = {"llm_api_base": "http://gateway/v1", "llm_api_key": "k", "llm_model": "dukim-llm"}


def test_summary_endpoints_add_extra_servers():
    mod = pytest.importorskip("dart_report_index")  # airflow 필요
    assert mod.summary_endpoints(AI, extra="") == [
        {"base_url": "http://gateway/v1", "api_key": "k", "model": "dukim-llm", "workers": mod.SUMMARY_WORKERS}]
    extra = mod.summary_endpoints(
        AI, extra='[{"base_url": "http://gpu:7900/qwen38/v1", "model": "qwen38-27b", "workers": 12}]')[1]
    assert extra == {"base_url": "http://gpu:7900/qwen38/v1", "api_key": "EMPTY", "model": "qwen38-27b", "workers": 12}


def test_summary_slots_never_exceed_each_servers_workers(monkeypatch):
    mod = pytest.importorskip("dart_report_index")
    active, peak, lock = {}, {}, threading.Lock()

    class FakeOpenAI:
        def __init__(self, base_url, api_key, **kwargs):
            self.base_url = base_url

    def fake_summarize(client, model, node):
        with lock:
            active[model] = active.get(model, 0) + 1
            peak[model] = max(peak.get(model, 0), active[model])
        time.sleep(0.01 if model == "fast" else 0.03)
        with lock:
            active[model] -= 1
        return f"{node} 요약"

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(mod, "_summarize", fake_summarize)
    slots = mod.SummarySlots([{"base_url": "a", "api_key": "k", "model": "slow", "workers": 2},
                              {"base_url": "b", "api_key": "k", "model": "fast", "workers": 3}])
    assert slots.size == 5
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(slots.size) as pool:
        results = list(pool.map(slots.summarize, range(60)))
    assert [s for s, _ in results] == [f"{i} 요약" for i in range(60)]
    assert peak == {"slow": 2, "fast": 3}
    counts = {m: sum(1 for _, x in results if x == m) for m in ("slow", "fast")}
    assert counts["fast"] > counts["slow"]  # 빠른 서버가 더 많이 맡는다


class FakeCursor:
    def __init__(self, queue, corp):
        self.queue, self.corp, self.sql, self._rows = queue, corp, [], []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        if "FROM stock_reports" in sql and "SELECT r.rcept_no" in sql:
            self._rows = self.queue
        elif "FROM dart_corps" in sql:
            self._rows = [(self.corp,)]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_build_trees_marks_filings_without_a_document_missing_and_fetches_the_period(monkeypatch):
    mod = pytest.importorskip("dart_report_index")
    import dart_sync_rdb
    from dart_client import DartError

    calls = []

    class FakeDart:
        def document(self, rcept_no):
            raise DartError('document.xml: <?xml version="1.0"?><result><status>014</status>'
                            '<message>파일이 존재하지 않습니다.</message></result>')

        def disclosures(self, bgn, end, corp_code):
            calls.append((bgn, end, corp_code))
            return [{"rcept_no": "20260316000100", "stock_code": "105560", "corp_code": corp_code,
                     "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260316"}]

    saved = []
    cur = FakeCursor([("20260619000667", "105560", "2025.12", False)], "00688996")
    monkeypatch.setattr(mod, "get_db_connection", lambda: FakeConn(cur))
    monkeypatch.setattr(dart_sync_rdb, "_client", lambda: FakeDart())
    monkeypatch.setattr(dart_sync_rdb, "_save_disclosures", lambda c, items, stocks: saved.extend(items) or len(items))
    mod.build_trees()
    assert calls == [("20251231", "20260619", "00688996")]
    assert [i["rcept_no"] for i in saved] == ["20260316000100"]
    updates = [p for s, p in cur.sql if s.startswith("UPDATE stock_reports SET status = 'missing'")]
    assert len(updates) == 1 and updates[0][1] == "20260619000667"
