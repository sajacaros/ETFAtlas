"""naver_client / age_utils 순수 함수 테스트."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

import naver_client  # noqa: E402


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def get(self, url, timeout, headers):
        assert url.endswith("/069500/etfAnalysis")
        return FakeResp(self.payload, self.status)


def test_fetch_expense_ratio_rounds_up():
    assert naver_client.fetch_expense_ratio("069500", FakeSession({"totalFee": 0.1501})) == 0.16
    assert naver_client.fetch_expense_ratio("069500", FakeSession({"totalFee": 0.15})) == 0.15


def test_fetch_expense_ratio_failure_returns_none():
    assert naver_client.fetch_expense_ratio("069500", FakeSession({}, status=500)) is None
    assert naver_client.fetch_expense_ratio("069500", FakeSession({})) is None


@pytest.mark.parametrize("code,expected", [
    ("005930", True), ("0131V0", True), ("069500", True),
    ("010010", False),          # 설정현금액
    ("KR7005930003", False),    # ISIN / 채권
    ("A005930", False), ("10100", False), ("", False),
])
def test_is_listed_security_code(code, expected):
    age_utils = pytest.importorskip("age_utils")  # psycopg2 필요
    assert age_utils.is_listed_security_code(code) is expected


@pytest.mark.parametrize("name,ok", [
    ("KODEX 200", True), ("TIGER 반도체", True),
    ("KODEX 레버리지", False), ("TIGER 미국S&P500", False), ("KODEX 국고채3년", False),
    ("TIGER 200커버드콜", False),
])
def test_passes_universe_name_filter(name, ok):
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.passes_universe_name_filter(name) is ok


def test_check_new_universe_candidates():
    age_utils = pytest.importorskip("age_utils")
    items = [
        {"code": "069500", "name": "KODEX 200", "net_assets": 10**13},       # 기존
        {"code": "091160", "name": "KODEX 반도체", "net_assets": 600 * 10**8},  # 신규
        {"code": "091230", "name": "TIGER 반도체", "net_assets": 400 * 10**8},  # 500억 미만
        {"code": "122630", "name": "KODEX 레버리지", "net_assets": 10**13},   # 제외 키워드
    ]
    result = age_utils.check_new_universe_candidates(items, {"069500"})
    assert [c["code"] for c in result] == ["091160"]


@pytest.mark.parametrize("now, expected", [
    ("2026-10-01 08:30", "20260930"),  # 스케줄 실행(장 시작 전)
    ("2026-10-01 10:16", "20260930"),  # 장중
    ("2026-10-01 15:59", "20260930"),
    ("2026-10-01 16:00", "20261001"),  # 종가 확정 후
    ("2026-10-01 23:00", "20261001"),
])
def test_last_settled_day(now, expected):
    from datetime import datetime
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.last_settled_day(datetime.strptime(now, "%Y-%m-%d %H:%M")) == expected


@pytest.mark.parametrize("name, ok", [
    ("1Q 은액티브", False),
    ("TIGER 은액티브", False),
    ("KODEX 은행", True),
    ("TIGER 은행고배당플러스TOP10", True),
])
def test_universe_name_filter_excludes_silver(name, ok):
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.passes_universe_name_filter(name) is ok


@pytest.mark.parametrize("name, company", [
    ("KODEX 200", "삼성자산운용"),
    ("IBK K-AI반도체코어테크", "IBK자산운용"),
    ("아이엠에셋 200", "iM에셋자산운용"),
    ("FOCUS 200", "브이아이자산운용"),
    ("DS 코스닥액티브", "디에스자산운용"),
    ("MIDAS 코스피액티브", "마이다스에셋자산운용"),
    ("DAISHIN K200", "대신자산운용"),
    ("DAISHIN343 K200", "대신자산운용"),
    ("NEWBRAND 200", "기타"),
])
def test_get_company_from_etf_name(name, company):
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.get_company_from_etf_name(name) == company
