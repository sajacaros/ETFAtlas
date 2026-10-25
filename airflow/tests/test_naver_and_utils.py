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


def test_fetch_etf_profile_rounds_up_fee():
    assert naver_client.fetch_etf_profile("069500", FakeSession({"totalFee": 0.1501})) == {"expense_ratio": 0.16}
    assert naver_client.fetch_etf_profile("069500", FakeSession({"totalFee": 0.15})) == {"expense_ratio": 0.15}


def test_fetch_etf_profile_fields():
    payload = {
        "totalFee": 0.15,
        "etfSummary": "기초지수를 추종합니다.<br>KOSPI200 &amp; 대형주<BR/>  구성 <b>200</b>종목",
        "etfBaseIndex": " 코스피 200 ",
        "listedDate": "20021014",
        "dividend": {"dividendYieldTtm": 0.98, "dividendPerShareTtm": 849, "dividendCountThisYear": 3},
    }
    assert naver_client.fetch_etf_profile("069500", FakeSession(payload)) == {
        "expense_ratio": 0.15,
        "description": "기초지수를 추종합니다. KOSPI200 & 대형주 구성 200 종목",
        "base_index": "코스피 200",
        "listed_date": "2002-10-14",
        "dividend_yield": 0.98,
        "dividend_per_share": 849,
    }


def test_fetch_etf_profile_keeps_zero_dividend():
    payload = {"dividend": {"dividendYieldTtm": 0, "dividendPerShareTtm": 0}}
    assert naver_client.fetch_etf_profile("069500", FakeSession(payload)) == {
        "dividend_yield": 0.0, "dividend_per_share": 0}


def test_fetch_etf_profile_skips_empty_fields():
    payload = {"etfSummary": "<br>", "etfBaseIndex": "", "listedDate": "2002",
               "dividend": {"dividendYieldTtm": None}}
    assert naver_client.fetch_etf_profile("069500", FakeSession(payload)) == {}


def test_fetch_etf_profile_failure_returns_none():
    assert naver_client.fetch_etf_profile("069500", FakeSession({}, status=500)) is None


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


def test_find_missing_price_dates_keeps_only_gaps():
    age_utils = pytest.importorskip("age_utils")
    days = ["20261015", "20261016", "20261017"]
    existing = {
        ("069500", "20261015"), ("069500", "20261016"), ("069500", "20261017"),  # 빠진 날 없음
        ("091160", "20261015"), ("091160", "20261017"),                          # 중간 하루 빠짐
    }
    result = age_utils.find_missing_price_dates({"069500", "091160", "102110"}, days, existing)
    assert result == {"091160": ["20261016"], "102110": days}


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


@pytest.mark.parametrize("now, expected", [
    ("2026-10-21 08:50", True),   # 개장 전: 직전 거래일 값
    ("2026-10-21 09:00", False),  # 장중: 그날 움직이는 값
    ("2026-10-21 15:59", False),
    ("2026-10-21 16:30", True),   # 종가 확정 뒤: 그날 값
])
def test_snapshot_is_settled(now, expected):
    from datetime import datetime
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.snapshot_is_settled(datetime.strptime(now, "%Y-%m-%d %H:%M")) is expected


@pytest.mark.parametrize("name, ok", [
    ("1Q 은액티브", False),
    ("TIGER 은액티브", False),
    ("KODEX 은행", True),
    ("TIGER 은행고배당플러스TOP10", True),
])
def test_universe_name_filter_excludes_silver(name, ok):
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.passes_universe_name_filter(name) is ok


@pytest.mark.parametrize("name, cycle, expected", [
    ("KODEX 200", 3, 3),
    ("TIGER 미국배당다우존스", 1, 1),
    ("PLUS 200TR", 3, 0),
    ("SOL 코리아밸류업TR", 3, 0),
    ("KODEX TRF3070", 3, 3),
    ("KODEX 200", None, None),
])
def test_resolve_dividend_cycle(name, cycle, expected):
    age_utils = pytest.importorskip("age_utils")
    assert age_utils.resolve_dividend_cycle(name, cycle) == expected


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


