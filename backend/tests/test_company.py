"""기업 분석: 그래프 밖 종목 안내, DART 실적·공시 스킬, DART 키 설정."""
import asyncio
import json
from datetime import date, timedelta

import pytest

from app.services.chat_memory import ConversationContext
from app.models.dart import DartSetting, StockDisclosure, StockFinancial
from app.services.answer.skills import REGISTRY
from app.services.answer.skills.company_financials import build_periods, quarter_values
from app.services.answer.universe import STOCK_SCOPE


# --- 리졸버: 그래프 밖 종목 ---

@pytest.fixture
def fake_stock_graph(monkeypatch):
    """그래프에는 삼성전자와 KIS 약칭으로 들어간 현대차만, DART 고유번호에는 그 밖의 회사도 있다."""
    from app.services import graph_service
    from app.services.answer import resolver as resolver_mod
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
    from app.services.answer.resolver import EntityResolver, UnmanagedStock
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
    from app.services.answer.resolver import EntityResolver
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
    from app.services.answer import resolver as resolver_mod
    from app.services.answer.resolver import AmbiguousETF
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


# --- 최근 정기보고서 ---

REPORT_XML = """<DOCUMENT><BODY>
<COVER-TITLE ATOC="Y">반 기 보 고 서</COVER-TITLE><P>표지</P>
<SECTION-1><TITLE ATOC="Y">I. 회사의 개요</TITLE><P>회사의 개요는 읽지 않는다 """ + "가" * 200 + """</P></SECTION-1>
<SECTION-1><TITLE ATOC="Y">II. 사업의 내용</TITLE>
<SECTION-2><TITLE ATOC="Y">1. 사업의 개요</TITLE><P>당사는 메모리 반도체를 만듭니다. """ + "나" * 100 + """</P></SECTION-2>
<SECTION-2><TITLE ATOC="Y">2. 주요 제품 및 서비스</TITLE>
<TABLE><TR><TH>품목</TH><TH>매출액(비율)</TH></TR><TR><TD>DRAM</TD><TD>131,895,033(100%)</TD></TR></TABLE>
<P>""" + "다" * 100 + """</P></SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y">4. 영업부문 (연결)</TITLE><P>단일 영업부문 """ + "라" * 100 + """</P></SECTION-2>
<SECTION-2><TITLE ATOC="Y">5. 금융위험관리 (연결)</TITLE><P>""" + "마" * 200 + """</P></SECTION-2>
<SECTION-2><TITLE ATOC="Y">3. 영업부문</TITLE><P>별도 """ + "바" * 100 + """</P></SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y">IV. 이사의 경영진단 및 분석의견</TITLE>
<SECTION-2><TITLE ATOC="Y">1. 개요</TITLE><P>기업공시서식 작성기준에 따라 분기ㆍ반기보고서에 기재하지 않습니다.</P></SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y">XI. 그 밖에 투자자 보호를 위하여 필요한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y">3. 제재 등과 관련된 사항</TITLE><P>가동중지명령을 받았습니다 &amp; 개선 중 """ + "사" * 100 + """</P></SECTION-2></SECTION-1>
</BODY></DOCUMENT>"""


def test_report_sections_keep_narrative_chapters_and_tables():
    from app.services.dart_document import extract_sections
    sections = extract_sections(REPORT_XML)
    assert [s.path for s in sections] == [
        "II. 사업의 내용 > 1. 사업의 개요",
        "II. 사업의 내용 > 2. 주요 제품 및 서비스",
        "XI. 그 밖에 투자자 보호를 위하여 필요한 사항 > 3. 제재 등과 관련된 사항",
        "재무제표 주석 > 4. 영업부문 (연결)",  # 연결이 있으면 별도 영업부문은 뺀다
    ]  # 회사의 개요·금융위험관리 주석, 반기라 비어 있는 경영진단은 읽지 않는다
    assert "DRAM | 131,895,033(100%)" in sections[1].text
    assert "가동중지명령을 받았습니다 & 개선 중" in sections[2].text


def test_report_sections_are_clipped():
    from app.services import dart_document
    xml = REPORT_XML.replace("나" * 100, "나" * (dart_document.SECTION_CHARS + 500))
    text = dart_document.extract_sections(xml)[0].text
    assert len(text) < dart_document.SECTION_CHARS + 20 and text.endswith("(…이하 생략)")


