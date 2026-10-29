import asyncio
import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....models.portfolio import Holding, Portfolio
from ...entities import AmbiguousETF, EntityResolver, UnmanagedETF, UnmanagedStock
from ...graph_service import GraphService, node as cypher
from ..base import FlowContext, Node, StockSet, result

SAFE_CODE_RE = re.compile(r"[0-9A-Z]{6}")  # 쿼리 문자열에 직접 넣으므로 코드 모양만 허용

MODES = {
    "all": "ETF가 담은 전체 종목",
    "etf": "특정 ETF 구성종목",
    "portfolio": "내 포트폴리오 실보유",
    "codes": "직접 입력",
}


class SourceParams(BaseModel):
    mode: Literal["all", "etf", "portfolio", "codes"] = Field(
        "all", title="가져올 대상", json_schema_extra={"options": MODES},
    )
    etf: str = Field(
        "", title="ETF", description="이름 일부나 코드로 검색해 고른다 (예: 반도체 kodex)",
        json_schema_extra={"widget": "etf", "show_if": {"mode": ["etf"]}},
    )
    portfolio_id: Optional[int] = Field(
        None, title="포트폴리오", json_schema_extra={"widget": "portfolio", "show_if": {"mode": ["portfolio"]}},
    )
    codes: str = Field(
        "", title="종목", description="코드나 이름을 쉼표로 구분 (예: 005930, SK하이닉스)",
        json_schema_extra={"show_if": {"mode": ["codes"]}},
    )


def universe(db: Session) -> List[Dict]:
    """ETF 구성종목으로 한 번이라도 들어온 주식 (ETF 제외)."""
    return cypher(GraphService(db), "MATCH (s:Stock) WHERE s.is_etf = false RETURN {code: s.code, name: s.name}", {})


def etf_holdings(db: Session, etf_codes: List[str]) -> List[Dict]:
    """ETF들의 현재 구성종목 중 주식 [{etf, etf_name, code, name, weight}], 비중 큰 순."""
    codes = [c for c in etf_codes if SAFE_CODE_RE.fullmatch(c)]
    if not codes:
        return []
    rows = cypher(
        GraphService(db),
        f"MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE e.code IN [{', '.join(repr(c) for c in codes)}] "
        "AND s.is_etf = false RETURN {etf: e.code, etf_name: e.name, code: s.code, name: s.name, weight: h.weight}",
        {},
    )
    return sorted(rows, key=lambda r: -(r.get("weight") or 0))


