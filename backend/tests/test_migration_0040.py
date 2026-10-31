"""0040 데이터 마이그레이션: 옛 도구 호출을 새 스킬 도구 호출로 바꾸는 규칙"""
import importlib.util
from pathlib import Path

import pytest

from tests.test_code_examples import _agent_tools, _calls

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0040_code_examples_skill_tools.py"


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig_0040", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid(code):
    custom, skills = _agent_tools()
    for line, name, args in _calls(code):
        assert name in custom or name in skills, line
        if name in skills:
            skills[name].model_validate(args)


def test_each_old_call_converts_to_a_valid_new_call(mig):
    code = "\n".join([
        'etf_search(query="<ETF명>")',
        "# 결과 ETF마다",
        'get_etf_info(etf_code="069500")',
        'get_etf_prices(etf_code="<ETF의 code>", period="1w")',
        'get_etf_prices(etf_code="069500")',
        'get_stock_prices(stock_code="005930", period="3m")',
        'compare_etfs(etf_codes="069500, 102110")',
        'compare_etfs(etf_codes="<유사 ETF 5개의 code, 쉼표 구분>")',
    ])
    new = mig.convert_code(code)
    assert new.splitlines() == [
        'etf_search(query="<ETF명>")',
        "# 결과 ETF마다",
        'etf_compare(etfs=["069500"])',
        'price_trend(etfs=["<ETF의 code>"], period="1w")',
        'price_trend(etfs=["069500"])',
        'stock_trend(stocks=["005930"], period="3m")',
        'etf_compare(etfs=["069500", "102110"])',
        'etf_compare(etfs=["<유사 ETF 5개의 code, 쉼표 구분>"])',
    ]
    _valid(new)


def test_unknown_shapes_are_refused(mig):
    with pytest.raises(ValueError):
        mig.convert_line('get_etf_info(code="069500")')


def test_seed_rewrites_are_valid_and_cover_every_old_call(mig):
    for pair in mig.SEED_REWRITES:
        assert mig.OLD_CALL.search(pair["old"])
        assert not mig.OLD_CALL.search(pair["new"])
        _valid(pair["new"])
        _valid(mig.convert_code(pair["old"]))  # 시드와 달라진 행이 와도 규칙 변환으로 맞는 호출이 된다
