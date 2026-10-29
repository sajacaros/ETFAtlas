"""기업 분석: 그래프 밖 종목 안내, DART 실적·공시 스킬, DART 키 설정."""
import asyncio
import json
from datetime import date, timedelta

import pytest

from app.services.chat_memory import ConversationContext
from app.models.dart import DartSetting, StockDisclosure, StockFinancial
from app.services.answer.skills import REGISTRY
from app.services.domain.financials import build_periods, quarter_values
from app.services.domain.universe import STOCK_SCOPE


# --- 리졸버: 그래프 밖 종목 ---

@pytest.fixture
def fake_stock_graph(monkeypatch):
    """그래프에는 삼성전자와 KIS 약칭으로 들어간 현대차만, DART 고유번호에는 그 밖의 회사도 있다."""
    from app.services import graph_service
    from app.services.domain import entities as resolver_mod
    stocks = [{"code": "005930", "name": "삼성전자"}, {"code": "005380", "name": "현대차"}]
    corps = [
        {"code": "005930", "name": "삼성전자"},
        {"code": "005380", "name": "현대자동차"},  # 그래프 이름과 다르다
        {"code": "003230", "name": "삼양식품"},  # 상장사지만 수집 ETF에 없다
        {"code": None, "name": "비상장회사"},
    ]

    class FakeGraph:
        parse_agtype = staticmethod(graph_service.GraphService.parse_agtype)

        def __init__(self, db):
            pass

        def execute_cypher(self, cypher, params, raise_errors=False):
            if "code" in params:
                return [{"result": json.dumps(s)} for s in stocks if s["code"] == params["code"]]
            return [{"result": json.dumps(s)} for s in stocks if params["query"] in s["name"].lower()]

    def dart_corp(db, code, query):
        return next((c for c in corps if (code and c["code"] == code) or (not code and c["name"].lower() == query)), None)

    monkeypatch.setattr(resolver_mod, "GraphService", FakeGraph)
    monkeypatch.setattr(resolver_mod, "_dart_corp", dart_corp)


def test_resolver_tells_stocks_outside_the_graph_apart(fake_stock_graph):
    from app.services.domain.entities import EntityResolver, UnmanagedStock
    r = EntityResolver()
    assert r.stock(None, "삼성전자") == {"code": "005930", "name": "삼성전자"}
    # DART 회사명으로 불러도 종목코드로 그래프의 종목을 찾는다
    assert r.stock(None, "현대자동차") == {"code": "005380", "name": "현대차"}
    for name in ("삼양식품", "003230"):
        with pytest.raises(UnmanagedStock) as exc:
            r.stock(None, name)
        assert exc.value.corp == {"code": "003230", "name": "삼양식품"} and exc.value.listed
    with pytest.raises(UnmanagedStock) as exc:
        r.stock(None, "비상장회사")
    assert not exc.value.listed
    assert r.stock(None, "없는회사") is None
    found, missing = r.stocks(None, ["삼성전자", "삼양식품", "없는회사"])
    assert [s["code"] for s in found] == ["005930"]
    assert missing == ["삼양식품(수집하는 ETF에 담기지 않은 종목)", "없는회사"]
    with pytest.raises(UnmanagedStock):  # 하나만 물었으면 단일 종목과 같은 안내
        r.stocks(None, ["삼양식품"])


class _Closable:
    def close(self):
        pass


def _run(skill_name, args, display, db_factory=_Closable):
    from app.services.domain.entities import EntityResolver
    from app.services.answer.skills.base import SkillContext

    async def run():
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=db_factory,
                           resolver=EntityResolver(), ai_config=None, stop=asyncio.Event())
        skill = REGISTRY[skill_name]
        return [e async for e in skill.run(skill.Args(**args), display, ctx)]

    return asyncio.run(run())[-1]


@pytest.mark.parametrize("skill,args,display", [
    ("stock_trend", {"stocks": ["삼양식품"]}, "line"),
    ("stock_holders", {"stocks": ["삼양식품"]}, "bar"),
    ("company_financials", {"stock": "삼양식품"}, "bar"),
    ("company_disclosures", {"stock": "삼양식품"}, "markdown"),
    ("company_report", {"stock": "삼양식품"}, "markdown"),
    ("company_revenue_mix", {"stock": "삼양식품"}, "bar"),
])
def test_stock_skills_explain_why_a_listed_stock_cannot_be_analyzed(fake_stock_graph, skill, args, display):
    result = _run(skill, args, display)
    assert result["status"] == "empty"
    assert not result["retryable"]  # 다시 설계해도 결과가 같다
    assert result["message"].startswith(STOCK_SCOPE)
    assert "순자산 500억 원 이상" in result["message"]
    assert "삼양식품(003230) 종목은 지금 수집하는 ETF 어디에도 담겨 있지 않아 분석할 수 없습니다" in result["message"]


def test_unlisted_company_is_told_apart(fake_stock_graph):
    result = _run("company_financials", {"stock": "비상장회사"}, "bar")
    assert result["message"].startswith("비상장회사은(는) 상장 종목이 아니어서 분석할 수 없습니다")


