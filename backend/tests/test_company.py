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
