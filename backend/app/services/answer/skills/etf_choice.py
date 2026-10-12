from typing import Dict, List, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver, _normalize
from .base import CHOICES_SHOWN, DataSkill, SkillResult, choice_result, empty
from .common import format_value, node, object_particle


class ETFChoiceArgs(BaseModel):
    by: Literal["stock", "theme"] = Field(description=(
        "ETF를 고르는 조건의 종류. stock: 종목이 조건('원익IPS가 들어간 ETF'), theme: 테마·이름 일부('반도체 ETF', '2차전지 ETF')"
    ))
    condition: str = Field(description="조건 값. by=stock이면 개별 주식 종목 이름 또는 6자리 코드, by=theme이면 그 단어 (예: '반도체')")
    purpose: str = Field(description="ETF를 고른 뒤 보여줄 것 (예: '구성종목', '수익률 추이')")


def _theme_word(theme: str) -> str:
    """'반도체 ETF' → '반도체'."""
    word = theme.strip()
    return word[:-3].strip() if word.upper().endswith("ETF") else word


def _theme_etfs(db: Session, theme: str) -> List[Dict]:
    """태그 이름과 같으면 그 태그의 ETF, 아니면 이름에 그 단어가 든 ETF. 순자산 큰 순."""
    query = _normalize(theme)
    if not query:
        return []
    graph = GraphService(db)
    tagged = node(
        graph,
        "MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE replace(toLower(t.name), ' ', '') = $query "
        "RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC",
        {"query": query},
    )
    return tagged or node(
        graph,
        "MATCH (e:ETF) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query "
        "RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC",
        {"query": query},
    )


class ETFChoiceSkill(DataSkill):
    name = "etf_choice"
    description = (
        "ETF 하나를 정해야 답할 수 있는데(구성종목·가격 추이·수익률 등) 대상이 조건으로만 주어져 여러 ETF가 해당할 때 "
        "후보 목록을 보여주고 어느 ETF를 볼지 되묻는다. 종목 조건('원익IPS가 들어간 ETF')은 by=stock, "
        "테마·이름 일부('반도체 ETF', '2차전지 ETF')는 by=theme. "
        "이 슬롯 하나만 만든다(다른 스킬·narrative·agent를 붙이지 않는다). "
        "'반도체 ETF 어떤 게 있어?'처럼 ETF 목록 자체를 묻는 질문이나 '원익IPS를 많이 담은 ETF는?'(stock_holders)에는 쓰지 않는다"
    )
    Args = ETFChoiceArgs
    displays = ("markdown",)

    def fetch(self, args: ETFChoiceArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        if args.by == "theme":
            theme = _theme_word(args.condition)
            etfs = _theme_etfs(db, theme)
            if not etfs:
                return empty(f"'{theme}'에 해당하는 ETF를 찾지 못했습니다")
            subject, metric = f"'{theme}' ETF가", "순자산"
            rows = [[e["name"], e["code"], format_value(e.get("net_assets"), "krw")] for e in etfs]
        else:
            stock = resolver.stock(db, args.condition)
            if stock is None:
                return empty(f"종목을 찾지 못했습니다: {args.condition}")
            etfs = node(
                GraphService(db),
                "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {code: $code}) "
                "RETURN {code: e.code, name: e.name, weight: h.weight} ORDER BY h.weight DESC",
                {"code": stock["code"]},
            )
            if not etfs:
                return empty(f"{stock['name']}{object_particle(stock['name'])} 상위 구성종목으로 담은 ETF가 없습니다")
            subject, metric = f"{stock['name']}{object_particle(stock['name'])} 담은 ETF가", f"{stock['name']} 비중"
            rows = [[e["name"], e["code"], f"{e['weight']:.2f}%"] for e in etfs]

        shown = rows[:CHOICES_SHOWN]
        footer = (f"{metric} 상위 {len(shown)}개입니다. 목록에 없는 ETF도 이름으로 고를 수 있습니다."
                  if len(rows) > len(shown) else "")
        return choice_result(
            f"{subject} {len(rows)}개입니다. 어느 ETF의 {args.purpose}{object_particle(args.purpose)} 볼까요?",
            ["ETF", "코드", metric], shown, footer,
        )