def test_etf_slot_with_an_outside_stock_name_is_retryable(fake_stock_graph, monkeypatch):
    """ETF 이름 후보가 여럿인데 정확히 같은 이름의 종목(그래프 밖이어도)이면 종목 스킬로 다시 설계한다."""
    from app.services.domain import entities as resolver_mod
    from app.services.domain.entities import AmbiguousETF
    original = resolver_mod.EntityResolver._lookup

    def lookup(db, label, name):
        if label == "ETF":
            raise AmbiguousETF(name, [{"code": "A", "name": "X"}, {"code": "B", "name": "Y"}])
        return original(db, label, name)

    monkeypatch.setattr(resolver_mod.EntityResolver, "_lookup", staticmethod(lookup))
    result = _run("holdings", {"etf": "삼양식품"}, "treemap")
    assert result["retryable"] and "개별 종목" in result["message"]


# --- 실적 ---

def _fin(year, reprt, account, amount, cum=None, fs="CFS", rcept="20260814000123"):
    return StockFinancial(stock_code="005930", bsns_year=year, reprt_code=reprt, fs_div=fs, account=account,
                          amount=amount, amount_cum=cum, rcept_no=rcept)


def _amounts(rows):
    return {(r.bsns_year, r.reprt_code, r.account): (r.amount, r.amount_cum) for r in rows}


def test_fourth_quarter_is_annual_minus_nine_month_cumulative():
    a = _amounts([_fin(2025, "11013", "매출액", 10), _fin(2025, "11012", "매출액", 20, 30),
                  _fin(2025, "11014", "매출액", 30, 60), _fin(2025, "11011", "매출액", 100)])
    assert quarter_values(a, 2025, "매출액") == [10, 20, 30, 40]


def test_fourth_quarter_falls_back_to_summing_quarters_and_never_fills_zero():
    a = _amounts([_fin(2025, "11013", "영업이익", 1), _fin(2025, "11012", "영업이익", 2),
                  _fin(2025, "11014", "영업이익", 3), _fin(2025, "11011", "영업이익", 10)])
    assert quarter_values(a, 2025, "영업이익") == [1, 2, 3, 4]
    a = _amounts([_fin(2025, "11013", "영업이익", 1), _fin(2025, "11011", "영업이익", 10)])
    assert quarter_values(a, 2025, "영업이익") == [1, None, None, None]


def test_periods_drop_empty_quarters_and_compute_margin():
    a = _amounts([_fin(2026, "11013", "매출액", 200), _fin(2026, "11013", "영업이익", 30),
                  _fin(2026, "11013", "당기순이익", -5)])
    assert build_periods(a, "quarter") == [{"period": "2026.1Q", "revenue": 200, "operating_income": 30,
                                            "net_income": -5, "margin": 15.0}]


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *conditions):
        return self

    def order_by(self, *columns):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return FakeQuery([r for r in self.rows if isinstance(r, model)])

    def close(self):
        pass


def test_financials_prefer_consolidated_and_summarize_year_over_year(fake_stock_graph):
    rows = [_fin(2025, "11013", "매출액", 100_0000_0000_0000), _fin(2025, "11013", "영업이익", 10_0000_0000_0000),
            _fin(2026, "11013", "매출액", 120_0000_0000_0000), _fin(2026, "11013", "영업이익", 6_0000_0000_0000),
            _fin(2026, "11013", "매출액", 1, fs="OFS"),
            _fin(2026, "11013", "부채총계", 50_0000_0000_0000), _fin(2026, "11013", "자본총계", 200_0000_0000_0000)]
    result = _run("company_financials", {"stock": "삼성전자"}, "table", lambda: FakeDB(rows))
    assert result["status"] == "complete"
    content = result["content"]
    assert [r["period"] for r in content["dataset"]["rows"]] == ["2025.1Q", "2026.1Q"]
    assert content["dataset"]["rows"][1]["revenue"] == 120_0000_0000_0000  # 별도(OFS) 값을 섞지 않는다
    assert content["sources"] == [{"label": "DART 주요계정 (연결재무제표)", "as_of": "2026-08-14"}]
    summary = result["summary"]
    assert "2026.1Q의 전년 동기(2025.1Q) 대비: 매출액 +20.0%, 영업이익 -40.0%" in summary
    assert "부채비율 25.0% (2026년 1분기 기준" in summary


def test_financials_state_when_net_income_exceeds_revenue(fake_stock_graph):
    """SK하이닉스 2026년 2분기처럼 금융수익이 커서 순이익이 매출액보다 크면 해설이 비교하지 않아도 되게 적는다."""
    rows = [_fin(2026, "11013", "매출액", 52_5762_8700_0000), _fin(2026, "11013", "당기순이익", 40_3459_0900_0000),
            _fin(2026, "11012", "매출액", 79_3187_4600_0000), _fin(2026, "11012", "당기순이익", 93_9225_9300_0000)]
    result = _run("company_financials", {"stock": "삼성전자"}, "bar", lambda: FakeDB(rows))
    assert "순이익이 매출액보다 큰 기간이 있습니다: 2026.2Q 순이익 93조 9,225억원 > 매출액 79조 3,187억원" in result["summary"]
    assert any(n.startswith("순이익이 매출액보다 큰 기간") for n in result["content"]["notes"])
    rows = rows[:2]
    assert "보여 준 모든 기간에서 순이익은 매출액보다 작습니다" in _run(
        "company_financials", {"stock": "삼성전자"}, "bar", lambda: FakeDB(rows))["summary"]


