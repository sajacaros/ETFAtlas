"""dart_client 단위 테스트 (HTTP는 가짜 세션으로 대체)."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

import dart_client  # noqa: E402
from dart_client import (DartClient, DartError, cash_flow_targets, parse_amount, parse_cash_flow_rows,  # noqa: E402
                         parse_corp_codes, parse_financial_rows)


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


def test_parse_cash_flow_rows_matches_ids_then_names_and_keeps_cumulative_amounts():
    items = [
        {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "account_nm": "영업활동현금흐름",
         "thstrm_amount": "56,515"},
        {"sj_div": "CF", "account_id": "-표준계정코드 미사용-", "account_nm": "유형자산의 취득", "thstrm_amount": "-35,972"},
        {"sj_div": "BS", "account_id": "x", "account_nm": "무형자산의 취득", "thstrm_amount": "9"},  # 현금흐름표가 아니다
    ]
    rows = parse_cash_flow_rows(items, "005930", 2025, "11014", "CFS", "r1")
    # 3분기 현금흐름은 9개월 누적 — 3개월 금액이 아니다. 찾지 못한 계정도 받아 본 표시로 남긴다
    assert [(r["account"], r["amount"], r["amount_cum"]) for r in rows] == [
        ("영업활동현금흐름", None, 56515), ("유형자산의취득", None, -35972), ("무형자산의취득", None, None)]
    assert {r["rcept_no"] for r in rows} == {"r1"}
    annual = parse_cash_flow_rows(items, "005930", 2025, "11011", "CFS", "r2")
    q1 = parse_cash_flow_rows(items, "005930", 2026, "11013", "CFS", "r3")
    assert (annual[0]["amount"], annual[0]["amount_cum"]) == (56515, None)
    assert (q1[0]["amount"], q1[0]["amount_cum"]) == (56515, 56515)


def test_parse_cash_flow_rows_adds_up_capex_split_into_parts():
    def cf(name, amount, account_id="dart_x"):
        return {"sj_div": "CF", "account_id": account_id, "account_nm": name, "thstrm_amount": amount}
    items = [cf("영업활동현금흐름", "10"), cf("건물의 취득", "7"), cf("건설중인자산의 취득", "25"), cf("기계장치의 취득", "-"),
             cf("단기금융상품의 취득", "81"), cf("무형자산의 취득", "1")]
    rows = {r["account"]: r["amount"] for r in parse_cash_flow_rows(items, "017960", 2025, "11011", "CFS", "r")}
    assert rows == {"영업활동현금흐름": 10, "유형자산의취득": 32, "무형자산의취득": 1}  # 금융상품 취득은 설비투자가 아니다


def test_cash_flow_targets_pick_consolidated_skip_done_and_go_newest_first():
    reports = [
        ("005930", 2026, "11012", "CFS", "a"), ("005930", 2026, "11012", "OFS", "a"),
        ("005930", 2025, "11011", "CFS", "b"), ("005930", 2025, "11014", "CFS", "c"),
        ("005930", 2023, "11011", "CFS", "d"), ("005930", 2023, "11014", "CFS", "e"),  # 오래된 분기는 받지 않는다
        ("000660", 2026, "11013", "OFS", "f"),
    ]
    done = {("005930", 2025, "11014", "CFS", "c"), ("000660", 2026, "11013", "OFS", "old")}  # 정정되면 다시 받는다
    reports.append(("005930", 2025, "11011", "OFS", "b"))  # 사업보고서는 연결이 있어도 별도를 대조용으로 받는다
    targets = cash_flow_targets(reports, done, 2026, 2, 10)
    assert targets == [("005930", 2026, "11012", "CFS", "a"), ("000660", 2026, "11013", "OFS", "f"),
                       ("005930", 2025, "11011", "CFS", "b"), ("005930", 2025, "11011", "OFS", "b"),
                       ("005930", 2023, "11011", "CFS", "d")]
    assert len(cash_flow_targets(reports, done, 2026, 2, 1)) == 1


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
