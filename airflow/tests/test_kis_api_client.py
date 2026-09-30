"""kis_api_client 단위 테스트 (HTTP는 가짜 세션으로 대체)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

from kis_api_client import KISApiClient, KISApiError  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, get_responses):
        self.get_responses = list(get_responses)
        self.token_calls = 0
        self.get_calls = []

    def post(self, url, json, timeout):
        assert url.endswith("/oauth2/tokenP")
        self.token_calls += 1
        expired = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        return FakeResponse({"access_token": f"tok{self.token_calls}",
                             "access_token_token_expired": expired})

    def get(self, url, headers, params, timeout):
        self.get_calls.append((url, headers, params))
        return FakeResponse(self.get_responses.pop(0))


class MemoryCache:
    def __init__(self):
        self.store = {}

    def load(self, key):
        return self.store.get(key)

    def save(self, key, token, expires_at):
        self.store[key] = (token, expires_at)


OK_PAYLOAD = {
    "rt_cd": "0",
    "output1": {"stck_prpr": "35000"},
    "output2": [
        {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자",
         "etf_cnfg_issu_rlim": "25.31", "etf_vltn_amt": "1,234,000", "stck_prpr": "61700"},
        {"stck_shrn_iscd": "000660", "hts_kor_isnm": "SK하이닉스",
         "etf_cnfg_issu_rlim": "10.5", "etf_vltn_amt": "500000", "stck_prpr": "0"},
        {"stck_shrn_iscd": "", "hts_kor_isnm": "원화예금"},
    ],
}


def make_client(responses, cache=None):
    client = KISApiClient("key", "secret", token_cache=cache)
    client.session = FakeSession(responses)
    client.MIN_INTERVAL = 0
    return client


def test_get_etf_components_parses_output2():
    client = make_client([OK_PAYLOAD])
    comps = client.get_etf_components("069500")

    assert [c.stock_code for c in comps] == ["005930", "000660"]
    samsung = comps[0]
    assert samsung.stock_name == "삼성전자"
    assert samsung.weight == pytest.approx(25.31)
    assert samsung.value == 1_234_000
    assert samsung.shares == 20            # 1,234,000 / 61,700
    assert comps[1].shares == 0             # 현재가 0이면 0

    url, headers, params = client.session.get_calls[0]
    assert url.endswith("/uapi/etfetn/v1/quotations/inquire-component-stock-price")
    assert headers["tr_id"] == "FHKST121600C0"
    assert headers["authorization"] == "Bearer tok1"
    assert params == {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "069500",
                      "FID_COND_SCR_DIV_CODE": "11216"}


def test_token_reused_from_cache():
    cache = MemoryCache()
    make_client([OK_PAYLOAD], cache).get_etf_components("069500")
    second = make_client([OK_PAYLOAD], cache)
    second.get_etf_components("069500")
    assert second.session.token_calls == 0  # 캐시된 토큰 재사용


def test_rate_limit_retry(monkeypatch):
    monkeypatch.setattr("kis_api_client.time.sleep", lambda s: None)
    client = make_client([{"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수 초과"}, OK_PAYLOAD])
    assert len(client.get_etf_components("069500")) == 2
    assert len(client.session.get_calls) == 2


def test_expired_token_reissued_once():
    client = make_client([{"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token"}, OK_PAYLOAD])
    client.get_etf_components("069500")
    assert client.session.token_calls == 2
    assert client.session.get_calls[1][1]["authorization"] == "Bearer tok2"


def test_api_error_raised():
    client = make_client([{"rt_cd": "1", "msg_cd": "OPSQ0002", "msg1": "없는 종목"}])
    with pytest.raises(KISApiError) as exc:
        client.get_etf_components("999999")
    assert exc.value.msg_cd == "OPSQ0002"


def _bar(date, close, diff, sign="2"):
    return {"stck_bsop_date": date, "stck_oprc": "100", "stck_hgpr": "110", "stck_lwpr": "90",
            "stck_clpr": str(close), "acml_vol": "1000", "prdy_vrss": str(diff), "prdy_vrss_sign": sign}


def test_get_daily_bars_paginates_and_sorts():
    recent = [(datetime(2026, 9, 30) - timedelta(days=i)).strftime("%Y%m%d") for i in range(100)]
    first = {"rt_cd": "0", "output2": [_bar(d, 100, 0) for d in recent]}  # 최신순 100건
    oldest = min(r["stck_bsop_date"] for r in first["output2"])
    second = {"rt_cd": "0", "output2": [_bar("20260102", 100, 0)]}
    client = make_client([first, second])
    bars = client.get_daily_bars("005930", "20260101", "20260930")

    assert bars[0].date == "20260102"
    assert [b.date for b in bars] == sorted(b.date for b in bars)
    assert len(client.session.get_calls) == 2
    # 두 번째 호출은 첫 페이지의 가장 오래된 날짜 전날까지
    assert client.session.get_calls[1][2]["FID_INPUT_DATE_2"] < oldest
    assert client.session.get_calls[0][1]["tr_id"] == "FHKST03010100"


def test_daily_bar_change_rate_sign():
    client = make_client([{"rt_cd": "0", "output2": [
        _bar("20260929", 105, 5, "2"), _bar("20260930", 95, 10, "5")]}])
    up, down = client.get_daily_bars("005930", "20260929", "20260930")
    assert up.change_rate == 5.0          # 5 / 100
    assert down.change_rate == -9.52      # -10 / 105


def test_is_market_open():
    client = make_client([{"rt_cd": "0", "output": [
        {"bass_dt": "20261003", "opnd_yn": "N"}, {"bass_dt": "20261005", "opnd_yn": "Y"}]}] * 3)
    assert client.is_market_open("20261003") is False
    assert client.is_market_open("20261005") is True
    assert client.is_market_open("20261004") is None
    assert client.session.get_calls[0][1]["tr_id"] == "CTCA0903R"