def test_financials_without_data_say_so(fake_stock_graph):
    result = _run("company_financials", {"stock": "삼성전자"}, "bar", lambda: FakeDB([]))
    assert result["status"] == "empty" and "DART 실적 데이터가 아직 없습니다" in result["message"]


# --- 공시 ---

def _disc(days_ago, title, no):
    return StockDisclosure(rcept_no=no, stock_code="005930", corp_code="00126380", report_nm=title,
                           rcept_dt=date.today() - timedelta(days=days_ago), flr_nm="삼성전자")


def test_disclosures_link_to_dart_and_pass_only_titles_to_the_narrative(fake_stock_graph):
    rows = [_disc(1, "분기보고서 (2026.09)", "20261018000001"), _disc(3, "주요사항보고서(자기주식취득결정)", "20261016000002")]
    result = _run("company_disclosures", {"stock": "삼성전자"}, "markdown", lambda: FakeDB(rows))
    text = result["content"]["text"]
    assert "[분기보고서 (2026.09)](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261018000001)" in text
    assert "rcpNo" not in result["summary"] and "본문은 읽지 않음" in result["summary"]
    assert "주요사항보고서(자기주식취득결정)" in result["summary"]


def test_disclosures_hide_insider_ownership_reports_unless_asked(fake_stock_graph):
    rows = [_disc(1, "임원ㆍ주요주주특정증권등소유상황보고서", "20261018000009"), _disc(2, "반기보고서 (2026.06)", "20261017000001")]
    result = _run("company_disclosures", {"stock": "삼성전자"}, "markdown", lambda: FakeDB(rows))
    assert "소유상황보고서](" not in result["content"]["text"]
    assert "임원·주요주주 지분 변동 보고서 1건은 뺐습니다" in result["content"]["text"]
    assert "1건 제외" in result["summary"]
    result = _run("company_disclosures", {"stock": "삼성전자", "insider": True}, "markdown", lambda: FakeDB(rows))
    assert "임원ㆍ주요주주특정증권등소유상황보고서](" in result["content"]["text"]


# --- DART 키 설정 ---

@pytest.fixture
def encryption_key(monkeypatch):
    from app.utils import encryption
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setattr(encryption, "_aesgcm_instance", None)
    yield
    encryption._aesgcm_instance = None


class SettingDB:
    def __init__(self, setting=None):
        self.setting = setting

    def get(self, model, id):
        return self.setting

    def add(self, obj):
        self.setting = obj

    def commit(self):
        pass


def test_dart_key_is_stored_encrypted_and_masked(encryption_key):
    from app.routers import admin
    from app.schemas.chat import DartSettingsUpdate
    from app.services import dart_config

    db = SettingDB()
    assert asyncio.run(admin.get_dart_settings(db=db, admin_id=1)) == {"api_key_masked": None}
    response = asyncio.run(admin.update_dart_settings(DartSettingsUpdate(api_key=" secret-9876 "), db=db, admin_id=1))
    assert isinstance(db.setting, DartSetting) and db.setting.api_key != "secret-9876"  # 평문으로 저장하지 않는다
    assert dart_config.load_dart_key(db) == "secret-9876"
    assert response == {"api_key_masked": "…9876"}
    response = asyncio.run(admin.update_dart_settings(DartSettingsUpdate(api_key=""), db=db, admin_id=1))
    assert db.setting.api_key is None and response == {"api_key_masked": None}
    assert dart_config.check_dart_key(dart_config.load_dart_key(db)) == {"ok": False, "error": "저장한 DART API 키가 없습니다"}


def test_undecryptable_dart_key_counts_as_missing(encryption_key):
    from app.services import dart_config
    assert dart_config.load_dart_key(SettingDB(DartSetting(id=1, api_key="not-a-ciphertext"))) == ""


# --- 정기보고서 목차 트리 (report_tree) ---

