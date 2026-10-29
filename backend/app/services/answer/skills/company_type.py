"""company_type: 종목이 지속 성장주·턴어라운드주·경기민감·성숙기·신흥·초기 단계 중 어디에 맞는지, 숫자로 볼 수 있는 기준만.

판정은 app/domain/company_type.py. 해자·신공장·업황처럼 보고서를 읽어야 아는 기준은 표에 '보고서로 확인'으로 남긴다.
"""
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....domain import company_type as ct
from ....domain import financials as fin
from ....models.dart import StockFinancial
from ...content import DataField, Dataset, Source, TableView
from ...entities import EntityResolver
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .company_financials import FS_LABEL

FIELDS = [
    DataField(key="category", label="유형", format="text"),
    DataField(key="check", label="기준", format="text"),
    DataField(key="value", label="값", format="text"),
    DataField(key="result", label="판정", format="text"),
]

RESULT = {True: "충족", False: "미충족", None: "데이터 없음"}


class CompanyTypeArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")


def _eok(value: Optional[int]) -> str:
    return "-" if value is None else f"{value / 1e8:,.0f}억"


def summary_text(name: str, fs: str, result: ct.CompanyType) -> str:
    """판정과 기준별 값. stock_opinion도 같은 문구를 LLM에 넘긴다."""
    head = {ct.MATCHED: f"유형 판정: {result.category}", ct.NONE: "유형 판정: 해당 없음",
            ct.UNDETERMINED: "유형 판정: 판정하지 않음"}[result.status]
    lines = [f"{name} 유형 판정 (DART 주요계정·현금흐름, {fs}) — {head}. {result.reason}"]
    if result.years:
        lines.append("연간 실적: " + "; ".join(
            f"{y.year} 매출 {_eok(y.revenue)}, 영업이익 {_eok(y.operating_income)}, 순이익 {_eok(y.net_income)}, "
            f"영업현금흐름 {_eok(y.ocf)}, FCF {_eok(y.fcf)}" for y in result.years))
    for category in ct.CATEGORIES:
        for c in result.checks.get(category, []):
            lines.append(f"[{category}] {c.label}: {RESULT[c.passed]} ({c.detail})")
    for category, what in result.qualitative.items():
        lines.append(f"[{category}] 보고서로 확인할 것: {what}")
    return "\n".join(lines)


def classify_stock(db: Session, code: str):
    """(연결/별도 표기, 판정). stock_opinion도 쓴다."""
    rows = db.query(StockFinancial).filter(StockFinancial.stock_code == code).all()
    fs_div, amounts = fin.pick_fs(rows)
    # 연결 회사는 별도(사업보고서)를 현금흐름 기준 대조용으로 함께 넘긴다
    separate = {(r.bsns_year, r.reprt_code, r.account): (r.amount, r.amount_cum) for r in rows if r.fs_div == "OFS"} \
        if fs_div == "CFS" else None
    return FS_LABEL.get(fs_div, fs_div), (ct.classify(amounts, separate) if amounts else None)


class CompanyTypeSkill(DataSkill):
    name = "company_type"
    description = (
        "종목이 어떤 유형의 주식인지(지속 성장주·턴어라운드주·경기민감·성숙기·신흥·초기 단계) 물을 때, 그리고 살까 말까를 물을 때 "
        "stock_opinion 앞에 두는 스킬. 숫자로 볼 수 있는 기준만 판정한다: 3개년 연속 매출·영업이익 증가, 영업이익률, "
        "발생액 품질(최근 3년 Σ영업현금흐름 ≥ 0.85 × Σ순이익), 적자·마진 훼손 뒤 흑자 반등과 영업현금흐름 흑자, "
        "영업흑자 연수, 실적 이력·매출 규모. 연도별 영업현금흐름·FCF도 요약에 들어간다. 종목 하나"
    )
    Args = CompanyTypeArgs
    displays = ("table",)
    tool = True
    subject = "stock"
    entity_args = {"stock": "stock"}

    def fetch(self, args: CompanyTypeArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if not stock:
            return not_found(f"종목을 찾지 못했습니다: {args.stock}")
        fs, result = classify_stock(db, stock["code"])
        if result is None:
            return empty(f"{stock['name']}의 DART 실적이 없습니다")
        rows: List[dict] = []
        for category in ct.CATEGORIES:
            matched = result.category == category
            label = f"{category} ✓" if matched else category
            for c in result.checks.get(category, []):
                rows.append({"category": label, "check": c.label, "value": c.detail, "result": RESULT[c.passed]})
            rows.append({"category": label, "check": ct.QUALITATIVE[category], "value": "-", "result": "보고서로 확인"})
        notes = [
            "숫자로 볼 수 있는 기준만 판정합니다. 해자·신공장·업황 사이클·수주 모멘텀은 정기보고서로 확인할 기준입니다",
            "위에서부터(신흥·초기 → 지속 성장 → 턴어라운드 → 경기민감·성숙기) 기준을 모두 충족한 첫 유형으로 정합니다. "
            "신흥·초기 단계는 기준 하나만 맞아도 해당합니다",
            f"연간 실적은 DART 사업보고서(2022년부터 수집), 영업이익률 기준 {ct.HIGH_MARGIN:.0f}%, "
            f"마진 훼손은 전년 이익률의 {ct.DAMAGED_MARGIN:.0%} 아래, 상업화 전은 매출 {ct.PRE_REVENUE / 1e8:,.0f}억 원 미만",
            "영업현금흐름·순이익은 연결이면 비지배지분을 포함합니다",
        ]
        dataset = Dataset(fields=FIELDS, rows=rows)
        return data_result(dataset, TableView(), summary_text(stock["name"], fs, result),
                           [Source(label="DART 주요계정·현금흐름표")], notes)
