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