REPORT_XML = """<DOCUMENT><BODY>
<COVER-TITLE ATOC="Y" ATOCID="1">반 기 보 고 서</COVER-TITLE><P>표지</P>
<SECTION-1><TITLE ATOC="Y" ATOCID="3">I. 회사의 개요</TITLE><P>회사의 개요 """ + "가" * 200 + """</P></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="9">II. 사업의 내용</TITLE>
<SECTION-2><TITLE ATOC="Y" ATOCID="188">1. 사업의 개요</TITLE><P>당사는 메모리 반도체를 만듭니다. """ + "나" * 100 + """</P></SECTION-2>
<SECTION-2><TITLE ATOC="Y" ATOCID="189">2. 주요 제품 및 서비스</TITLE>
<TABLE><TBODY><TR><TD>[주요 제품 매출]</TD><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>
<TABLE><THEAD><TR><TH ROWSPAN="2">품목</TH><TH COLSPAN="2">매출액</TH></TR><TR><TH>3개월</TH><TH>누적</TH></TR></THEAD>
<TBODY><TR><TD ROWSPAN="2">DRAM</TD><TD>100</TD><TD>200</TD></TR><TR><TD>110</TD><TD>210</TD></TR>
<TR><TD COLSPAN="2">합계</TD><TD>410</TD></TR></TBODY></TABLE>
<P>""" + "다" * 100 + """</P></SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="10">III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y" ATOCID="420">3. 연결재무제표 주석</TITLE>
<TITLE ATOC="Y" ATOCID="440">27. 부문별 보고 (연결)</TITLE>
<TABLE><TR><TD><TABLE><TR><TE>영업부문에 대한 공시</TE></TR><TR><TE>당반기</TE><TE>(단위 : 백만원)</TE></TR></TABLE>
<TABLE><THEAD><TR><TH> </TH><TH>DX 부문</TH><TH>DS 부문</TH></TR></THEAD>
<TBODY><TR><TD>매출액</TD><TD>1,000</TD><TD>2,000</TD></TR></TBODY></TABLE></TD></TR></TABLE>
<TABLE><TR><TD>부문 정보는 경영위원회가 검토하는 단위입니다.</TD></TR></TABLE>
<TITLE ATOC="Y" ATOCID="441">28. 특수관계자와의 거래 (연결)</TITLE><P>""" + "바" * 150 + """</P>
</SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="20">VII. 주주에 관한 사항</TITLE>
<P>가. 최대주주의 개요</P><P>최대주주는 삼성생명입니다. """ + "라" * 5000 + """</P>
<P>나. 최대주주 변동현황</P><P>""" + "마" * 5000 + """</P></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="30">XI. 그 밖에 투자자 보호를 위하여 필요한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y" ATOCID="31">3. 제재 등과 관련된 사항</TITLE><P>가동중지명령을 받았습니다 &amp; 개선 중 """ + "사" * 100 + """</P></SECTION-2></SECTION-1>
</BODY></DOCUMENT>"""
RCEPT = "20260814000200"


def _tree():
    from app.services.report_tree import build_tree
    return {n.node_id: n for n in build_tree(REPORT_XML)}


def test_report_tree_follows_the_document_sections():
    nodes = _tree()
    assert nodes["189"].path == "II. 사업의 내용 > 2. 주요 제품 및 서비스"
    assert (nodes["189"].parent_id, nodes["189"].level) == ("9", 2)
    # 같은 SECTION 안의 다음 제목(주석 항목)은 그 SECTION 노드의 자식
    assert nodes["440"].path == "III. 재무에 관한 사항 > 3. 연결재무제표 주석 > 27. 부문별 보고 (연결)"
    assert (nodes["440"].parent_id, nodes["441"].parent_id, nodes["440"].level) == ("420", "420", 3)
    assert nodes["9"].chars == 0  # 장 자신의 본문은 없고 하위 절에 있다
    assert "가동중지명령을 받았습니다 & 개선 중" in nodes["31"].text
    assert [n.seq for n in nodes.values()] == list(range(len(nodes)))


def test_report_tables_resolve_merged_cells_and_take_the_caption_above():
    from app.services.report_tree import render_table
    table = next(b.table for b in _tree()["189"].blocks if b.kind == "table")
    assert table["header"] == ["품목", "매출액 / 3개월", "매출액 / 누적"]  # 여러 줄 머리말을 열마다 한 줄로
    assert table["rows"] == [["DRAM", "100", "200"], ["DRAM", "110", "210"], ["합계", "", "410"]]  # ROWSPAN은 아래로 채운다
    assert (table["caption"], table["unit"]) == ("[주요 제품 매출] (단위 : 백만원)", "백만원")  # 위의 작은 표는 캡션
    assert render_table(table).splitlines()[:3] == ["[주요 제품 매출] (단위 : 백만원)", "| 품목 | 매출액 / 3개월 | 매출액 / 누적 |", "|---|---|---|"]


def test_tables_inside_a_frame_table_are_read_as_tables():
    blocks = _tree()["440"].blocks
    table = next(b.table for b in blocks if b.kind == "table")
    assert table["caption"] == "영업부문에 대한 공시 당반기 (단위 : 백만원)"
    assert table["header"] == ["", "DX 부문", "DS 부문"] and table["rows"] == [["매출액", "1,000", "2,000"]]
    assert any(b.kind == "para" and "경영위원회" in b.text for b in blocks)  # 한 칸짜리 표는 문단


def test_long_sections_split_at_their_subheadings():
    nodes = _tree()
    assert nodes["20-1"].path == "VII. 주주에 관한 사항 > 가. 최대주주의 개요"
    assert (nodes["20-1"].parent_id, nodes["20-1"].level) == ("20", 2)
    assert "삼성생명" in nodes["20-1"].text and "삼성생명" not in nodes["20-2"].text
    assert nodes["20"].chars == 0


def test_big_tables_keep_the_rows_the_question_asks_about():
    from app.services.report_tree import render_table
    table = {"caption": None, "unit": None, "header": ["성명", "직위"],
             "rows": [[f"임원{i}", "부사장"] for i in range(100)] + [["합 계", "100명"]]}
    text = render_table(table, keywords=["임원57"], max_rows=10)
    assert "| 임원57 | 부사장 |" in text and "| 합 계 | 100명 |" in text and "| 임원0 |" in text
    assert "| 임원30 |" not in text and "표 101행 중 5행" in text
    assert "88행 생략" in render_table({**table, "rows": table["rows"][:98]}, max_rows=10)


