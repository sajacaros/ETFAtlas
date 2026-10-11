from typing import Dict, List, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from .price_trend import PriceTrendBase


class StockTrendArgs(BaseModel):
    stocks: List[str] = Field(min_length=1, max_length=5, description="종목 이름 또는 6자리 코드 (예: '삼성전자')")
    period: Literal["1w", "1m", "3m", "6m", "1y"] = Field("3m", description="조회 기간")


class StockTrendSkill(PriceTrendBase):
    name = "stock_trend"
    description = (
        "개별 주식 종목(삼성전자 등, ETF 아님)의 가격 추이. 여럿이면 시작일 대비 누적 수익률(%)로 겹쳐 그린다. "
        "candlestick은 종목 하나의 일별 시가·고가·저가·종가와 거래량, table은 종목별 기간 요약"
    )
    Args = StockTrendArgs
    target = "종목"

    def targets(self, args: StockTrendArgs, db: Session, resolver: EntityResolver):
        return resolver.stocks(db, args.stocks)

    def prices(self, graph: GraphService, code: str, days: int) -> List[Dict]:
        return graph.get_stock_prices(code, days=days)
