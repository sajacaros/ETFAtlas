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


class HoldingUpdate(BaseModel):
    quantity: Decimal


class HoldingResponse(BaseModel):
    id: int
    portfolio_id: int
    ticker: str
    quantity: Decimal

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


class CalculationResponse(BaseModel):
    rows: list[CalculationRowResponse]
    base_amount: Decimal
    total_weight: Decimal
    total_holding_amount: Decimal
    total_adjustment_amount: Decimal
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
