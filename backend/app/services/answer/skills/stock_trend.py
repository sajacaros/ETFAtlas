from typing import Dict, List

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....domain.periods import Period
from ...entities import EntityResolver
from ...graph_service import GraphService
from .common import DEFAULT_PERIOD, PERIOD_DESCRIPTION
from .price_trend import PriceTrendBase


class StockTrendArgs(BaseModel):
    stocks: List[str] = Field(min_length=1, max_length=5, description="종목 이름 또는 6자리 코드 (예: '삼성전자')")
    period: Period = Field(DEFAULT_PERIOD, description=PERIOD_DESCRIPTION)


class StockTrendSkill(PriceTrendBase):
    name = "stock_trend"
    description = (
        "개별 주식 종목(삼성전자 등, ETF 아님)의 가격 추이. 여럿이면 시작일 대비 누적 수익률(%)로 겹쳐 그린다. "
        "candlestick은 종목 하나의 일별 시가·고가·저가·종가와 거래량, table은 종목별 기간 요약. "
        "주가 분석·차트 분석·보조지표는 stock_technical"
    )
    Args = StockTrendArgs
    tool = True
    target = "종목"
    subject = "stock"
    entity_args = {"stocks": "stock"}

    def targets(self, args: StockTrendArgs, db: Session, resolver: EntityResolver):
        return resolver.stocks(db, args.stocks)

    def prices(self, graph: GraphService, code: str, days: int) -> List[Dict]:
        return graph.get_stock_prices(code, days=days)
