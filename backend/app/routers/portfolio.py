from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from decimal import Decimal
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation, Holding
from ..utils.jwt import get_current_user_id
from ..schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    TargetAllocationCreate, TargetAllocationUpdate, TargetAllocationResponse,
    HoldingCreate, HoldingUpdate, HoldingResponse,
    CalculationResponse, CalculationRowResponse,
    PortfolioDetailResponse,
)
from ..domain.portfolio_calculation import (
    calculate_portfolio, TargetInput, HoldingInput,
)
from ..services.price_service import PriceService

router = APIRouter()


def _get_portfolio_or_404(db: Session, portfolio_id: int, user_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == user_id
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


# --- Portfolio CRUD ---

@router.get("/", response_model=List[PortfolioResponse])
async def get_portfolios(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()
    return portfolios


@router.post("/", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    request: PortfolioCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = Portfolio(
        user_id=user_id,
        name=request.name,
        calculation_base=request.calculation_base,
        target_total_amount=request.target_total_amount,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    return portfolio


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int,
    request: PortfolioUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    if request.name is not None:
        portfolio.name = request.name
    if request.calculation_base is not None:
        portfolio.calculation_base = request.calculation_base
    if request.target_total_amount is not None:
        portfolio.target_total_amount = request.target_total_amount
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    db.delete(portfolio)
    db.commit()


# --- Target Allocations ---

@router.post("/{portfolio_id}/targets", response_model=TargetAllocationResponse, status_code=status.HTTP_201_CREATED)
async def add_target(
    portfolio_id: int,
    request: TargetAllocationCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    existing = db.query(TargetAllocation).filter(
        TargetAllocation.portfolio_id == portfolio.id,
        TargetAllocation.ticker == request.ticker
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Target allocation already exists for this ticker")

    allocation = TargetAllocation(
        portfolio_id=portfolio.id,
        ticker=request.ticker,
        target_weight=request.target_weight,
    )
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return allocation


@router.put("/{portfolio_id}/targets/{target_id}", response_model=TargetAllocationResponse)
async def update_target(
    portfolio_id: int,
    target_id: int,
    request: TargetAllocationUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.id == target_id,
        TargetAllocation.portfolio_id == portfolio.id
    ).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Target allocation not found")

    allocation.target_weight = request.target_weight
    db.commit()
    db.refresh(allocation)
    return allocation


@router.delete("/{portfolio_id}/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    portfolio_id: int,
    target_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.id == target_id,
        TargetAllocation.portfolio_id == portfolio.id
    ).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Target allocation not found")

    db.delete(allocation)
    db.commit()


# --- Holdings ---

@router.post("/{portfolio_id}/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
async def add_holding(
    portfolio_id: int,
    request: HoldingCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    existing = db.query(Holding).filter(
        Holding.portfolio_id == portfolio.id,
        Holding.ticker == request.ticker
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Holding already exists for this ticker")

    holding = Holding(
        portfolio_id=portfolio.id,
        ticker=request.ticker,
        quantity=request.quantity,
    )
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return holding


@router.put("/{portfolio_id}/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(
    portfolio_id: int,
    holding_id: int,
    request: HoldingUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.portfolio_id == portfolio.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    holding.quantity = request.quantity
    db.commit()
    db.refresh(holding)
    return holding


@router.delete("/{portfolio_id}/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    portfolio_id: int,
    holding_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.portfolio_id == portfolio.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    db.delete(holding)
    db.commit()


# --- Calculation ---

@router.get("/{portfolio_id}/calculate", response_model=CalculationResponse)
async def calculate(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # Gather data
    target_allocations = db.query(TargetAllocation).filter(
        TargetAllocation.portfolio_id == portfolio.id
    ).all()
    holdings = db.query(Holding).filter(
        Holding.portfolio_id == portfolio.id
    ).all()

    # Build inputs
    targets = [
        TargetInput(ticker=ta.ticker, target_weight=Decimal(str(ta.target_weight)))
        for ta in target_allocations
    ]
    holding_inputs = [
        HoldingInput(ticker=h.ticker, quantity=Decimal(str(h.quantity)))
        for h in holdings
    ]

    # All tickers
    all_tickers = list(set(
        [ta.ticker for ta in target_allocations] +
        [h.ticker for h in holdings]
    ))

    # Get prices and names
    price_service = PriceService(db)
    prices = price_service.get_prices(all_tickers)
    etf_names = price_service.get_etf_names(all_tickers)

    # Calculate
    result = calculate_portfolio(
        targets=targets,
        holdings=holding_inputs,
        prices=prices,
        etf_names=etf_names,
        calculation_base=portfolio.calculation_base,
        target_total_amount=Decimal(str(portfolio.target_total_amount)) if portfolio.target_total_amount else None,
    )

    # Convert to response
    return CalculationResponse(
        rows=[
            CalculationRowResponse(
                ticker=row.ticker,
                name=row.name,
                target_weight=row.target_weight,
                current_price=row.current_price,
                target_amount=row.target_amount,
                target_quantity=row.target_quantity,
                holding_quantity=row.holding_quantity,
                holding_amount=row.holding_amount,
                required_quantity=row.required_quantity,
                adjustment_amount=row.adjustment_amount,
                status=row.status,
            )
            for row in result.rows
        ],
        base_amount=result.base_amount,
        total_weight=result.total_weight,
        total_holding_amount=result.total_holding_amount,
        total_adjustment_amount=result.total_adjustment_amount,
        weight_warning=result.weight_warning,
    )
