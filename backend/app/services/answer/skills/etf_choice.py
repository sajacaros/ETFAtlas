from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....domain.format import format_value
from ...entities import EntityResolver
from ...graph_service import GraphService, node
from .base import CHOICES_SHOWN, DataSkill, PlanLookups, SkillResult, choice_result, empty, not_found
from .common import object_particle, theme_etfs, theme_word


class ETFChoiceArgs(BaseModel):
    by: Literal["stock", "theme"] = Field(description=(
        "ETF를 고르는 조건의 종류. stock: 어떤 종목을 담은 ETF, theme: 업종·테마 이름이나 ETF 이름의 일부"
    ))
    condition: str = Field(description="조건 값. by=stock이면 개별 주식 종목 이름 또는 6자리 코드, by=theme이면 그 단어")
    purpose: str = Field(description="ETF를 고른 뒤 보여줄 것 (예: '구성종목', '수익률 추이')")


class ETFChoiceSkill(DataSkill):
    name = "etf_choice"
    description = (
        "ETF 하나를 정해야 답할 수 있는데(구성종목·가격 추이·수익률 등) 대상이 조건으로만 주어져 여러 ETF가 해당할 때 "
        "후보 목록을 보여주고 어느 ETF를 볼지 되묻는다. 어떤 종목을 담은 ETF면 by=stock, 업종·테마 이름이면 by=theme. "
        "이 슬롯 하나만 만든다(다른 스킬·narrative·agent를 붙이지 않는다). "
        "ETF 목록 자체를 묻거나 종목을 많이 담은 ETF 순위를 묻는 질문, ETF 상품 이름이 주어진 질문에는 쓰지 않는다. "
        "'가장 많이 담은 ETF', 'N위 ETF'처럼 순위로 대상이 정해지면 되묻지 않고 순위 스킬과 참조('@이름.순위')를 쓴다. "
        "'순자산이 가장 큰', '수익률 상위', '보수가 가장 낮은'처럼 수치 기준이 주어져도 되묻지 않는다 — rank 스킬로 고른다"
    )
    Args = ETFChoiceArgs
    displays = ("markdown",)
    subject = "etf"

    def plan_errors(self, args: ETFChoiceArgs, lookups: PlanLookups):
        # 테마로 되묻는데 그 '테마'가 상장 ETF의 정확한 이름이면, 대상이 이미 정해진 것이다
        if args.by == "theme" and lookups.is_etf_name(args.condition):
            return [f"'{args.condition}'은(는) 테마가 아니라 ETF 상품 이름입니다. "
                    "되묻지 말고 그 이름을 데이터 스킬의 인자에 그대로 적으세요"]
        return []

    def fetch(self, args: ETFChoiceArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        if args.by == "theme":
            theme = theme_word(args.condition)
            etfs = theme_etfs(db, theme)
            if not etfs:
                resolver.etf(db, args.condition)  # 테마가 아니라 관리하지 않는 ETF의 이름이면 UnmanagedETF로 그렇다고 알린다
                return not_found(f"'{theme}'에 해당하는 ETF를 찾지 못했습니다")
            subject, metric = f"'{theme}' ETF가", "순자산"
            rows = [[e["name"], e["code"], format_value(e.get("net_assets"), "krw")] for e in etfs]
        else:
            stock = resolver.stock(db, args.condition)
            if stock is None:
                return not_found(f"종목을 찾지 못했습니다: {args.condition}")
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