class ReportDB(FakeDB):
    def __init__(self, rows, cached=None):
        super().__init__(rows)
        self.cached = cached
        self.saved = []

    def get(self, model, key):
        return self.cached if self.cached and self.cached.rcept_no == key else None

    def merge(self, obj):
        self.saved.append(obj)

    def expunge(self, obj):
        pass

    def commit(self):
        pass


def test_latest_report_is_the_newest_filing_and_prefers_the_disclosure_title():
    from app.services.answer.skills.company_report import latest_report
    rows = [_fin(2026, "11013", "매출액", 1, rcept="20260515000100"), _fin(2026, "11012", "매출액", 1, rcept="20260814000200"),
            _disc(60, "반기보고서 (2026.06)", "20260814000200"), _disc(30, "주요사항보고서(자기주식취득결정)", "20260901000300")]
    report = latest_report(ReportDB(rows), "005930")
    assert (report.rcept_no, report.report_nm, report.filed) == ("20260814000200", "2026년 반기보고서", "2026-08-14")
    rows.append(_disc(10, "[기재정정]반기보고서 (2026.06)", "20261009000400"))  # 정정본이 최신 보고서다
    assert latest_report(ReportDB(rows), "005930").report_nm == "2026년 반기보고서 (기재정정)"
    # 공시 목록(최근 90일 백필)에 없으면 주요계정의 접수번호로 찾는다
    assert latest_report(ReportDB(rows[:2]), "005930").report_nm == "2026년 반기보고서"
    assert latest_report(ReportDB([]), "005930") is None


def test_report_name_tells_first_and_third_quarter_apart():
    from app.services.answer.skills.company_report import report_name
    # 공시 제목은 1·3분기 모두 '분기보고서'다 — 주요계정의 보고서 코드가 있으면 그것을, 없으면 기간 끝 달을 본다
    assert report_name("분기보고서 (2026.03)", None) == "2026년 1분기보고서"
    assert report_name("분기보고서 (2025.09)", None) == "2025년 3분기보고서"
    assert report_name("분기보고서 (2026.03)", _fin(2025, "11014", "매출액", 1)) == "2025년 3분기보고서"
    assert report_name("[첨부정정]사업보고서 (2025.12)", None) == "2025년 사업보고서 (첨부정정)"


def test_company_report_summarizes_the_document_once_and_caches_it(fake_stock_graph, monkeypatch):
    from pydantic_ai.models.test import TestModel
    from app.models.dart import StockReportSummary
    from app.services.answer.skills import company_report

    class Config:
        llm_model = "test"

    prompts = []
    model = TestModel(custom_output_text="#### 사업 구조\n- 메모리 반도체")
    monkeypatch.setattr(company_report, "build_model", lambda config: model)
    monkeypatch.setattr(company_report, "load_dart_key", lambda db: "key")
    monkeypatch.setattr(company_report, "fetch_document", lambda key, no: prompts.append(no) or REPORT_XML)

    async def no_breakdowns(config, sections):
        return []
    monkeypatch.setattr(company_report.report_breakdowns, "extract", no_breakdowns)
    db = ReportDB([_disc(60, "반기보고서 (2026.06)", "20260814000200")])

    async def run():
        from app.services.answer.resolver import EntityResolver
        from app.services.answer.skills.base import SkillContext
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: db,
                           resolver=EntityResolver(), ai_config=Config(), stop=asyncio.Event())
        skill = REGISTRY["company_report"]
        return [e async for e in skill.run(skill.Args(stock="삼성전자"), "markdown", ctx)]

    events = asyncio.run(run())
    assert events[0] == {"type": "title", "title": "삼성전자 2026년 반기보고서 요약"}  # 영역 제목을 보고서 이름으로
    result = events[-1]
    assert result["status"] == "complete" and prompts == ["20260814000200"]
    streamed = "".join(e["text"] for e in events if e["type"] == "delta")
    assert streamed.strip() == result["content"]["text"].strip()  # 화면은 흘려받은 텍스트를 그대로 둔다
    assert "[DART 원문](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814000200)" in result["content"]["text"]
    assert result["summary"].startswith("삼성전자의 2026년 반기보고서 (2026-08-14 접수) 본문 요약:")
    assert "메모리 반도체" in result["summary"]
    saved = db.saved[0]
    assert saved.rcept_no == "20260814000200" and "II. 사업의 내용 > 1. 사업의 개요" in saved.sections

    assert saved.breakdowns == "[]"  # 매출 구성 표가 없었다는 것도 남겨 다시 뽑지 않는다
    db.cached = StockReportSummary(rcept_no="20260814000200", summary="#### 사업 구조\n- 캐시된 요약", breakdowns="[]")
    result = asyncio.run(run())[-1]
    assert "캐시된 요약" in result["content"]["text"] and prompts == ["20260814000200"]  # 원문을 다시 받지 않는다


