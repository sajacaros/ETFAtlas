import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ....domain.composition import ETFAllocation, aggregate_composition
from ....models.etf import ETF
from ...graph_service import GraphService
from ..resolver import EntityResolver, _normalize
from ..schemas import BarView, DataField, Dataset, DonutView, Source, TableView, TreemapView
from .base import DataSkill, SkillResult, data_result, empty
from .common import node

DONUT_MAX_SLICES = 8  # 넘으면 나머지를 '기타'로 묶는다
OTHER = "_OTHER"  # 집계용 표식: ETF 안에서 상위 30개 밖 종목·현금
SAFE_CODE_RE = re.compile(r"[0-9A-Z]{6}")  # 쿼리 문자열에 직접 넣으므로 코드 모양만 허용


class PortfolioItem(BaseModel):
    asset: str = Field(description=(
        "포트폴리오에 담은 ETF 또는 종목의 이름이나 6자리 코드. 사용자가 쓴 이름을 앞뒤 접두어(1Q, ACE 등)까지 "
        "한 글자도 빼거나 바꾸지 말고 그대로 적는다 — 접두어가 빠지면 다른 운용사의 같은 이름 ETF로 계산된다"
    ))
    allocation: float = Field(gt=0, le=100, description="이 자산에 배분한 포트폴리오 비중(%). 사용자가 준 표의 비중 열")


class PortfolioLookthroughArgs(BaseModel):
    items: List[PortfolioItem] = Field(
        min_length=1, max_length=50, description="포트폴리오 구성. 사용자가 준 표나 목록의 각 행 (ETF와 개별 종목이 섞여도 된다)",
    )
    top: int = Field(15, ge=5, le=50, description="보여줄 상위 종목 수")


def _unlisted_etf(db: Session, asset: str) -> Optional[Dict]:
    """그래프에 없는 ETF (해외 ETF 등 구성종목을 수집하지 않는 ETF). {code, name} 또는 None."""
    key = asset.strip()
    row = db.query(ETF).filter((ETF.code == key.upper()) | (func.lower(ETF.name) == key.lower())).first()
    return {"code": row.code, "name": row.name} if row else None


def _holdings(db: Session, codes: List[str]) -> Dict[str, List[Dict]]:
    """ETF 코드 → 구성종목 [{stock_code, stock_name, weight, date}]. 한 번의 쿼리로 가져온다."""
    codes = [c for c in codes if SAFE_CODE_RE.fullmatch(c)]
    if not codes:
        return {}
    rows = node(
        GraphService(db),
        f"MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE e.code IN [{', '.join(repr(c) for c in codes)}] "
        "RETURN {etf: e.code, stock_code: s.code, stock_name: s.name, weight: h.weight, date: h.date}",
        {},
    )
    result: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get("weight") is not None:
            result.setdefault(r["etf"], []).append(r)
    return result


