from app.models.portfolio import SharedPortfolio
from app.routers.portfolio import _is_same_snapshot

ALLOCATIONS = [{"ticker": "069500", "weight": 60.0}, {"ticker": "CASH", "weight": 40.0}]


def _shared(name="성장형", account_types=("IRP",), allocations=ALLOCATIONS):
    return SharedPortfolio(name=name, account_types=list(account_types), allocations=allocations)


def test_identical_snapshot_is_reused():
    assert _is_same_snapshot("성장형", ["IRP"], list(reversed(ALLOCATIONS)), _shared())
    both = _shared(account_types=("IRP", "PENSION_SAVINGS"))
    assert _is_same_snapshot("성장형", ["PENSION_SAVINGS", "IRP"], ALLOCATIONS, both)


def test_any_change_needs_new_snapshot():
    assert not _is_same_snapshot("안정형", ["IRP"], ALLOCATIONS, _shared())
    assert not _is_same_snapshot("성장형", ["PENSION_SAVINGS"], ALLOCATIONS, _shared())
    assert not _is_same_snapshot("성장형", ["IRP", "PENSION_SAVINGS"], ALLOCATIONS, _shared())
    assert not _is_same_snapshot("성장형", ["IRP"], [{"ticker": "069500", "weight": 60.5}, {"ticker": "CASH", "weight": 39.5}], _shared())
    assert not _is_same_snapshot("성장형", ["IRP"], ALLOCATIONS[:1], _shared())
    assert not _is_same_snapshot("성장형", ["IRP"], ALLOCATIONS + [{"ticker": "360750", "weight": 0.0}], _shared())


def test_account_types_need_at_least_one_and_are_normalized():
    import pytest
    from pydantic import ValidationError
    from app.schemas.portfolio import PortfolioCreate, PortfolioUpdate

    assert PortfolioCreate().account_types == ["PENSION_SAVINGS"]
    req = PortfolioCreate(account_types=["PENSION_SAVINGS", "IRP", "IRP"])
    assert req.account_types == ["IRP", "PENSION_SAVINGS"]
    assert PortfolioUpdate().account_types is None
    for bad in ([], ["ISA"]):
        with pytest.raises(ValidationError):
            PortfolioCreate(account_types=bad)
        with pytest.raises(ValidationError):
            PortfolioUpdate(account_types=bad)
