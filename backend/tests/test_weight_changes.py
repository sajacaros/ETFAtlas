from app.services.weight_changes import is_significant


def test_added_uses_its_own_threshold():
    assert is_significant("added", 2.5, 3.0, 2.0)
    assert not is_significant("added", 2.0, 3.0, 2.0)


def test_other_changes_use_the_main_threshold():
    assert not is_significant("increased", 2.5, 3.0, 2.0)
    assert is_significant("decreased", -3.1, 3.0, 2.0)
    assert not is_significant("removed", -2.5, 3.0, 2.0)
