from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


# --- Portfolio ---
class PortfolioCreate(BaseModel):
    name: str = "My Portfolio"
    calculation_base: str = "CURRENT_TOTAL"
    target_total_amount: Optional[Decimal] = None


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    calculation_base: Optional[str] = None
    target_total_amount: Optional[Decimal] = None


class PortfolioReorderItem(BaseModel):
    id: int
    display_order: int


class PortfolioReorderRequest(BaseModel):
    orders: list[PortfolioReorderItem]


class PortfolioResponse(BaseModel):
    id: int
    name: str
    calculation_base: str
    target_total_amount: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    current_value_date: Optional[str] = None
    current_value_updated_at: Optional[str] = None
    daily_change_amount: Optional[Decimal] = None
    daily_change_rate: Optional[float] = None
    invested_amount: Optional[Decimal] = None
    investment_return_rate: Optional[float] = None

    class Config:
        from_attributes = True


# --- Target Allocation ---
class TargetAllocationCreate(BaseModel):
    ticker: str
    target_weight: Decimal


class TargetAllocationUpdate(BaseModel):
    target_weight: Decimal


class TargetAllocationResponse(BaseModel):
    id: int
    portfolio_id: int
    ticker: str
    target_weight: Decimal

    class Config:
        from_attributes = True


# --- Holding ---
class HoldingCreate(BaseModel):
    ticker: str
    quantity: Decimal = Decimal("0")
    avg_price: Optional[Decimal] = None


class HoldingUpdate(BaseModel):
    quantity: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None


class HoldingResponse(BaseModel):
    id: int
    portfolio_id: int
    ticker: str
    quantity: Decimal
    avg_price: Optional[Decimal] = None

    class Config:
        from_attributes = True


# --- Calculation ---
class CalculationRowResponse(BaseModel):
    ticker: str
    name: str
    target_weight: Decimal
    current_price: Decimal
    target_amount: Decimal
    target_quantity: Decimal
    holding_quantity: Decimal
    holding_amount: Decimal
    required_quantity: Decimal
    adjustment_amount: Decimal
    status: str  # BUY / SELL / HOLD
    avg_price: Optional[Decimal] = None
    profit_loss_rate: Optional[Decimal] = None
    profit_loss_amount: Optional[Decimal] = None
    price_change_rate: Optional[Decimal] = None


class CalculationResponse(BaseModel):
    rows: list[CalculationRowResponse]
    base_amount: Decimal
    total_weight: Decimal
    total_holding_amount: Decimal
    total_adjustment_amount: Decimal
    total_profit_loss_amount: Optional[Decimal] = None
    weight_warning: Optional[str] = None


# --- Portfolio Detail ---
class PortfolioDetailResponse(BaseModel):
    id: int
    name: str
    calculation_base: str
    target_total_amount: Optional[Decimal] = None
    is_shared: bool = False
    share_token: Optional[str] = None
    target_allocations: list[TargetAllocationResponse] = []
    holdings: list[HoldingResponse] = []

    class Config:
        from_attributes = True


# --- Dashboard ---
class DashboardSummaryItem(BaseModel):
    amount: Decimal
    rate: float


class DashboardSummary(BaseModel):
    current_value: Decimal
    cumulative: DashboardSummaryItem
    daily: Optional[DashboardSummaryItem] = None
    monthly: Optional[DashboardSummaryItem] = None
    yearly: Optional[DashboardSummaryItem] = None
    ytd: Optional[DashboardSummaryItem] = None
    invested_amount: Optional[Decimal] = None
    investment_return: Optional[DashboardSummaryItem] = None
    snapshot_date: Optional[str] = None
    updated_at: Optional[str] = None


class ChartDataPoint(BaseModel):
    date: str
    total_value: Decimal
    cumulative_rate: float


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    chart_data: list[ChartDataPoint]


# --- Total Holdings ---
class TotalHoldingItem(BaseModel):
    ticker: str
    name: str
    quantity: Decimal
    current_price: Decimal
    value: Decimal
    weight: float


class TotalHoldingsResponse(BaseModel):
    holdings: list[TotalHoldingItem]
    total_value: Decimal


# --- Batch Update ---
class BatchTargetItem(BaseModel):
    ticker: str
    target_weight: Decimal


class BatchHoldingItem(BaseModel):
    ticker: str
    quantity: Decimal
    avg_price: Optional[Decimal] = None


class PortfolioBatchUpdate(BaseModel):
    name: Optional[str] = None
    calculation_base: Optional[str] = None
    target_total_amount: Optional[Decimal] = None
    targets: list[BatchTargetItem]
    holdings: list[BatchHoldingItem]


# --- Backfill ---
class BackfillSnapshotResponse(BaseModel):
    created: int


# --- Refresh Snapshot ---
class RefreshSnapshotResponse(BaseModel):
    date: str
    total_value: Decimal
    change_amount: Optional[Decimal] = None
    change_rate: Optional[float] = None


class RefreshAllSnapshotsResponse(BaseModel):
    refreshed: int
    skipped: int


# --- Sharing ---
class ShareToggleRequest(BaseModel):
    is_shared: bool


class ShareToggleResponse(BaseModel):
    is_shared: bool
    share_token: Optional[str] = None
    share_url: Optional[str] = None


class SharedPortfolioListItem(BaseModel):
    portfolio_name: str
    user_name: str
    share_token: str
    tickers_count: int
    updated_at: Optional[str] = None


class SharedAllocationItem(BaseModel):
    ticker: str
    name: str
    weight: float


class SharedPortfolioDetail(BaseModel):
    portfolio_name: str
    user_name: str
    allocations: list[SharedAllocationItem]


class SharedReturnsChartPoint(BaseModel):
    date: str
    value: float


class SharedReturnsResponse(BaseModel):
    base_amount: int = 10_000_000
    period: str
    actual_start_date: str
    chart_data: list[SharedReturnsChartPoint]
