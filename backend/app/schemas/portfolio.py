from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer
from typing import Annotated, Literal, Optional
from decimal import Decimal

# 금액·수량·비중. 계산은 Decimal로 하고 JSON에는 숫자로 내보낸다 (Pydantic 기본값은 문자열)
Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


AccountType = Literal["IRP", "PENSION_SAVINGS"]
CalculationBase = Literal["CURRENT_TOTAL", "TARGET_AMOUNT"]
ACCOUNT_TYPE_ORDER: tuple[str, ...] = ("IRP", "PENSION_SAVINGS")


def normalize_account_types(types: list[str]) -> list[str]:
    """중복을 없애고 정해진 순서로 맞춘다. 같은 태그 묶음이면 늘 같은 값이 된다."""
    return [t for t in ACCOUNT_TYPE_ORDER if t in types]


# 계좌 유형 태그는 최소 1개
AccountTypes = Annotated[list[AccountType], Field(min_length=1), AfterValidator(normalize_account_types)]


class TargetAllocationCreate(BaseModel):
    ticker: str
    target_weight: Num


# --- Portfolio ---
class PortfolioCreate(BaseModel):
    name: str = "My Portfolio"
    account_types: AccountTypes = ["PENSION_SAVINGS"]
    calculation_base: CalculationBase = "CURRENT_TOTAL"
    target_total_amount: Optional[Num] = None
    targets: list[TargetAllocationCreate] = []  # 구성종목 분석에서 저장할 때 목표 비중을 함께 넣는다


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    account_types: Optional[AccountTypes] = None
    calculation_base: Optional[CalculationBase] = None
    target_total_amount: Optional[Num] = None
    snapshot_enabled: Optional[bool] = None


class PortfolioReorderItem(BaseModel):
    id: int
    display_order: int


class PortfolioReorderRequest(BaseModel):
    orders: list[PortfolioReorderItem]


class PortfolioResponse(BaseModel):
    id: int
    name: str
    account_types: list[AccountType]
    calculation_base: CalculationBase
    target_total_amount: Optional[Num] = None
    current_value: Optional[Num] = None
    current_value_date: Optional[str] = None
    current_value_updated_at: Optional[str] = None
    daily_change_amount: Optional[Num] = None
    daily_change_rate: Optional[float] = None
    invested_amount: Optional[Num] = None
    investment_return_rate: Optional[float] = None
    snapshot_enabled: bool = False

    model_config = ConfigDict(from_attributes=True)


# --- Target Allocation ---
class TargetAllocationUpdate(BaseModel):
    target_weight: Num


class TargetAllocationResponse(BaseModel):
    id: int
    portfolio_id: int
    ticker: str
    target_weight: Num

    model_config = ConfigDict(from_attributes=True)


# --- Holding ---
class HoldingCreate(BaseModel):
    ticker: str
    quantity: Num = Decimal("0")
    avg_price: Optional[Num] = None


class HoldingUpdate(BaseModel):
    quantity: Optional[Num] = None
    avg_price: Optional[Num] = None


class HoldingResponse(BaseModel):
    id: int
    portfolio_id: int
    ticker: str
    quantity: Num
    avg_price: Optional[Num] = None

    model_config = ConfigDict(from_attributes=True)


# --- Calculation ---
class CalculationRowResponse(BaseModel):
    ticker: str
    name: str
    target_weight: Num
    current_price: Num
    target_amount: Num
    target_quantity: Num
    holding_quantity: Num
    holding_amount: Num
    required_quantity: Num
    adjustment_amount: Num
    status: str  # BUY / SELL / HOLD
    avg_price: Optional[Num] = None
    profit_loss_rate: Optional[Num] = None
    profit_loss_amount: Optional[Num] = None
    price_change_rate: Optional[Num] = None


