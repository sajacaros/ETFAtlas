"""dart_client 단위 테스트 (HTTP는 가짜 세션으로 대체)."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

import dart_client  # noqa: E402
from dart_client import DartClient, DartError, parse_amount, parse_corp_codes, parse_financial_rows  # noqa: E402


def test_parse_amount_keeps_missing_values_missing():
    assert parse_amount("1,234,567") == 1234567
    assert parse_amount("-1,000") == -1000
    assert parse_amount("") is None and parse_amount("-") is None and parse_amount(None) is None


def test_parse_corp_codes_reads_the_zip_and_blank_stock_codes():
    xml = ("<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
           "<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>"
           "<list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>"
           "<stock_code> </stock_code><modify_date>20250101</modify_date></list></result>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    corps = parse_corp_codes(buf.getvalue())
    assert corps[0] == {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930", "modify_date": "20260101"}
    assert corps[1]["stock_code"] is None


def test_parse_financial_rows_normalizes_accounts_and_drops_the_rest():
    base = {"bsns_year": "2026", "reprt_code": "11012", "fs_div": "CFS", "stock_code": "005930", "rcept_no": "20260814000123"}
    rows = parse_financial_rows([
        {**base, "account_nm": "매출액", "thstrm_amount": "74,000", "thstrm_add_amount": "153,000"},
        {**base, "account_nm": "당기순이익(손실)", "thstrm_amount": "-1,000", "thstrm_add_amount": ""},
        {**base, "account_nm": "법인세차감전 순이익", "thstrm_amount": "9"},
        {**base, "account_nm": "매출액", "thstrm_amount": "1"},  # 같은 키는 앞의 것
    ])
    assert [(r["account"], r["amount"], r["amount_cum"]) for r in rows] == [
        ("매출액", 74000, 153000), ("당기순이익", -1000, None)]
    assert rows[0]["bsns_year"] == 2026


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.params = []

    def get(self, url, params, timeout):
        self.params.append(params)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(dart_client.time, "sleep", lambda s: None)


def _client(responses):
    client = DartClient("key")
    client.session = FakeSession(responses)
    return client


def test_disclosures_follow_pages_and_treat_no_data_as_empty():
    client = _client([
        FakeResponse({"status": "000", "total_page": 2, "list": [{"rcept_no": "1"}]}),
        FakeResponse({"status": "000", "total_page": 2, "list": [{"rcept_no": "2"}]}),
    ])
    assert [i["rcept_no"] for i in client.disclosures("20261001", "20261019")] == ["1", "2"]
    assert client.session.params[1]["page_no"] == 2 and "corp_code" not in client.session.params[1]
    assert list(_client([FakeResponse({"status": "013"})]).disclosures("20261001", "20261019", "00126380")) == []


def test_rate_limit_is_retried_and_other_errors_raise():
    client = _client([FakeResponse({"status": "020"}), FakeResponse({"status": "000", "list": [{"x": 1}]})])
    assert client.financials(["00126380"], 2026, "11013") == [{"x": 1}]
    with pytest.raises(DartError):
        _client([FakeResponse({"status": "010", "message": "등록되지 않은 키"})]).financials(["1"], 2026, "11013")


def test_corp_codes_rejects_an_error_instead_of_a_zip():
    with pytest.raises(DartError):
        _client([FakeResponse(content=b"<result><status>010</status></result>")]).corp_codes()


def test_document_returns_the_report_zip_and_rejects_an_error():
    client = _client([FakeResponse(content=b"PK\x03\x04zip")])
    assert client.document("20260814000200") == b"PK\x03\x04zip"
    assert client.session.params[0]["rcept_no"] == "20260814000200"
    with pytest.raises(DartError):
        _client([FakeResponse(content='{"status":"014","message":"파일이 존재하지 않습니다"}'.encode())]).document("1")
