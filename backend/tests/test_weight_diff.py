from app.domain.weight_diff import diff_holdings


def test_diff_holdings_classifies_each_stock():
    prev = {"A": {"name": "가", "weight": 10.0}, "B": {"name": "나", "weight": 5.0}, "C": {"name": "다", "weight": 3.0}}
    curr = {"A": {"name": "가", "weight": 12.5}, "B": {"name": "나", "weight": 5.0}, "D": {"name": "라", "weight": 2.0}}
    changes = {c["stock_code"]: c for c in diff_holdings(prev, curr)}
    assert set(changes) == {"A", "C", "D"}  # 그대로인 B는 빠진다
    assert changes["A"]["change_type"] == "increased" and changes["A"]["weight_change"] == 2.5
    assert changes["C"] == {"stock_code": "C", "stock_name": "다", "change_type": "removed",
                            "previous_weight": 3.0, "current_weight": 0, "weight_change": -3.0}
    assert changes["D"]["change_type"] == "added" and changes["D"]["previous_weight"] == 0
