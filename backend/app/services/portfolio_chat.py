"""챗봇에서 `/portfolio <키> 질문`으로 포트폴리오를 첨부해 질의하는 기능.

키는 비밀이 아니라 식별자다. 조회할 때마다 로그인 사용자 기준으로 권한을 확인하므로
본인 포트폴리오이거나 공유 중인 포트폴리오만 열린다 (공유를 끄면 남은 바로 못 쓴다).
챗봇에는 목표 비중과 그 비중으로 합산한 구성종목만 넘기고, 보유 수량·금액은 넘기지 않는다.
"""
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..domain.composition import ETFAllocation, aggregate_composition
from ..models.portfolio import Portfolio
from .graph_service import GraphService
from .price_service import PriceService

COMMAND = "/portfolio"
COMPOSITION_TOP_N = 30
VIA_ETFS_TOP_N = 3

_COMMAND_RE = re.compile(r"^\s*/portfolio(?:\s+(\S+))?(?:\s+(.*))?\s*$", re.DOTALL)


@dataclass
class PortfolioCommand:
    key: str          # 빈 문자열이면 키를 빠뜨린 것
    question: str     # 명령 뒤의 질문 (없으면 빈 문자열)


def parse_portfolio_command(message: str) -> Optional[PortfolioCommand]:
    """`/portfolio <키> 질문` 형식이면 키와 질문으로 나눈다. 명령이 아니면 None."""
    match = _COMMAND_RE.match(message)
    if not match:
        return None
    return PortfolioCommand(key=match.group(1) or "", question=(match.group(2) or "").strip())


def can_access(portfolio: Portfolio, user_id: Optional[int]) -> bool:
    return user_id is not None and (portfolio.user_id == user_id or bool(portfolio.is_shared))


def find_accessible_portfolio(db: Session, user_id: Optional[int], key: str) -> Optional[Portfolio]:
    """키에 해당하는 포트폴리오 중 이 사용자가 볼 수 있는 것. 없거나 권한이 없으면 None (둘을 구분하지 않는다)."""
    if not key:
        return None
    portfolio = db.query(Portfolio).filter(Portfolio.chat_key == key).first()
    if portfolio is None or not can_access(portfolio, user_id):
        return None
    return portfolio


def describe_portfolio(db: Session, portfolio: Portfolio, user_id: Optional[int]) -> dict:
    """챗봇에 넘길 포트폴리오 요약: ETF 목표 비중 + 비중대로 합산한 구성종목 상위 30개.

    비중은 % 단위 숫자. 구성종목은 현금과 구성종목 데이터가 없는 ETF(해외 ETF 등)를 빼고
    나머지 ETF 비중 합을 100%로 환산해 계산한다.
    """
    targets = sorted(portfolio.target_allocations, key=lambda t: float(t.target_weight), reverse=True)
    names = PriceService(db).get_etf_names([t.ticker for t in targets])

    graph = GraphService(db)
    allocations = []
    excluded = []
    as_of = None
    for t in targets:
        weight = float(t.target_weight)
        holdings = graph.get_etf_holdings_full(t.ticker) if t.ticker.upper() != "CASH" and weight > 0 else []
        if not holdings:
            if weight > 0:
                excluded.append(names.get(t.ticker, t.ticker))
            continue
        for h in holdings:
            if h.get("recorded_at") and (as_of is None or h["recorded_at"] > as_of):
                as_of = h["recorded_at"]
        allocations.append(ETFAllocation(t.ticker, names.get(t.ticker, t.ticker), weight, holdings))

    stocks = aggregate_composition(allocations)
    return {
        "name": portfolio.name,
        "kind": "내 포트폴리오" if portfolio.user_id == user_id else "공유 포트폴리오",
        "etfs": [
            {"code": t.ticker, "name": names.get(t.ticker, t.ticker), "weight": float(t.target_weight)}
            for t in targets
        ],
        "stocks": [
            {
                "rank": i + 1,
                "stock_code": s.stock_code,
                "stock_name": s.stock_name,
                "weight": s.weight,
                "via": [{"code": e.code, "name": e.name, "weight": e.weight} for e in s.etfs[:VIA_ETFS_TOP_N]],
            }
            for i, s in enumerate(stocks[:COMPOSITION_TOP_N])
        ],
        "total_stocks": len(stocks),
        "excluded_from_stocks": excluded,
        "holdings_as_of": as_of,
    }
