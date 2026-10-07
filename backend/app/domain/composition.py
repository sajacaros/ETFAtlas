"""ETF 투자 비중으로 포트폴리오 구성종목 비중을 계산 (look-through).

입력 ETF 비중은 합계 100%로 환산한 뒤, 각 구성종목 비중(%)에 곱해 종목별로 합산한다.
"""
from dataclasses import dataclass, field


@dataclass
class ETFAllocation:
    code: str
    name: str
    weight: float                # 입력 비중
    holdings: list[dict]         # [{stock_code, stock_name, weight}] — weight는 ETF 내 비중(%)


@dataclass
class ETFContribution:
    code: str
    name: str
    weight: float                # 이 ETF를 통해 들어온 포트폴리오 비중(%)


@dataclass
class StockExposure:
    stock_code: str
    stock_name: str
    weight: float                # 포트폴리오 비중(%)
    etfs: list[ETFContribution] = field(default_factory=list)


def normalize_weights(allocations: list[ETFAllocation]) -> dict[str, float]:
    """ETF 코드 → 합계 100%로 환산한 비중. 합계가 0이면 빈 dict."""
    total = sum(a.weight for a in allocations if a.weight > 0)
    if total <= 0:
        return {}
    return {a.code: a.weight * 100 / total for a in allocations if a.weight > 0}


def aggregate_composition(allocations: list[ETFAllocation]) -> list[StockExposure]:
    """겹치는 종목은 합산해 포트폴리오 비중 내림차순으로 반환."""
    normalized = normalize_weights(allocations)
    stocks: dict[str, StockExposure] = {}
    for a in allocations:
        etf_weight = normalized.get(a.code)
        if not etf_weight:
            continue
        for h in a.holdings:
            contribution = etf_weight * (h.get("weight") or 0) / 100
            if contribution <= 0:
                continue
            code = h["stock_code"]
            stock = stocks.get(code)
            if stock is None:
                stock = stocks[code] = StockExposure(code, h.get("stock_name") or code, 0.0)
            stock.weight += contribution
            stock.etfs.append(ETFContribution(a.code, a.name, contribution))

    result = sorted(stocks.values(), key=lambda s: s.weight, reverse=True)
    for s in result:
        s.etfs.sort(key=lambda e: e.weight, reverse=True)
    return result
