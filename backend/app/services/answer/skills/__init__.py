"""등록된 스킬. 새 기능은 스킬을 만들어 여기에 올리면 레이아웃 에이전트의 선택지에 바로 들어간다."""
from typing import Dict

from .agent import AgentSkill
from .base import Skill
from .company_disclosures import CompanyDisclosuresSkill
from .company_financials import CompanyFinancialsSkill
from .company_report import CompanyReportSkill
from .company_type import CompanyTypeSkill
from .company_revenue_mix import CompanyRevenueMixSkill
from .company_valuation import CompanyValuationSkill
from .etf_choice import ETFChoiceSkill
from .etf_compare import ETFCompareSkill
from .etf_profile import ETFProfileSkill
from .holdings import HoldingsSkill
from .narrative import NarrativeSkill
from .overlap import OverlapSkill
from .period_returns import PeriodReturnsSkill
from .portfolio_lookthrough import PortfolioLookthroughSkill
from .price_trend import PriceTrendSkill
from .rank import RankSkill
from .stock_holders import StockHoldersSkill
from .stock_opinion import StockOpinionSkill
from .stock_technical import StockTechnicalSkill
from .stock_trend import StockTrendSkill

REGISTRY: Dict[str, Skill] = {
    s.name: s
    for s in (
        PriceTrendSkill(),
        PeriodReturnsSkill(),
        ETFCompareSkill(),
        ETFProfileSkill(),
        HoldingsSkill(),
        PortfolioLookthroughSkill(),
        StockTrendSkill(),
        StockTechnicalSkill(),
        StockHoldersSkill(),
        CompanyFinancialsSkill(),
        CompanyValuationSkill(),
        CompanyTypeSkill(),
        CompanyDisclosuresSkill(),
        CompanyReportSkill(),
        CompanyRevenueMixSkill(),
        StockOpinionSkill(),
        RankSkill(),
        OverlapSkill(),
        ETFChoiceSkill(),
        NarrativeSkill(),
        AgentSkill(),
    )
}

FALLBACK_SKILL = "agent"  # 레이아웃 설계에 실패하면 질문 전체를 이 스킬 하나로 처리한다
