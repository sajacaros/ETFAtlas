from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty
from .common import node


class StockHoldersArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (예: '삼성전자')")
    top: int = Field(10, ge=3, le=30, description="보여줄 ETF 수 (비중 높은 순)")


class StockHoldersSkill(DataSkill):
    name = "stock_holders"
    description = "개별 종목을 많이 담은 ETF 순위: 그 종목의 비중이 높은 순서로 ETF와 비중, 총보수. '삼성전자를 가장 많이 보유한 ETF' 같은 질문에"
    Args = StockHoldersArgs
    displays = ("bar", "table")

    def fetch(self, args: StockHoldersArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if stock is None:
            return empty(f"종목을 찾지 못했습니다: {args.stock}")
        holders = node(
            GraphService(db),
            "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {code: $code}) "
            "RETURN {code: e.code, name: e.name, weight: h.weight, expense_ratio: e.expense_ratio, date: h.date} "
            "ORDER BY h.weight DESC LIMIT $top",
            {"code": stock["code"], "top": args.top},
        )
        if not holders:
            return empty(f"{stock['name']}을(를) 상위 구성종목으로 담은 ETF가 없습니다")

        dataset = Dataset(
            fields=[
                DataField(key="name", label="ETF", format="text"),
                DataField(key="code", label="코드", format="text"),
                DataField(key="weight", label=f"{stock['name']} 비중", format="percent"),
                DataField(key="expense_ratio", label="총보수", format="percent"),
            ],
            rows=[{k: h.get(k) for k in ("name", "code", "weight", "expense_ratio")} for h in holders],
        )
        view = BarView(x="name", y=["weight"], horizontal=True) if display == "bar" else TableView()
        summary = f"{stock['name']} 비중이 높은 ETF: " + ", ".join(
            f"{h['name']} {h['weight']:.2f}%(총보수 {h['expense_ratio']}%)" for h in holders
        )
        notes = ["ETF마다 비중 상위 30개 종목까지만 수집하므로, 그 밖에서 담은 ETF는 빠집니다"]
        sources = [Source(label="ETF 구성종목", as_of=holders[0].get("date"))]
        return data_result(dataset, view, summary, sources, notes)