class PortfolioLookthroughSkill(DataSkill):
    name = "portfolio_lookthrough"
    description = (
        "포트폴리오(여러 ETF·종목과 각 비중)의 종목별 합산 비중. ETF는 구성종목으로 풀어 비중을 곱해 더하고, "
        "직접 담은 종목은 그대로 더한다. 사용자가 비중이 적힌 표·목록을 주고 구성종목 비율·겹치는 종목·실제 노출을 물을 때. "
        "ETF별 holdings 슬롯을 여러 개 만드는 대신 이 슬롯 하나로 처리한다"
    )
    Args = PortfolioLookthroughArgs
    displays = ("treemap", "bar", "donut", "table")

    def fetch(self, args: PortfolioLookthroughArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        # 자산별로 ETF → 그래프 밖 ETF → 종목 순서로 찾는다 (ETF 코드가 다른 ETF의 구성종목 노드로 잡히지 않게).
        # 같은 자산이 두 번 나오면 비중을 더한다
        etfs: Dict[str, Dict] = {}
        stocks: Dict[str, Dict] = {}
        unlisted: Dict[str, Dict] = {}
        missing: List[str] = []
        resolved: List[str] = []  # 적힌 이름과 다른 대상으로 찾은 항목 (사용자가 확인할 수 있게 notes에 남긴다)
        for item in args.items:
            for kind, found in (
                ("etf", lambda: resolver.etf(db, item.asset)),
                ("unlisted", lambda: _unlisted_etf(db, item.asset)),
                ("stock", lambda: resolver.stock(db, item.asset)),
            ):
                entity = found()
                if entity is not None:
                    bucket = {"etf": etfs, "stock": stocks, "unlisted": unlisted}[kind]
                    entry = bucket.setdefault(entity["code"], {**entity, "allocation": 0.0})
                    entry["allocation"] += item.allocation
                    if entity["code"] != item.asset.strip().upper() and _normalize(entity["name"]) != _normalize(item.asset):
                        resolved.append(f"{item.asset} → {entity['name']}({entity['code']})")
                    break
            else:
                missing.append(item.asset)
        if not (etfs or stocks or unlisted):
            return empty(f"포트폴리오 항목을 찾지 못했습니다: {', '.join(missing)}")

        holdings = _holdings(db, list(etfs))
        no_holdings = [e for code, e in etfs.items() if code not in holdings]
        allocations: List[ETFAllocation] = []
        for code, e in etfs.items():
            hs = holdings.get(code)
            if not hs:
                continue
            rest = 100 - sum(h["weight"] for h in hs)
            if rest > 0.005:  # 상위 30개 밖 종목·현금 몫
                hs = [*hs, {"stock_code": OTHER, "stock_name": "기타", "weight": rest}]
            allocations.append(ETFAllocation(code, e["name"], e["allocation"], hs))
        # 구성을 모르는 ETF는 ETF 한 행으로, 직접 담은 종목은 자기 자신 100%로 넣는다
        for e in [*no_holdings, *unlisted.values()]:
            allocations.append(ETFAllocation(e["code"], "구성 미확인", e["allocation"], [
                {"stock_code": e["code"], "stock_name": f"{e['name']} (구성 미확인)", "weight": 100},
            ]))
        for code, s in stocks.items():
            allocations.append(ETFAllocation(f"direct:{code}", "직접", s["allocation"], [
                {"stock_code": code, "stock_name": s["name"], "weight": 100},
            ]))

        exposures = aggregate_composition(allocations)
        named = [x for x in exposures if x.stock_code != OTHER]
        top = min(args.top, DONUT_MAX_SLICES - 1) if display == "donut" else args.top
        shown = named[:top]
        rows = [
            {
                "name": x.stock_name,
                "code": None if x.stock_name.endswith("(구성 미확인)") else x.stock_code,
                "weight": round(x.weight, 2),
                "via": " · ".join(f"{c.name} {c.weight:.2f}" for c in x.etfs),
            }
            for x in shown
        ]
        # 표시하지 않은 종목과 ETF 안의 30위 밖·현금을 합친 값. 모든 행의 합이 100이 된다
        rest = round(100 - sum(x.weight for x in shown), 2)
        if rest > 0.005:
            rows.append({"name": "기타", "code": None, "weight": rest,
                         "via": f"상위 {len(shown)}개 밖 종목, ETF 구성 30위 밖·현금"})

        dataset = Dataset(
            fields=[
                DataField(key="name", label="종목", format="text"),
                DataField(key="code", label="코드", format="text"),
                DataField(key="weight", label="합산 비중", format="percent"),
                DataField(key="via", label="경로", format="text"),
            ],
            rows=rows,
        )
        view = {
            "treemap": TreemapView(name="name", value="weight"),
            "donut": DonutView(name="name", value="weight"),
            "bar": BarView(x="name", y=["weight"], horizontal=True),
        }.get(display, TableView())

        notes: List[str] = []
        unknown = [*no_holdings, *unlisted.values()]
        if unknown:
            names = ", ".join(f"{e['name']}({e['code']})" for e in unknown)
            notes.append(f"구성종목 데이터가 없어 ETF 단위로 표시: {names}")
        if resolved:
            notes.append(f"이름으로 찾은 항목: {', '.join(resolved)}")
        if missing:
            notes.append(f"찾지 못해 계산에서 뺀 항목: {', '.join(missing)}")
        total = sum(a.weight for a in allocations)
        if abs(total - 100) > 0.05:
            notes.append(f"입력 비중 합계 {total:.2f}%를 100%로 맞춰 계산했습니다")
        if etfs:
            notes.append("ETF 구성종목은 비중 상위 30개 기준입니다")

        summary = (
            f"포트폴리오 합산 상위 {len(shown)}개: "
            + ", ".join(f"{r['name']} {r['weight']:.2f}%" for r in rows)
            + (f" / {notes[0]}" if unknown else "")
        )
        sources = [
            Source(label=f"{e['name']} 구성종목", as_of=max((h.get("date") or "" for h in holdings[code]), default="") or None)
            for code, e in etfs.items() if code in holdings
        ]
        return data_result(dataset, view, summary, sources, notes)