def test_summary_input_lists_the_subheadings_of_a_long_node():
    from app.services.report_tree import Block, Node, needs_summary, summary_input
    blocks = [Block("heading", "가. 등기임원"), Block("para", "가" * 9000), Block("heading", "마. 직원 등의 현황"),
              Block("para", "직원 128,612명")]
    text = summary_input(Node("27", None, 0, 2, "1. 임원 및 직원 등의 현황", "VIII. 임원 > 1. 임원 및 직원 등의 현황", blocks))
    assert text.startswith("## 이 절 전체의 소제목·표 제목\n가. 등기임원\n마. 직원 등의 현황")  # 뒤쪽 소제목도 색인에 들어간다
    assert len(text) < 8100
    assert not needs_summary(Node("x", None, 0, 3, "2-1. 연결 재무상태표", "III. 재무에 관한 사항 > 2. 연결재무제표 > 2-1. 연결 재무상태표",
                                  [Block("para", "가" * 500)]))  # 재무제표 본표는 제목으로 충분하다


def test_report_name_tells_first_and_third_quarter_apart():
    from app.services.report_tree import report_name, report_period
    # 공시 제목은 1·3분기 모두 '분기보고서'다 — 주요계정의 보고서 코드가 있으면 그것을, 없으면 기간 끝 달을 본다
    assert report_name("분기보고서 (2026.03)") == "2026년 1분기보고서"
    assert report_name("분기보고서 (2025.09)") == "2025년 3분기보고서"
    assert report_name("분기보고서 (2026.03)", 2025, "11014") == "2025년 3분기보고서"
    assert report_name("[첨부정정]사업보고서 (2025.12)") == "2025년 사업보고서 (첨부정정)"
    assert report_period("[기재정정]반기보고서 (2026.06)") == report_period(None, 2026, "11012") == "2026.06"


def test_reports_to_index_are_the_last_year_with_the_amendment_only():
    from app.services.report_tree import latest_reports
    financials = [("005930", "20260814000200", 2026, "11012"), ("005930", "20260515000100", 2026, "11013"),
                  ("005930", "20250515000100", 2025, "11013")]  # 1년 지남
    disclosures = [("005930", "20260814000200", "반기보고서 (2026.06)"), ("005930", "20261009000400", "[기재정정]반기보고서 (2026.06)"),
                   ("005930", "20260901000300", "주요사항보고서(자기주식취득결정)")]
    assert latest_reports(financials, disclosures, date(2025, 10, 25)) == [
        ("20260515000100", "005930", "2026년 1분기보고서", "2026.03"),
        ("20261009000400", "005930", "2026년 반기보고서 (기재정정)", "2026.06"),  # 같은 기간이면 정정본만
    ]


def test_reports_to_index_skip_attachment_only_old_period_and_missing_filings():
    from app.services.report_tree import attachment_only, latest_reports, stale_period
    financials = [("140670", "20260814002300", 2026, "11012"), ("105560", "20260316000100", 2025, "11011")]
    disclosures = [
        ("140670", "20260929000169", "[첨부정정]반기보고서 (2026.06)"),  # 첨부만 바꿈 → 원래 보고서
        ("140670", "20260814002367", "[첨부추가]반기보고서 (2026.06)"),
        ("105560", "20260619000667", "[기재정정]사업보고서 (2025.12)"),  # DART에 원문이 없음 → 원래 보고서
        ("105560", "20260324000822", "[기재정정]사업보고서 (2024.12)"),  # 접수는 최근이지만 옛 기간
    ]
    assert latest_reports(financials, disclosures, date(2025, 10, 25), exclude={"20260619000667"}) == [
        ("20260316000100", "105560", "2025년 사업보고서", "2025.12"),
        ("20260814002300", "140670", "2026년 반기보고서", "2026.06"),
    ]
    assert attachment_only("2026년 반기보고서 (첨부정정)") and not attachment_only("2026년 반기보고서 (기재정정)")
    assert stale_period("2025.06", date(2025, 10, 25)) and not stale_period("2025.09", date(2025, 10, 25))


def test_pick_report_prefers_the_latest_period_over_a_late_amendment():
    from app.services.answer.skills.company_report import pick_report
    from app.models.dart import StockReport
    rows = [StockReport(rcept_no="20260515002888", period="2026.03", status="tree"),
            StockReport(rcept_no="20260619000667", period="2025.12", status="summarized"),
            StockReport(rcept_no="20260929000169", period="2026.06", status="missing")]
    assert pick_report(rows, None).rcept_no == "20260515002888"
    assert pick_report(rows, "2025.12").rcept_no == "20260619000667"


# --- company_report · company_revenue_mix ---

class ReportQuery(FakeQuery):
    def options(self, *options):
        return self


class ReportDB(FakeDB):
    def __init__(self, rows):
        super().__init__(rows)
        self.commits = 0

    def query(self, model):
        return ReportQuery([r for r in self.rows if isinstance(r, model)])

    def get(self, model, key):
        return next((r for r in self.rows if isinstance(r, model) and r.rcept_no == key), None)

    def expunge(self, obj):
        pass

    def commit(self):
        self.commits += 1


def _indexed(status="summarized", summaries=None, **report):
    """REPORT_XML을 색인한 보고서와 노드."""
    from app.models.dart import ReportNode, StockReport
    from app.services.report_tree import build_tree
    rows = [StockReport(rcept_no=RCEPT, stock_code="005930", report_nm="2026년 반기보고서", period="2026.06", status=status,
                        **report)]
    for n in build_tree(REPORT_XML):
        rows.append(ReportNode(rcept_no=RCEPT, node_id=n.node_id, parent_id=n.parent_id, seq=n.seq, level=n.level,
                               title=n.title, path=n.path, chars=n.chars, blocks=n.blocks_json(),
                               content_hash=n.content_hash, summary=(summaries or {}).get(n.node_id)))
    return ReportDB(rows)


