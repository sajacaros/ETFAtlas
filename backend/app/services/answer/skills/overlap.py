from typing import Dict, List

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import ETF_NAMES_DESCRIPTION
from .portfolio_lookthrough import _holdings


class OverlapArgs(BaseModel):
    etfs: List[str] = Field(min_length=2, max_length=2, description=ETF_NAMES_DESCRIPTION)


def overlap(a: List[Dict], b: List[Dict]) -> Dict:
    """두 ETF 구성종목의 공통·단독 종목과 겹침 비중 (두 비중 중 작은 쪽의 합 — 두 ETF가 실제로 같이 들고 있는 몫)."""
    wa = {h["stock_code"]: h for h in a}
    wb = {h["stock_code"]: h for h in b}
    common = sorted(set(wa) & set(wb), key=lambda c: (-(wa[c]["weight"] + wb[c]["weight"]), c))
    only_a = sorted(set(wa) - set(wb), key=lambda c: (-wa[c]["weight"], c))
    only_b = sorted(set(wb) - set(wa), key=lambda c: (-wb[c]["weight"], c))
    return {
        "common": common, "only_a": only_a, "only_b": only_b,
        "overlap": round(sum(min(wa[c]["weight"], wb[c]["weight"]) for c in common), 2),
        "common_a": round(sum(wa[c]["weight"] for c in common), 2),
        "common_b": round(sum(wb[c]["weight"] for c in common), 2),
    }


class OverlapSkill(DataSkill):
    name = "overlap"
    description = (
        "ETF 두 개의 구성종목 겹침: 두 ETF에 모두 있는 종목과 한쪽에만 있는 종목, 종목별 두 비중, "
        "겹치는 비중(두 비중 중 작은 쪽의 합)을 계산한다. '둘 다 담은 종목', '얼마나 겹쳐', '한쪽에만 있는 종목'을 물을 때. "
        "holdings 슬롯 두 개와 해설로 겹침을 어림하지 말고 이 슬롯을 쓴다. 공통 종목을 다음 슬롯이 참조로 받을 수 있다. "
        "ETF마다 비중(%)이 주어진 포트폴리오의 겹치는 종목·실제 노출은 이 스킬이 아니라 portfolio_lookthrough로 본다"
    )
    Args = OverlapArgs
    displays = ("table", "bar")
    exports = "두 ETF에 모두 있는 종목 목록, 두 비중 합이 큰 순"

    def fetch(self, args: OverlapArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = resolver.etfs(db, args.etfs)
        if len(found) < 2:
            return not_found(f"ETF를 찾지 못했습니다: {', '.join(missing) or ', '.join(args.etfs)}")
        a, b = found[:2]
        holdings = _holdings(db, [a["code"], b["code"]])
        if not holdings.get(a["code"]) or not holdings.get(b["code"]):
            names = [e["name"] for e in (a, b) if not holdings.get(e["code"])]
            return empty(f"구성종목 데이터가 없습니다: {', '.join(names)}")
        ha, hb = holdings[a["code"]], holdings[b["code"]]
        o = overlap(ha, hb)
        wa = {h["stock_code"]: h for h in ha}
        wb = {h["stock_code"]: h for h in hb}

        def row(code: str, where: str) -> Dict:
            h = wa.get(code) or wb[code]
            return {"name": h["stock_name"], "code": code, "where": where,
                    "a": wa[code]["weight"] if code in wa else None, "b": wb[code]["weight"] if code in wb else None}

        rows = ([row(c, "공통") for c in o["common"]] + [row(c, f"{a['name']}만") for c in o["only_a"]]
                + [row(c, f"{b['name']}만") for c in o["only_b"]])
        dataset = Dataset(
            fields=[
                DataField(key="name", label="종목", format="text"),
                DataField(key="code", label="코드", format="text"),
                DataField(key="where", label="구분", format="text"),
                DataField(key="a", label=f"{a['name']} 비중", format="percent"),
                DataField(key="b", label=f"{b['name']} 비중", format="percent"),
            ],
            rows=rows,
        )
        view = BarView(x="name", y=["a", "b"], horizontal=True) if display == "bar" else TableView()

        def names(codes: List[str], weights: Dict[str, Dict]) -> str:
            return ", ".join(f"{weights[c]['stock_name']} {weights[c]['weight']:.2f}%" for c in codes) or "없음"

        summary = (
            f"{a['name']}·{b['name']} 공통 종목 {len(o['common'])}개, 겹치는 비중 {o['overlap']:.2f}% "
            f"(공통 종목 비중 합계 {a['name']} {o['common_a']:.2f}%, {b['name']} {o['common_b']:.2f}%). "
            f"공통: " + ", ".join(f"{wa[c]['stock_name']}({wa[c]['weight']:.2f}%/{wb[c]['weight']:.2f}%)" for c in o["common"])
            + f". {a['name']}에만: {names(o['only_a'], wa)}. {b['name']}에만: {names(o['only_b'], wb)}"
        )
        notes = [
            "겹치는 비중은 공통 종목마다 두 비중 중 작은 쪽을 더한 값입니다",
            "ETF마다 비중 상위 30개 종목까지만 수집하므로, 한쪽에만 있는 종목도 다른 ETF의 30위 밖에 있을 수 있습니다",
        ]
        if missing:
            notes.append(f"찾지 못한 ETF: {', '.join(missing)}")
        as_of = max((h.get("date") or "" for h in [*ha, *hb]), default="") or None
        return data_result(dataset, view, summary, [Source(label="ETF 구성종목", as_of=as_of)], notes,
                           exports=[{"code": c, "name": wa[c]["stock_name"]} for c in o["common"]])
