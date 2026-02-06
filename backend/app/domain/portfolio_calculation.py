from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


@dataclass
class TargetInput:
    ticker: str
    target_weight: Decimal  # percentage, e.g. 30.0 for 30%


@dataclass
class HoldingInput:
    ticker: str
    quantity: Decimal


@dataclass
class CalculationRow:
    ticker: str
    name: str
    target_weight: Decimal         # %
    current_price: Decimal
    target_amount: Decimal
    target_quantity: Decimal        # rounded integer
    holding_quantity: Decimal
    holding_amount: Decimal         # = quantity * price
    required_quantity: Decimal      # = target_qty - holding_qty
    adjustment_amount: Decimal      # = required_qty * price
    status: str                     # BUY / SELL / HOLD


@dataclass
class CalculationResult:
    rows: list[CalculationRow] = field(default_factory=list)
    base_amount: Decimal = Decimal("0")
    total_weight: Decimal = Decimal("0")
    total_holding_amount: Decimal = Decimal("0")
    total_adjustment_amount: Decimal = Decimal("0")
    weight_warning: Optional[str] = None


CASH_TICKER = "CASH"
CASH_PRICE = Decimal("1")


def calculate_portfolio(
    targets: list[TargetInput],
    holdings: list[HoldingInput],
    prices: dict[str, Decimal],
    etf_names: dict[str, str],
    calculation_base: str,
    target_total_amount: Optional[Decimal],
) -> CalculationResult:
    """
    Pure calculation function for portfolio rebalancing.

    Args:
        targets: list of target allocations
        holdings: list of actual holdings
        prices: {ticker: current_price}
        etf_names: {ticker: display_name}
        calculation_base: 'CURRENT_TOTAL' or 'TARGET_AMOUNT'
        target_total_amount: user-input target amount (for TARGET_AMOUNT mode)

    Returns:
        CalculationResult with per-row detail and totals
    """
    # Build lookup maps
    target_map: dict[str, Decimal] = {t.ticker: t.target_weight for t in targets}
    holding_map: dict[str, Decimal] = {h.ticker: h.quantity for h in holdings}

    # Union of all tickers (target OR holding)
    all_tickers = sorted(set(target_map.keys()) | set(holding_map.keys()))

    # Inject CASH price
    prices = dict(prices)  # copy
    prices[CASH_TICKER] = CASH_PRICE

    # Step 1: Determine base amount
    if calculation_base == "TARGET_AMOUNT" and target_total_amount is not None:
        base_amount = target_total_amount
    else:
        # CURRENT_TOTAL: sum of (quantity * price) for all holdings
        base_amount = Decimal("0")
        for ticker in all_tickers:
            qty = holding_map.get(ticker, Decimal("0"))
            price = prices.get(ticker, Decimal("0"))
            base_amount += qty * price

    # Step 2: Build rows
    rows: list[CalculationRow] = []
    total_weight = Decimal("0")
    total_holding_amount = Decimal("0")
    total_adjustment_amount = Decimal("0")

    for ticker in all_tickers:
        weight = target_map.get(ticker, Decimal("0"))
        qty = holding_map.get(ticker, Decimal("0"))
        price = prices.get(ticker, Decimal("0"))
        name = etf_names.get(ticker, ticker)

        # Target
        target_amount = (base_amount * weight / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        if price > 0:
            if ticker == CASH_TICKER:
                target_quantity = target_amount  # CASH: quantity = amount
            else:
                target_quantity = (target_amount / price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            target_quantity = Decimal("0")

        # Holding
        holding_amount = (qty * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        # Diff
        required_quantity = target_quantity - qty
        adjustment_amount = (required_quantity * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        # Status
        if required_quantity > 0:
            status = "BUY"
        elif required_quantity < 0:
            status = "SELL"
        else:
            status = "HOLD"

        total_weight += weight
        total_holding_amount += holding_amount
        total_adjustment_amount += adjustment_amount

        rows.append(CalculationRow(
            ticker=ticker,
            name=name,
            target_weight=weight,
            current_price=price,
            target_amount=target_amount,
            target_quantity=target_quantity,
            holding_quantity=qty,
            holding_amount=holding_amount,
            required_quantity=required_quantity,
            adjustment_amount=adjustment_amount,
            status=status,
        ))

    # Weight warning
    weight_warning = None
    if total_weight != Decimal("100") and len(targets) > 0:
        weight_warning = f"목표 비중 합계가 {total_weight}%입니다 (100%가 아님)"

    return CalculationResult(
        rows=rows,
        base_amount=base_amount,
        total_weight=total_weight,
        total_holding_amount=total_holding_amount,
        total_adjustment_amount=total_adjustment_amount,
        weight_warning=weight_warning,
    )
