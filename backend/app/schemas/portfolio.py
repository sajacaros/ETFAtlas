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


class PortfolioResponse(BaseModel):
    id: int
    name: str
    calculation_base: str
    target_total_amount: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    current_value_date: Optional[str] = None
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


# --- Backfill ---
class BackfillSnapshotResponse(BaseModel):
    created: int
