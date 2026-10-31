import asyncio
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ....models.weight_change import WeightChange
from ..base import FlowContext, Node, StockSet, result
from ..lookups import held_by

ACTIVE = {
    "off": "보지 않음",
    "added": "새로 편입",
    "buy": "새로 편입 또는 비중 증가",
}


class ETFSignalParams(BaseModel):
    """켠 조건을 모두 만족하는 종목만 남긴다. 모두 끄면 필터링하지 않고 열만 붙인다."""
    min_etfs: Optional[int] = Field(None, ge=1, le=100, title="담은 ETF 수 이상", description="관리 중인 ETF가 상위 30위 안에 담은 수. 예: 5")
    active: Literal["off", "added", "buy"] = Field("buy", title="액티브 ETF 매수", json_schema_extra={"options": ACTIVE})
    days: int = Field(5, ge=1, le=20, title="최근 공시일 수", description="비중 변화를 모아 볼 기간",
                      json_schema_extra={"show_if": {"active": ["added", "buy"]}})
    min_change: float = Field(0.5, ge=0, le=30, title="비중 변화 최소(%p)", description="새로 편입은 편입 비중으로 본다",
                              json_schema_extra={"show_if": {"active": ["added", "buy"]}})
    min_active_etfs: int = Field(1, ge=1, le=30, title="매수한 액티브 ETF 수 이상",
                                 json_schema_extra={"show_if": {"active": ["added", "buy"]}})


def recent_dates(db: Session, days: int) -> List[str]:
    rows = db.query(WeightChange.base_date).distinct().order_by(WeightChange.base_date.desc()).limit(days).all()
    return [r[0] for r in rows]


def active_buys(db: Session, codes: List[str], dates: List[str], mode: str, min_change: float) -> Dict[str, Dict[str, Any]]:
    """코드 → {etfs: 매수한 액티브 ETF 이름(중복 없음), change: 비중 변화 합(%p)}."""
    if not codes or not dates:
        return {}
    types = ["added"] if mode == "added" else ["added", "increased"]
    rows = (
        db.query(WeightChange.stock_code, WeightChange.etf_name, func.sum(WeightChange.weight_change))
        .filter(
            WeightChange.base_date.in_(dates),
            WeightChange.stock_code.in_(codes),
            WeightChange.change_type.in_(types),
            WeightChange.weight_change >= min_change,
        )
        .group_by(WeightChange.stock_code, WeightChange.etf_name)
        .all()
    )
    out: Dict[str, Dict[str, Any]] = {}
    for code, etf, change in rows:
        entry = out.setdefault(code, {"etfs": [], "change": 0.0})
        entry["etfs"].append(etf)
        entry["change"] += change
    return out


def passes(row: Dict[str, Any], p: ETFSignalParams) -> bool:
    if p.min_etfs is not None and (row.get("etf_count") or 0) < p.min_etfs:
        return False
    if p.active != "off" and (row.get("active_etfs") or 0) < p.min_active_etfs:
        return False
    return True


class ETFSignalNode(Node):
    type = "etf_signal"
    label = "ETF 신호 필터"
    category = "filter"
    icon = "🧭"
    description = "ETF가 담은 정도로 필터링한다. 담은 ETF 수, 최근 공시일에 액티브 ETF가 새로 편입하거나 비중을 늘린 종목"
    Params = ETFSignalParams

    async def run(self, params: ETFSignalParams, inputs: List[StockSet], ctx: FlowContext):
        source = inputs[0]
        codes = list(source.rows)
        holders, buys, dates = await asyncio.to_thread(self._load, ctx, codes, params)

        rows = {}
        for code, row in source.rows.items():
            buy = buys.get(code)
            values = {
                **row,
                "etf_count": len(holders.get(code, [])),
                **({
                    "active_etfs": len(buy["etfs"]) if buy else 0,
                    "active_change": round(buy["change"], 2) if buy else None,
                    "active_names": ", ".join(buy["etfs"][:3]) + (f" 외 {len(buy['etfs']) - 3}" if len(buy["etfs"]) > 3 else "") if buy else None,
                } if params.active != "off" else {}),
            }
            if passes(values, params):
                rows[code] = values
        items = source.derive(rows)
        items.add_field("etf_count", "담은 ETF 수")
        if params.active != "off":
            items.add_field("active_etfs", "매수한 액티브 ETF 수")
            items.add_field("active_change", "액티브 비중 증가 합(%p)")
            items.add_field("active_names", "매수한 액티브 ETF", "text")

        conditions = []
        if params.min_etfs is not None:
            conditions.append(f"담은 ETF {params.min_etfs}개 이상")
        if params.active != "off":
            if not dates:
                raise ValueError("액티브 ETF 비중 변화 기록이 아직 없습니다")
            span = dates[-1] if len(dates) == 1 else f"{dates[-1]}~{dates[0]}"
            conditions.append(
                f"최근 공시일 {len(dates)}개({span}) 동안 액티브 ETF {params.min_active_etfs}개 이상이 "
                f"{ACTIVE[params.active]} ({params.min_change:g}%p 이상)"
            )
        items.notes.append(
            ("조건(ETF 신호): " + ", ".join(conditions) + f" → {len(source.rows):,}종목 중 {len(rows):,}종목")
            if conditions else "ETF 신호: 조건을 켜지 않아 필터링하지 않고 열만 붙였습니다"
        )
        yield result(items)

    @staticmethod
    def _load(ctx: FlowContext, codes: List[str], params: ETFSignalParams):
        db = ctx.session_factory()
        try:
            holders = held_by(db, codes)
            if params.active == "off":
                return holders, {}, []
            dates = recent_dates(db, params.days)
            return holders, active_buys(db, codes, dates, params.active, params.min_change), dates
        finally:
            db.close()