def test_company_report_without_a_report_says_so(fake_stock_graph):
    result = _run("company_report", {"stock": "삼성전자"}, "markdown", lambda: ReportDB([]))
    assert result["status"] == "empty" and "정기보고서를 찾지 못했습니다" in result["message"]


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


def test_company_report_splits_into_revenue_mix_charts_and_the_summary(fake_stock_graph, monkeypatch):
    from app.models.dart import StockReportSummary
    from app.services.answer.skills import company_report
    from app.services.answer.skills.report_breakdowns import check

    mixes = [check(_mix("product", [("장비매출", "69,624,089"), ("부품매출", "4,991,080"), ("용역수익", "3,447,782")],
                        total="78,062,951"), MIX_SOURCE),
             check(_mix("customer", [("고객 A", "21,316,082"), ("고객 B", "5,619,282")]), MIX_SOURCE)]
    extracted = []

    async def extract(config, sections):
        extracted.append(len(sections))
        return mixes
    monkeypatch.setattr(company_report.report_breakdowns, "extract", extract)
    monkeypatch.setattr(company_report, "load_dart_key", lambda db: "key")
    monkeypatch.setattr(company_report, "fetch_document", lambda key, no: REPORT_XML)
    # 매출 구성을 뽑기 전에 요약만 남긴 보고서: 원문을 다시 읽어 구성만 뽑고 요약은 캐시를 쓴다
    db = ReportDB([_disc(60, "반기보고서 (2026.06)", "20260814000200")],
                  cached=StockReportSummary(rcept_no="20260814000200", summary="#### 사업 구조\n- 장비"))
    db.commit = lambda: None

    async def run():
        from app.services.answer.resolver import EntityResolver
        from app.services.answer.skills.base import SkillContext
        ctx = SkillContext(question="삼성전자 주 고객은?", conversation=ConversationContext(),
                           session_factory=lambda: db, resolver=EntityResolver(), ai_config=None, stop=asyncio.Event())
        skill = REGISTRY["company_report"]
        return [e async for e in skill.run(skill.Args(stock="삼성전자"), "markdown", ctx)]

    events = asyncio.run(run())
    split = events[0]
    assert split == {"type": "split", "parts": [
        {"id": "chart1", "title": "삼성전자 주요 고객별 매출 · 당반기", "display": "bar"},  # 질문이 고객을 묻는다
        {"id": "chart2", "title": "삼성전자 제품별 매출 · 당반기", "display": "donut"},
        {"id": "text", "title": "삼성전자 2026년 반기보고서 요약", "display": "markdown"},
    ]}
    results = {e["part"]: e for e in events if e["type"] == "result"}
    assert set(results) == {"chart1", "chart2", "text"}
    donut = results["chart2"]
    assert donut["content"]["view"]["kind"] == "donut"
    assert donut["summary"] == "삼성전자 제품별 매출 · 당반기: 장비매출 69,624,089천원(89.2%), 부품매출 4,991,080천원(6.4%), 용역수익 3,447,782천원(4.4%)"
    assert results["chart1"]["content"]["notes"]  # 막대는 합이 전체가 아니라고 밝힌다
    assert "장비" in results["text"]["content"]["text"]
    assert extracted  # 요약은 캐시에 있어도 원문을 읽어 구성을 뽑았다
    assert db.cached.breakdowns and "고객 A" in db.cached.breakdowns  # 뽑은 구성을 캐시에 남긴다