def test_diff_etf_profiles_keeps_only_changed_fields():
    age_utils = pytest.importorskip("age_utils")
    current = {
        "069500": {"code": "069500", "expense_ratio": 0.15, "description": "설명",
                   "base_index": "코스피 200", "listed_date": "2002-10-14"},
        "091160": {"code": "091160", "expense_ratio": 0.45, "description": None,
                   "base_index": None, "listed_date": None},
    }
    fetched = {
        "069500": {"expense_ratio": 0.15, "description": "설명",
                   "base_index": "코스피 200", "listed_date": "2002-10-14"},  # 변화 없음
        "091160": {"expense_ratio": 0.09, "description": "반도체",
                   "listed_date": "2006-06-27"},                               # 보수 인하 + 백필
        "0091P0": {"expense_ratio": 0.5},                                      # 신규
    }
    assert age_utils.diff_etf_profiles(current, fetched) == {
        "091160": {"expense_ratio": 0.09, "description": "반도체", "listed_date": "2006-06-27"},
        "0091P0": {"expense_ratio": 0.5},
    }


def test_daily_return():
    age_utils = pytest.importorskip("age_utils")
    prices = [("2026-10-16", 100.0), ("2026-10-20", 110.0), ("2026-10-21", 99.0)]
    assert age_utils.daily_return(prices, "2026-10-21") == -10.0
    assert age_utils.daily_return(prices, "2026-10-20") == 10.0  # 주말을 건너 직전 거래일과 비교
    assert age_utils.daily_return(prices, "2026-10-16") is None  # 직전 가격 없음
    assert age_utils.daily_return(prices, "2026-10-22") is None  # 그날 가격 없음


def test_find_rising_etfs_sorted_and_thresholded():
    age_utils = pytest.importorskip("age_utils")
    prices = {
        "A": [("2026-10-20", 100.0), ("2026-10-21", 103.0)],
        "B": [("2026-10-20", 100.0), ("2026-10-21", 110.0)],
        "C": [("2026-10-20", 100.0), ("2026-10-21", 102.9)],
        "D": [("2026-10-20", 100.0)],  # 그날 가격 없음
    }
    result = age_utils.find_rising_etfs(prices, {"A": "에이"}, "2026-10-21", 3.0)
    assert [(r["etf_code"], r["etf_name"], r["return_1d"]) for r in result] == [("B", "B", 10.0), ("A", "에이", 3.0)]


def test_format_daily_report():
    age_utils = pytest.importorskip("age_utils")
    rising = [{"etf_code": f"E{i}", "etf_name": f"이티에프{i}", "return_1d": 20.0 - i, "holdings": []} for i in range(12)]
    report = {
        "rising": rising,
        "features": ["반도체 ETF 8개가 SK하이닉스 상승에 함께 올랐다."],
    }
    header, blocks = age_utils.format_daily_report("2026-10-21", report, 3.0, [{"code": "N", "name": "새"}])
    assert header == "📈 **ETF 일일 리포트** (2026-10-21)"
    assert blocks[0] == "신규 편입: 새(N)"
    assert blocks[1] == "**오늘의 특징**\n• 반도체 ETF 8개가 SK하이닉스 상승에 함께 올랐다."
    lines = blocks[2].split("\n")
    assert lines[0] == "**상승 ETF** (1일 +3.0% 이상 12개 중 상위 10개)"
    assert lines[1] == "1. 이티에프0 (E0) +20.00%"
    assert len(lines) == 11

    _, blocks = age_utils.format_daily_report("2026-10-21", {**report, "rising": rising[:2], "features": []}, 3.0, [])
    assert blocks[0].split("\n")[0] == "**상승 ETF** (1일 +3.0% 이상 2개)"

    _, blocks = age_utils.format_daily_report("2026-10-21", {**report, "rising": []}, 3.0, [])
    assert blocks == ["1일 +3.0% 이상 오른 ETF가 없습니다."]


def test_backfill_price_days_leaves_recent_days_to_daily_collection(monkeypatch):
    age_utils = pytest.importorskip("age_utils")
    business = [f"202610{d:02d}" for d in range(1, 24)]  # 23일치 (주말 구분 없이 단순화)
    calls = []

    def fake_business_days(start, end):
        calls.append((start, end))
        return business

    monkeypatch.setattr(age_utils, "last_settled_day", lambda now: "20261023")
    monkeypatch.setattr(age_utils, "get_business_days", fake_business_days)
    days = age_utils.backfill_price_days(30)
    assert calls == [("20260923", "20261023")]
    assert days == business[:-age_utils.PRICE_REFILL_BUSINESS_DAYS]
