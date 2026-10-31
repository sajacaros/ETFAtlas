from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...content import BarView, DataField, Dataset, Source, TableView
from ...entities import EntityResolver
from ...graph_service import GraphService, node
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import cut_note, min_weight_field, object_particle



class StockHoldersArgs(BaseModel):
    stocks: List[str] = Field(min_length=1, max_length=5, description=(
        "종목 이름 또는 6자리 코드 목록. 여러 종목을 함께 많이 담은 ETF를 물으면 그 종목들을 모두 한 목록에 적는다"
    ))
    top: int = Field(10, ge=3, le=30, description="보여줄 ETF 수 (비중 높은 순)")
    min_weight: Optional[float] = min_weight_field("ETF(종목이 여러 개면 비중 합계 기준)")


class StockHoldersSkill(DataSkill):
    name = "stock_holders"
    description = (
        "개별 종목을 많이 담은 ETF 순위: 그 종목의 비중이 높은 순서로 ETF와 비중, 총보수. "
        "어떤 종목을 가장 많이 보유한 ETF를 묻는 질문에. 종목이 여러 개면 "
        "슬롯을 종목마다 나누지 말고 이 슬롯 하나에 모두 넣는다 — 종목들의 비중 합계 순으로 매기고 종목별 비중을 함께 보여준다"
    )
    Args = StockHoldersArgs
    displays = ("bar", "table")
    exports = "ETF 목록, 그 종목(여러 개면 비중 합계) 비중 높은 순"
    subject = "stock"
    exports_kind = "etf"
    entity_args = {"stocks": "stock"}

    def fetch(self, args: StockHoldersArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stocks, missing = resolver.stocks(db, args.stocks)
        if not stocks:
            return not_found(f"종목을 찾지 못했습니다: {', '.join(args.stocks)}")
        holders = _rank(db, stocks)
        names = ", ".join(s["name"] for s in stocks)
        if not holders:
            return empty(f"{names}{object_particle(names)} 상위 구성종목으로 담은 ETF가 없습니다")
        if args.min_weight is not None:
            holders = [h for h in holders if h["total"] >= args.min_weight]
            if not holders:
                return empty(f"{names} 비중이 {args.min_weight:g}% 이상인 ETF가 없습니다")
        passed = len(holders)
        holders = holders[:args.top]

        single = len(stocks) == 1
        weight_keys = [f"w_{s['code']}" for s in stocks]
        fields = [DataField(key="name", label="ETF", format="text"), DataField(key="code", label="코드", format="text")]
        fields += [DataField(key=k, label=f"{s['name']} 비중", format="percent") for k, s in zip(weight_keys, stocks)]
        if not single:
            fields.append(DataField(key="total", label="비중 합계", format="percent"))
        fields.append(DataField(key="expense_ratio", label="총보수", format="percent"))
        dataset = Dataset(fields=fields, rows=[
            {"name": h["name"], "code": h["code"], "expense_ratio": h["expense_ratio"],
             **{k: h["weights"].get(s["code"]) for k, s in zip(weight_keys, stocks)},
             **({} if single else {"total": h["total"]})}
            for h in holders
        ])
        # 여러 종목이면 종목별 비중을 쌓아 막대 길이가 합계가 되게 한다
        view = BarView(x="name", y=weight_keys, horizontal=True, stacked=not single) if display == "bar" else TableView()

        def describe(h: Dict) -> str:
            if single:
                return f"{h['name']} {h['total']:.2f}%(총보수 {h['expense_ratio']}%)"
            parts = ", ".join(f"{s['name']} {h['weights'].get(s['code'], 0):.2f}%" for s in stocks)
            return f"{h['name']} 합계 {h['total']:.2f}%({parts}, 총보수 {h['expense_ratio']}%)"

        label = f"{names} 비중이" if single else f"{names} 비중 합계가"
        if args.min_weight is not None:
            label = f"{label} {args.min_weight:g}% 이상이고"
        summary = f"{label} 높은 ETF: " + "; ".join(describe(h) for h in holders)
        notes = ["ETF마다 비중 상위 30개 종목까지만 수집하므로, 그 밖에서 담은 ETF는 빠집니다"]
        if args.min_weight is not None:
            notes += cut_note(passed, len(holders), "ETF")
        if not single:
            notes.append("상위 30개 안에 없는 종목은 0%로 계산했습니다")
        if missing:
            notes.append(f"찾지 못한 종목: {', '.join(missing)}")
        sources = [Source(label="ETF 구성종목", as_of=holders[0].get("date"))]
        return data_result(dataset, view, summary, sources, notes,
                           exports=[{"code": h["code"], "name": h["name"]} for h in holders])


def _rank(db: Session, stocks: List[Dict]) -> List[Dict]:
    """종목들을 담은 ETF를 종목 비중 합계가 높은 순으로. [{code, name, expense_ratio, date, weights: {종목 코드: 비중}, total}]"""
    rows = node(
        GraphService(db),
        "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.code IN $codes "
        "RETURN {code: e.code, name: e.name, stock: s.code, weight: h.weight, expense_ratio: e.expense_ratio, date: h.date}",
        {"codes": [s["code"] for s in stocks]},
    )
    etfs: Dict[str, Dict] = {}
    for r in rows:
        if r.get("weight") is None:
            continue
        etf = etfs.setdefault(r["code"], {"code": r["code"], "name": r["name"], "expense_ratio": r.get("expense_ratio"),
                                          "date": r.get("date"), "weights": {}})
        etf["weights"][r["stock"]] = r["weight"]
    for etf in etfs.values():
        etf["total"] = round(sum(etf["weights"].values()), 2)
    return sorted(etfs.values(), key=lambda e: (-e["total"], e["code"]))