class _Config:
    llm_model = "test"


def _writer(text, prompts):
    """흘려보낼 답을 정해 두고 모델이 받은 글을 모으는 가짜 모델."""
    from pydantic_ai.models.function import FunctionModel

    async def stream(messages, info):
        prompts.append("\n".join(str(getattr(p, "content", "")) for m in messages for p in m.parts))
        yield text
    return FunctionModel(stream_function=stream)


def test_company_report_without_an_indexed_report_says_so(fake_stock_graph):
    from app.models.dart import StockReport
    result = _run("company_report", {"stock": "삼성전자"}, "markdown", lambda: ReportDB([]))
    assert result["status"] == "empty" and "정기보고서를 찾지 못했습니다" in result["message"]
    pending = StockReport(rcept_no=RCEPT, stock_code="005930", report_nm="2026년 반기보고서", status="pending")
    result = _run("company_report", {"stock": "삼성전자"}, "markdown", lambda: ReportDB([pending]))
    assert "아직 색인하지 못했습니다" in result["message"]
    result = _run("company_report", {"stock": "삼성전자", "period": "2025.12"}, "markdown", lambda: _indexed())
    assert "2025.12 기간 정기보고서는 색인돼 있지 않습니다" in result["message"]


def test_company_report_answers_from_the_nodes_it_picks(fake_stock_graph, monkeypatch):
    from app.services.answer.skills import company_report
    picked = []

    async def pick(ctx, entries, need):
        picked.append((need, company_report.outline(entries)))
        return company_report.expand(entries, ["189", "999"]), ["DRAM"]
    prompts = []
    monkeypatch.setattr(company_report, "pick_nodes", pick)
    monkeypatch.setattr(company_report, "build_model", lambda config: _writer("- DRAM 누적 매출 200백만원", prompts))
    db = _indexed(summaries={"189": "품목별 매출액(3개월·누적)"})

    async def run():
        from app.services.domain.entities import EntityResolver
        from app.services.answer.skills.base import SkillContext
        ctx = SkillContext(question="삼성전자 DRAM 매출 얼마야?", conversation=ConversationContext(), session_factory=lambda: db,
                           resolver=EntityResolver(), ai_config=_Config(), stop=asyncio.Event())
        skill = REGISTRY["company_report"]
        return [e async for e in skill.run(skill.Args(stock="삼성전자", need="DRAM 매출"), "markdown", ctx)]

    events = asyncio.run(run())
    assert events[0] == {"type": "title", "title": "삼성전자 2026년 반기보고서: DRAM 매출"}
    # 목차에는 제목과 노드 요약이 함께, 빈 서식 같은 짧은 절은 빠진다
    assert picked[0][0] == "DRAM 매출" and "[189] 2. 주요 제품 및 서비스 (" in picked[0][1] and "— 품목별 매출액(3개월·누적)" in picked[0][1]
    assert "[1] 반 기 보 고 서" not in picked[0][1]
    assert "| 품목 | 매출액 / 3개월 | 매출액 / 누적 |" in prompts[0]  # 고른 노드의 표를 병합 셀을 푼 채로 읽는다
    result = events[-1]
    text = result["content"]["text"]
    assert result["status"] == "complete" and "읽은 절: II. 사업의 내용 > 주요 제품 및 서비스" in text
    assert "[DART 원문](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814000200)" in text
    assert "".join(e["text"] for e in events if e["type"] == "delta").strip() == text.strip()
    assert result["summary"].startswith("삼성전자의 2026년 반기보고서 (2026-08-14 접수)에서 'DRAM 매출'을(를) 찾아 읽은 절")
    assert "DRAM 누적 매출 200백만원" in result["summary"]


def test_prepare_report_explains_why_a_period_is_not_there(fake_stock_graph):
    from app.models.dart import StockReport
    from app.services.domain.entities import EntityResolver
    from app.services.answer.skills import company_report
    from app.services.answer.skills.base import SkillContext
    db = _indexed()
    db.rows += [StockReport(rcept_no="20260515000100", stock_code="005930", report_nm="2026년 1분기보고서", period="2026.03",
                            status="missing"),
                StockReport(rcept_no="20260316000100", stock_code="005930", report_nm="2025년 사업보고서", period="2025.12",
                            status="pending")]

    def message(period):
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: db,
                           resolver=EntityResolver(), ai_config=None, stop=asyncio.Event())
        return company_report.prepare_report("삼성전자", ctx, period).message

    assert "DART가 원문을 주지 않아" in message("2026.03")
    assert "아직 색인하지 못했습니다" in message("2025.12")
    assert "최근 1년 보고서만" in message("2024.12")