class SourceNode(Node):
    type = "source"
    label = "대상 종목"
    category = "source"
    icon = "📥"
    description = "분석할 대상 종목을 정한다. ETF가 담은 전체 종목, 특정 ETF의 구성종목, 내 포트폴리오가 ETF로 실제 담고 있는 종목, 직접 고른 종목 중 하나"
    Params = SourceParams
    min_inputs = 0
    max_inputs = 0

    async def run(self, params: SourceParams, inputs, ctx: FlowContext):
        items = await asyncio.to_thread(self._load, params, ctx)
        yield result(items)

    def _load(self, params: SourceParams, ctx: FlowContext) -> StockSet:
        db = ctx.session_factory()
        try:
            if params.mode == "all":
                return self._from_rows(universe(db), "ETF 구성종목에 들어 있는 주식 전체 (ETF가 상위 30위 안에 담은 종목만)")
            if params.mode == "etf":
                return self._from_etf(db, params.etf)
            if params.mode == "portfolio":
                return self._from_portfolio(db, ctx.user_id, params.portfolio_id)
            return self._from_codes(db, params.codes)
        finally:
            db.close()

    @staticmethod
    def _from_rows(rows: List[Dict], note: str = "") -> StockSet:
        items = StockSet(notes=[note] if note else [])
        for r in sorted(rows, key=lambda r: r["code"]):
            items.rows[r["code"]] = {"code": r["code"], "name": r.get("name") or r["code"]}
        return items

    @staticmethod
    def _from_etf(db: Session, name: str) -> StockSet:
        if not name.strip():
            raise ValueError("ETF를 입력하세요")
        try:
            etf = EntityResolver().etf(db, name.strip())
        except AmbiguousETF as e:
            options = ", ".join(c["name"] for c in e.candidates[:5])
            raise ValueError(f"'{name}'에 맞는 ETF가 여럿입니다: {options}")
        except UnmanagedETF as e:
            raise ValueError(f"{e.etf['name']}은(는) 구성종목을 수집하지 않는 ETF입니다")
        if not etf:
            raise ValueError(f"ETF를 찾지 못했습니다: {name}")
        holdings = etf_holdings(db, [etf["code"]])
        items = StockSet(notes=[f"{etf['name']}({etf['code']}) 현재 구성종목 중 주식 (상위 30개)"])
        items.add_field("weight", "ETF 내 비중", "percent")
        for h in holdings:
            items.rows[h["code"]] = {"code": h["code"], "name": h["name"], "weight": h["weight"]}
        return items

    @staticmethod
    def _from_portfolio(db: Session, user_id: int, portfolio_id: Optional[int]) -> StockSet:
        if portfolio_id is None:
            raise ValueError("포트폴리오를 고르세요")
        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id).first()
        if not portfolio:
            raise ValueError("포트폴리오를 찾지 못했습니다")
        tickers = [h.ticker for h in db.query(Holding).filter(Holding.portfolio_id == portfolio.id) if SAFE_CODE_RE.fullmatch(h.ticker)]
        if not tickers:
            raise ValueError(f"{portfolio.name}에 보유 종목이 없습니다")
        # 보유 ETF는 구성종목으로 풀고, 직접 보유한 주식은 그대로 넣는다
        via: Dict[str, Dict] = {}
        for h in etf_holdings(db, tickers):
            entry = via.setdefault(h["code"], {"code": h["code"], "name": h["name"], "etfs": []})
            entry["etfs"].append(h["etf_name"])
        stock_codes = {r["code"]: r for r in universe(db)}
        for t in tickers:
            if t in stock_codes:
                via.setdefault(t, {"code": t, "name": stock_codes[t]["name"], "etfs": []})["etfs"].insert(0, "직접 보유")
        items = StockSet(notes=[f"{portfolio.name}이 직접 또는 ETF로 담은 주식 (ETF는 상위 30개 구성종목만)"])
        items.add_field("via", "담은 경로", "text")
        for code, entry in sorted(via.items(), key=lambda kv: -len(kv[1]["etfs"])):
            items.rows[code] = {"code": code, "name": entry["name"], "via": ", ".join(entry["etfs"])}
        return items

    @staticmethod
    def _from_codes(db: Session, text: str) -> StockSet:
        names = [t.strip() for t in re.split(r"[,\n]", text) if t.strip()]
        if not names:
            raise ValueError("종목을 입력하세요")
        resolver = EntityResolver()
        items = StockSet()
        missing = []
        for name in names:
            try:
                stock = resolver.stock(db, name)
            except UnmanagedStock as e:  # ETF가 담지 않은 상장사도 시세로 분석할 수 있다
                stock = e.corp if e.corp["code"] else None
            if SAFE_CODE_RE.fullmatch(name.upper()):  # 코드는 그래프에 없어도 시세는 받을 수 있다
                code = name.upper()
                items.rows[code] = {"code": code, "name": stock["name"] if stock else code}
            elif stock:
                items.rows[stock["code"]] = {"code": stock["code"], "name": stock["name"]}
            else:
                missing.append(name)
        if missing:
            items.notes.append(f"찾지 못한 종목: {', '.join(missing)}")
        if not items.rows:
            raise ValueError(f"종목을 찾지 못했습니다: {', '.join(missing)}")
        return items
