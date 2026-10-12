from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from .base import CHOICES_SHOWN, DataSkill, SkillResult, choice_result, empty
from .common import node, object_particle


class ETFChoiceArgs(BaseModel):
    stock: str = Field(description="ETF를 고르는 조건이 되는 종목 이름 또는 6자리 코드 (예: '원익IPS')")
    purpose: str = Field(description="ETF를 고른 뒤 보여줄 것 (예: '구성종목', '수익률 추이')")


class ETFChoiceSkill(DataSkill):
    name = "etf_choice"
    description = (
        "ETF 하나를 정해야 답할 수 있는데(구성종목·가격 추이·수익률 등) 대상이 '원익IPS가 들어간 ETF'처럼 "
        "종목 조건으로만 주어져 여러 ETF가 해당할 때. 그 종목을 담은 ETF 목록을 보여주고 어느 ETF를 볼지 되묻는다. "
        "이 슬롯 하나만 만든다(다른 스킬·narrative·agent를 붙이지 않는다). "
        "'원익IPS를 많이 담은 ETF는?'처럼 ETF 목록 자체를 묻는 질문은 stock_holders"
    )
    Args = ETFChoiceArgs
    displays = ("markdown",)

    def fetch(self, args: ETFChoiceArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if stock is None:
            return empty(f"종목을 찾지 못했습니다: {args.stock}")
        holders = node(
            GraphService(db),
            "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {code: $code}) "
            "RETURN {code: e.code, name: e.name, weight: h.weight} ORDER BY h.weight DESC",
            {"code": stock["code"]},
        )
        if not holders:
            return empty(f"{stock['name']}{object_particle(stock['name'])} 상위 구성종목으로 담은 ETF가 없습니다")

        shown = holders[:CHOICES_SHOWN]
        footer = (f"{stock['name']} 비중 상위 {len(shown)}개입니다. 목록에 없는 ETF도 이름으로 고를 수 있습니다."
                  if len(holders) > len(shown) else "")
        return choice_result(
            f"{stock['name']}{object_particle(stock['name'])} 담은 ETF가 {len(holders)}개입니다. "
            f"어느 ETF의 {args.purpose}{object_particle(args.purpose)} 볼까요?",
            ["ETF", "코드", f"{stock['name']} 비중"],
            [[h["name"], h["code"], f"{h['weight']:.2f}%"] for h in shown],
            footer,
        )