def test_picking_reads_the_sections_of_a_chapter_and_asks_again_for_unknown_ids(fake_stock_graph, monkeypatch):
    from pydantic_ai.models.test import TestModel
    from app.services.domain.entities import EntityResolver
    from app.services.answer.skills import company_report
    from app.services.answer.skills.base import SkillContext
    stock, report, entries = company_report.prepare_report(
        "삼성전자", SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: _indexed(),
                                resolver=EntityResolver(), ai_config=None, stop=asyncio.Event()))
    # 본문이 없는 장을 고르면 하위 절을 읽는다
    assert [e.node_id for e in company_report.expand(entries, ["9"])] == ["188", "189"]
    assert company_report.keywords("연구개발비와 매출 대비 비율") == ["연구개발비", "매출", "대비", "비율"]

    monkeypatch.setattr(company_report, "build_model",
                        lambda config: TestModel(custom_output_args={"ids": ["999"], "keywords": []}))
    ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=None, resolver=None,
                       ai_config=None, stop=asyncio.Event())
    picked, _ = asyncio.run(company_report.pick_nodes(ctx, entries, "최대주주"))
    assert picked == []  # 목차에 없는 id는 버린다 (한 번 더 물어도 없으면 빈 결과)


def test_company_report_overview_reads_every_chapter_once_and_keeps_it(fake_stock_graph, monkeypatch):
    from app.services.answer.skills import company_report
    prompts = []
    monkeypatch.setattr(company_report, "build_model", lambda config: _writer("#### 사업 구조\n- 메모리 반도체", prompts))

    async def no_mix(config, source):
        return []
    monkeypatch.setattr(company_report.report_breakdowns, "extract", no_mix)
    db = _indexed()
    events = _skill_events("company_report", db, "삼성전자 분석해줘", _Config())
    assert events[0] == {"type": "title", "title": "삼성전자 2026년 반기보고서 요약"}
    result = events[-1]
    assert result["status"] == "complete" and "메모리 반도체" in result["content"]["text"]
    assert result["summary"].startswith("삼성전자의 2026년 반기보고서 (2026-08-14 접수) 본문 요약:")
    prompt = prompts[0]
    # 사업의 내용·투자자 보호 사항·부문 주석(연결)을 모두 읽고, 회사의 개요·주주는 읽지 않는다
    assert "## II. 사업의 내용 > 1. 사업의 개요" in prompt and "가동중지명령" in prompt and "| 매출액 | 1,000 | 2,000 |" in prompt
    assert "회사의 개요 가가" not in prompt and "삼성생명" not in prompt
    report = db.get(company_report.StockReport, RCEPT)
    assert report.overview == "#### 사업 구조\n- 메모리 반도체" and report.model == "test" and report.breakdowns == "[]"

    result = _skill_events("company_report", db, "삼성전자 분석해줘", _Config())[-1]
    assert "메모리 반도체" in result["content"]["text"] and len(prompts) == 1  # 다음부터는 남긴 개요


def test_revenue_mix_reads_the_sales_and_segment_tables_once(fake_stock_graph, monkeypatch):
    from app.services.answer.skills import company_report
    from app.services.answer.skills.report_breakdowns import check
    sources = []
    mixes = [check(_mix("segment", [("DX 부문", "1,000"), ("DS 부문", "2,000")], unit="백만원"), "DX 부문 | 1,000 | DS 부문 | 2,000")]

    async def extract(config, source):
        sources.append(source)
        return mixes
    monkeypatch.setattr(company_report.report_breakdowns, "extract", extract)
    db = _indexed()
    events = _skill_events("company_revenue_mix", db, "삼성전자 부문별 매출은?")
    assert events[0] == {"type": "split", "parts": [
        {"id": "chart1", "title": "삼성전자 부문별 매출 · 당반기", "display": "bar"}]}  # 요약 영역은 없다
    assert not any(e["type"] == "delta" for e in events)
    # 매출 표가 있는 절과 부문 주석(연결)을 병합 셀을 푼 표로 넘긴다 — 주석 이름이 '부문별 보고'여도 찾는다
    assert "## II. 사업의 내용 > 2. 주요 제품 및 서비스" in sources[0]
    assert "## III. 재무에 관한 사항 > 3. 연결재무제표 주석 > 27. 부문별 보고 (연결)" in sources[0]
    assert "| 품목 | 매출액 / 3개월 | 매출액 / 누적 |" in sources[0] and "사업의 개요" not in sources[0]
    assert "DX 부문" in db.get(company_report.StockReport, RCEPT).breakdowns
    _skill_events("company_revenue_mix", db, "삼성전자 부문별 매출은?")
    assert len(sources) == 1  # 다음부터는 남긴 구성


def test_company_report_splits_into_revenue_mix_charts_and_the_summary(fake_stock_graph):
    from app.services.answer.skills.report_breakdowns import check, dumps
    mixes = [check(_mix("product", [("장비매출", "69,624,089"), ("부품매출", "4,991,080"), ("용역수익", "3,447,782")],
                        total="78,062,951"), MIX_SOURCE),
             check(_mix("customer", [("고객 A", "21,316,082"), ("고객 B", "5,619,282")]), MIX_SOURCE)]
    db = _indexed(overview="#### 사업 구조\n- 장비", breakdowns=dumps(mixes))
    events = _skill_events("company_report", db, "삼성전자 주 고객은?")
    assert events[0] == {"type": "split", "parts": [
        {"id": "chart1", "title": "삼성전자 주요 고객별 매출 · 당반기", "display": "bar"},  # 질문이 고객을 묻는다
        {"id": "chart2", "title": "삼성전자 제품별 매출 · 당반기", "display": "donut"},
        {"id": "text", "title": "삼성전자 2026년 반기보고서 요약", "display": "markdown"},
    ]}
    results = {e["part"]: e for e in events if e["type"] == "result"}
    assert set(results) == {"chart1", "chart2", "text"}
    assert results["chart2"]["content"]["view"]["kind"] == "donut"
    assert results["chart2"]["summary"] == ("삼성전자 제품별 매출 · 당반기: 장비매출 69,624,089천원(89.2%), "
                                           "부품매출 4,991,080천원(6.4%), 용역수익 3,447,782천원(4.4%)")
    assert results["chart1"]["content"]["notes"]  # 막대는 합이 전체가 아니라고 밝힌다
    assert "장비" in results["text"]["content"]["text"]


