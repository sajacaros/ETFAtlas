from app.models.portfolio import SharedPortfolio
from app.routers.portfolio import _is_same_snapshot

ALLOCATIONS = [{"ticker": "069500", "weight": 60.0}, {"ticker": "CASH", "weight": 40.0}]


def _shared(name="성장형", allocations=ALLOCATIONS):
    return SharedPortfolio(name=name, allocations=allocations)


def test_identical_snapshot_is_reused():
    assert _is_same_snapshot("성장형", list(reversed(ALLOCATIONS)), _shared())


def test_any_change_needs_new_snapshot():
    assert not _is_same_snapshot("안정형", ALLOCATIONS, _shared())
    assert not _is_same_snapshot("성장형", [{"ticker": "069500", "weight": 60.5}, {"ticker": "CASH", "weight": 39.5}], _shared())
    assert not _is_same_snapshot("성장형", ALLOCATIONS[:1], _shared())
    assert not _is_same_snapshot("성장형", ALLOCATIONS + [{"ticker": "360750", "weight": 0.0}], _shared())
