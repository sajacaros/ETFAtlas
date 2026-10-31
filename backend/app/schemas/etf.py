"""ETF·태그·즐겨찾기 API 응답 스키마"""
from typing import List

from pydantic import BaseModel, Field


class ETFResponse(BaseModel):
    code: str
    name: str
    issuer: str | None = None
    net_assets: int | None = None
    expense_ratio: float | None = None
    description: str | None = None
    base_index: str | None = None
    listed_date: str | None = None
    dividend_cycle: int | None = None
    dividend_yield: float | None = None  # 최근 12개월 분배율(%) = 12개월 주당 분배금 ÷ 현재가
    dividend_per_share: int | None = None  # 최근 12개월 주당 분배금(원)
    component_count: int | None = None  # 전체 구성종목 수 (보유종목은 상위 30개까지만 수집)
    active: bool | None = None  # 액티브 ETF 여부 (KIS 분류), 모르면 None


class ETFHoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    sector: str | None = None
    weight: float
    shares: int | None = None
    recorded_at: str | None = None


class HoldingChangeResponse(BaseModel):
    stock_code: str
    stock_name: str
    change_type: str
    current_weight: float
    previous_weight: float
    weight_change: float


class ActiveChangeResponse(HoldingChangeResponse):
    etf_code: str
    etf_name: str
    prev_date: str


class ActiveChangesResponse(BaseModel):
    current_date: str | None = None
    previous_date: str | None = None
    threshold: float
    added_threshold: float
    changes: List[ActiveChangeResponse]


class PriceResponse(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    market_cap: int | None = None
    net_assets: int | None = None


class SimilarETFResponse(BaseModel):
    etf_code: str
    name: str
    overlap: int
    similarity: float


class ETFListItem(BaseModel):
    """ETF 목록 한 줄 (홈·태그·즐겨찾기)"""
    code: str
    name: str
    net_assets: int | None = None
    return_1d: float | None = None
    return_1w: float | None = None
    return_1m: float | None = None
    market_cap_change_1w: float | None = None
    active: bool | None = None


class ETFSearchResponse(BaseModel):
    code: str
    name: str


class CompositionItem(BaseModel):
    code: str
    weight: float = Field(ge=0)


class CompositionRequest(BaseModel):
    items: List[CompositionItem] = Field(max_length=50)


class CompositionETF(BaseModel):
    code: str
    name: str
    weight: float


class CompositionStock(BaseModel):
    rank: int
    stock_code: str
    stock_name: str
    weight: float
    etfs: List[CompositionETF]


class CompositionResponse(BaseModel):
    stocks: List[CompositionStock]
    total_stocks: int
    as_of: str | None = None


class TagResponse(BaseModel):
    name: str
    etf_count: int


class TagHoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    weight: float


class WatchlistItemResponse(BaseModel):
    etf_code: str
    etf_name: str
    category: str | None = None