def test_revenue_mix_without_tables_says_so(fake_stock_graph):
    result = _skill_events("company_revenue_mix", _indexed(breakdowns="[]"), "삼성전자 주 고객은?")[-1]
    assert result["status"] == "empty" and "매출 구성" in result["message"]


def _skill_events(skill_name, db, question, config=None):
    async def run():
        from app.services.domain.entities import EntityResolver
        from app.services.answer.skills.base import SkillContext
        ctx = SkillContext(question=question, conversation=ConversationContext(), session_factory=lambda: db,
                           resolver=EntityResolver(), ai_config=config, stop=asyncio.Event())
        skill = REGISTRY[skill_name]
        return [e async for e in skill.run(skill.Args(stock="삼성전자"), skill.displays[0], ctx)]
    return asyncio.run(run())


# HPSP 반기보고서 영업부문 주석 (단위 : 천원)
MIX_SOURCE = """제품과 용역에 대한 공시
장비매출 | 부품매출 | 용역수익 | 제품과 용역 합계
고객과의 계약에서 생기는 수익 | 69,624,089 | 4,991,080 | 3,447,782 | 78,062,951
주요 고객에 대한 공시
고객 A | 고객 B | 고객 C | 고객 D
수익 | 21,316,082 | 5,619,282 | 758,622 | 273,555"""


def _mix(kind, items, total=None, unit="천원"):
    from app.services.answer.skills.report_breakdowns import ExtractedBreakdown, ExtractedItem
    return ExtractedBreakdown(kind=kind, period="당반기", unit=unit, total=total,
                              items=[ExtractedItem(name=n, value=v) for n, v in items])


def test_revenue_mix_is_a_donut_only_when_the_items_add_up_to_the_stated_total():
    from app.services.answer.skills.report_breakdowns import check
    products = [("장비매출", "69,624,089"), ("부품매출", "4,991,080"), ("용역수익", "3,447,782")]
    whole = check(_mix("product", products, total="78,062,951"), MIX_SOURCE)
    assert whole["whole"] and [i["value"] for i in whole["items"]] == [69624089, 4991080, 3447782]
    # 합계가 없거나(일부 고객만) 맞지 않으면 막대 — 비중을 말할 수 없다
    customers = [("고객 A", "21,316,082"), ("고객 B", "5,619,282")]
    assert check(_mix("customer", customers), MIX_SOURCE)["whole"] is False
    assert check(_mix("product", products, total="88,242,097"), MIX_SOURCE) is not None
    assert check(_mix("product", products, total="88,242,097"), MIX_SOURCE)["whole"] is False
    # 합계 행은 항목에서 뺀다
    assert len(check(_mix("product", [*products, ("합 계", "78,062,951")], total="78,062,951"), MIX_SOURCE)["items"]) == 3


def test_revenue_mix_with_a_number_not_in_the_report_is_dropped():
    from app.services.answer.skills.report_breakdowns import check
    # 지어낸 값, 다른 숫자의 일부로만 있는 값('624,089'), 단위를 바꾼 값은 표 전체를 버린다
    for value in ("70,000,000", "624,089", "696억"):
        assert check(_mix("product", [("장비매출", value), ("부품매출", "4,991,080")]), MIX_SOURCE) is None
    assert check(_mix("product", [("장비매출", "69,624,089")]), MIX_SOURCE) is None  # 항목 하나는 구성이 아니다
    # 이름이 표의 셀이 아니면(셀을 이어 붙이거나 지어낸 이름) 표를 잘못 읽은 것이다
    for name in ("장비매출 | 부품매출", "출수"):
        assert check(_mix("product", [(name, "69,624,089"), ("부품매출", "4,991,080")]), MIX_SOURCE) is None
    assert check(_mix("region", [("국내", "40"), ("해외", "60")], unit="%"), "국내 | 40 | 해외 | 60")["whole"]
    assert check(_mix("product", [("장비 매출", "69,624,089"), ("부품매출", "4,991,080")]), MIX_SOURCE)  # 띄어쓰기 차이는 본다


def test_revenue_mix_shows_what_the_question_asks_first():
    from app.services.answer.skills.report_breakdowns import choose
    mixes = [{"kind": k} for k in ("customer", "region", "product", "segment")]
    assert [b["kind"] for b in choose(mixes, "HPSP 분석해줘")] == ["segment", "product"]
    assert [b["kind"] for b in choose(mixes, "HPSP의 주 고객은 누구야?")] == ["customer", "segment"]
    assert [b["kind"] for b in choose(mixes[:1], "HPSP 분석해줘")] == ["customer"]