class CalculationResponse(BaseModel):
    rows: list[CalculationRowResponse]
    base_amount: Num
    total_weight: Num
    total_holding_amount: Num
    total_adjustment_amount: Num
    total_profit_loss_amount: Optional[Num] = None
    weight_warning: Optional[str] = None


# --- Portfolio Detail ---
class PortfolioDetailResponse(BaseModel):
    id: int
    name: str
    account_types: list[AccountType]
    calculation_base: CalculationBase
    target_total_amount: Optional[Num] = None
    snapshot_enabled: bool = False
    target_allocations: list[TargetAllocationResponse] = []
    holdings: list[HoldingResponse] = []

    model_config = ConfigDict(from_attributes=True)


# --- Dashboard ---
class DashboardSummaryItem(BaseModel):
    amount: Num
    rate: float


class DashboardSummary(BaseModel):
    current_value: Num
    cumulative: DashboardSummaryItem
    daily: Optional[DashboardSummaryItem] = None
    monthly: Optional[DashboardSummaryItem] = None
    yearly: Optional[DashboardSummaryItem] = None
    ytd: Optional[DashboardSummaryItem] = None
    invested_amount: Optional[Num] = None
    investment_return: Optional[DashboardSummaryItem] = None
    snapshot_date: Optional[str] = None
    updated_at: Optional[str] = None


class ChartDataPoint(BaseModel):
    date: str
    total_value: Num
    cumulative_rate: float


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    chart_data: list[ChartDataPoint]


# --- Total Holdings ---
class TotalHoldingItem(BaseModel):
    ticker: str
    name: str
    quantity: Num
    current_price: Num
    value: Num
    weight: float


class TotalHoldingsResponse(BaseModel):
    holdings: list[TotalHoldingItem]
    total_value: Num


# --- Batch Update ---
class BatchTargetItem(BaseModel):
    ticker: str
    target_weight: Num


class BatchHoldingItem(BaseModel):
    ticker: str
    quantity: Num
    avg_price: Optional[Num] = None


class PortfolioBatchUpdate(BaseModel):
    name: Optional[str] = None
    account_types: Optional[AccountTypes] = None
    calculation_base: Optional[CalculationBase] = None
    target_total_amount: Optional[Num] = None
    targets: list[BatchTargetItem]
    holdings: list[BatchHoldingItem]




# --- Sharing ---
class ShareCreateResponse(BaseModel):
    share_token: str
    share_url: str
    created: bool  # False면 똑같은 구성의 기존 공유본을 돌려준 것


class SharedAllocationItem(BaseModel):
    ticker: str
    name: str
    weight: float


class SharedPortfolioListItem(BaseModel):
    portfolio_name: str
    account_types: list[AccountType]
    share_token: str
    tickers_count: int
    owner_id: int
    owner_name: str
    shared_at: Optional[str] = None
    is_owner: bool = False


class SharedPortfolioDetail(BaseModel):
    portfolio_name: str
    account_types: list[AccountType]
    allocations: list[SharedAllocationItem]
    owner_name: str
    shared_at: Optional[str] = None
    is_owner: bool = False


class SharedReturnsChartPoint(BaseModel):
    date: str
    value: float


class SharedReturnsResponse(BaseModel):
    base_amount: int = 10_000_000
    period: str
    actual_start_date: str
    chart_data: list[SharedReturnsChartPoint]


class SharedReturnsSummary(BaseModel):
    returns_1w: Optional[float] = None
    returns_1m: Optional[float] = None
    returns_3m: Optional[float] = None


# --- Risk Analysis ---
class RiskChartPoint(BaseModel):
    date: str
    value: float
    return_rate: float


class DrawdownPoint(BaseModel):
    date: str
    drawdown: float


class RiskAnalysisResponse(BaseModel):
    period: str
    actual_start_date: str
    total_return: float
    mdd: float
    volatility: float
    sharpe_ratio: Optional[float] = None
    chart_data: list[RiskChartPoint]
    drawdown_data: list[DrawdownPoint]
