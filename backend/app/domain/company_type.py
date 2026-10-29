"""종목 유형 판정: 지속 성장주 / 턴어라운드주 / 경기민감·성숙기 / 신흥·초기 단계 — 숫자로 볼 수 있는 기준만.

해자·신공장 가동·업황 사이클·수주 모멘텀처럼 보고서를 읽어야 아는 기준은 '보고서로 확인'으로 남기고 판정에 쓰지 않는다.
앞에서부터 기준을 모두 충족한 첫 유형으로 정하고, 어느 유형에도 맞지 않으면 '해당 없음'이다 (사지 않는 쪽 신호).
매출액 계정이 없는 회사(은행·증권 등)는 판정하지 않는다.
영업현금흐름 기준은 연결로 보되, 연결로는 어긋나고 별도(사업보고서)로는 맞으면 판정하지 않는다 — 할부금융 등 금융 자회사의
대출 증감이 연결 영업현금흐름에 들어가 본업 현금창출력을 재지 못하는 경우다. 별도가 낫다고 그쪽으로 통과시키지는 않는다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cashflow import CAPEX, INTANGIBLE, OCF, annual_flow, free_cash_flow, ttm_flow
from .financials import ANNUAL, Amounts, build_periods, without_revenue

COMPOUNDER, TURNAROUND, CYCLICAL, EMERGING = "지속 성장주", "턴어라운드주", "경기민감·성숙기", "신흥·초기 단계"
CATEGORIES = (EMERGING, COMPOUNDER, TURNAROUND, CYCLICAL)  # 판정 순서

HISTORY_YEARS = 4          # 3개년 연속 증가를 보려면 연간 실적 4개
HIGH_MARGIN = 10.0         # '높은 영업이익률' (%)
ACCRUAL_RATIO = 0.85       # ΣOCF ≥ 0.85 ΣNI
DAMAGED_MARGIN = 0.5       # 영업이익률이 전년의 절반 아래로 떨어지면 마진 훼손
PRE_REVENUE = 10_000_000_000  # 매출 100억 원 미만은 상업화 전으로 본다
# 턴어라운드의 저점을 찾는 직전 사업연도 수. 영업적자는 3년까지(2023년 적자 뒤 흑자로 돌아선 회사), 이익률 반토막은 2년까지
# — 3년으로 넓히면 2023년 반도체 불황처럼 적자 없이 이익률만 꺾였다 회복한 경기민감 종목까지 턴어라운드로 옮겨 간다
# (2026-10 전체 570종목 비교: 적자·훼손 모두 3년이면 경기민감 29개가 옮겨 가고, 그중 18개가 이익률만 꺾인 종목)
LOSS_YEARS = 3
DAMAGE_YEARS = 2

MATCHED, NONE, UNDETERMINED = "matched", "none", "undetermined"


@dataclass
class Check:
    label: str
    passed: Optional[bool]  # None: 데이터 없음 또는 보고서로 확인할 기준 (판정에 쓰지 않는다)
    detail: str


@dataclass
class YearRow:
    year: int
    revenue: Optional[int]
    operating_income: Optional[int]
    net_income: Optional[int]
    ocf: Optional[int]
    fcf: Optional[int]

    @property
    def margin(self) -> Optional[float]:
        if self.operating_income is None or not self.revenue or self.revenue <= 0:
            return None
        return self.operating_income / self.revenue * 100


@dataclass
class CompanyType:
    status: str                      # matched | none | undetermined
    category: Optional[str]          # matched일 때 유형
    reason: str
    years: List[YearRow] = field(default_factory=list)
    checks: Dict[str, List[Check]] = field(default_factory=dict)
    qualitative: Dict[str, str] = field(default_factory=dict)  # 유형별로 보고서에서 확인할 것


QUALITATIVE = {
    COMPOUNDER: "강력한 경제적 해자(시장 지위·기술·브랜드·전환 비용)",
    TURNAROUND: "흑자 반등의 원인(신공장 가동·제품 믹스 개선 등)이 이어지는지",
    CYCLICAL: "전방 산업 CAPEX·매크로 사이클에서의 위치, 또는 점유율을 확보한 성숙기 캐시카우인지",
    EMERGING: "차세대 기술·정책·수주 모멘텀",
}


def _eok(value: Optional[int]) -> str:
    return "-" if value is None else f"{value / 1e8:,.0f}억"


def year_rows(amounts: Amounts) -> List[YearRow]:
    """사업보고서가 있는 연도의 연간 실적·현금흐름, 오래된 순."""
    by_year = {int(p["period"]): p for p in build_periods(amounts, "year")}
    years = sorted(y for y in by_year if (y, ANNUAL, "영업이익") in amounts or (y, ANNUAL, "매출액") in amounts)
    rows = []
    for y in years:
        p = by_year[y]
        ocf = annual_flow(amounts, y, OCF)
        rows.append(YearRow(y, p["revenue"], p["operating_income"], p["net_income"], ocf,
                            free_cash_flow(ocf, annual_flow(amounts, y, CAPEX), annual_flow(amounts, y, INTANGIBLE))))
    return rows


def _rising(values: List[Optional[int]], positive: bool = False) -> Optional[bool]:
    if any(v is None for v in values):
        return None
    if positive and any(v <= 0 for v in values):
        return False
    return all(b > a for a, b in zip(values, values[1:]))


def _series(rows: List[YearRow], attr: str) -> str:
    return " → ".join(f"{r.year} {_eok(getattr(r, attr))}" for r in rows)


def _ttm_operating(amounts: Amounts, last_year: YearRow) -> Optional[Dict]:
    """이어진 최근 4개 분기의 영업이익·매출 합. 분기가 이어지지 않으면 최근 사업연도 (그보다 새 분기가 없을 때만)."""
    quarters = [p for p in build_periods(amounts, "quarter") if p["operating_income"] is not None]
    last4 = quarters[-4:]
    if len(last4) == 4:
        year0, q0 = last4[0]["period"].split(".")
        year1, q1 = last4[-1]["period"].split(".")
        continuous = (int(year1) * 4 + int(q1[0])) - (int(year0) * 4 + int(q0[0])) == 3
    else:
        continuous = False
    if not continuous:
        newer = quarters and int(quarters[-1]["period"].split(".")[0]) > last_year.year
        if newer or last_year.operating_income is None:
            return None
        return {"label": f"{last_year.year}년", "operating_income": last_year.operating_income, "revenue": last_year.revenue}
    revenue = [p["revenue"] for p in last4]
    return {"label": f"{last4[0]['period']}~{last4[-1]['period']}",
            "operating_income": sum(p["operating_income"] for p in last4),
            "revenue": sum(revenue) if None not in revenue else None}


def _accrual(three: List[YearRow]) -> Check:
    label = f"발생액 품질: 최근 3년 ΣOCF ≥ {ACCRUAL_RATIO} × Σ순이익"
    ocf_sum = None if any(r.ocf is None for r in three) else sum(r.ocf for r in three)
    ni_sum = None if any(r.net_income is None for r in three) else sum(r.net_income for r in three)
    if ocf_sum is None or ni_sum is None:
        return Check(label, None, "영업현금흐름 또는 순이익 데이터 없음")
    return Check(label, ni_sum > 0 and ocf_sum >= ACCRUAL_RATIO * ni_sum,
                 f"ΣOCF {_eok(ocf_sum)}, Σ순이익 {_eok(ni_sum)}"
                 + (f" (비율 {ocf_sum / ni_sum:.2f})" if ni_sum > 0 else " (순이익 합이 0 이하)"))


def _ocf_positive(three: List[YearRow]) -> Check:
    ocf_sum = None if any(r.ocf is None for r in three) else sum(r.ocf for r in three)
    return Check("최근 3년 영업현금흐름 합 흑자", None if ocf_sum is None else ocf_sum > 0, f"ΣOCF {_eok(ocf_sum)}")


def _against_separate(check, consolidated: List[YearRow], separate: List[YearRow]) -> Check:
    """연결로 어긋난 현금흐름 기준이 같은 연도의 별도로는 맞으면 판정하지 않는다 (둘 다 보여 준다).
    연결 순이익 합이 흑자일 때만 — 적자로 어긋난 것은 자회사 손실이지 현금흐름 왜곡이 아니다."""
    result = check(consolidated)
    by_year = {r.year: r for r in separate}
    if result.passed is not False or any(r.year not in by_year for r in consolidated):
        return result
    if any(r.net_income is None for r in consolidated) or sum(r.net_income for r in consolidated) <= 0:
        return result
    other = check([by_year[r.year] for r in consolidated])
    if not other.passed:
        return result
    return Check(result.label, None, f"연결 {result.detail} / 별도 {other.detail} — 연결과 별도가 엇갈려 판정하지 않음 "
                                     "(금융 자회사의 대출 증감 등이 연결 영업현금흐름에 섞였을 수 있다)")


def classify(amounts: Amounts, separate: Optional[Amounts] = None,
             loss_years: int = LOSS_YEARS, damage_years: int = DAMAGE_YEARS) -> CompanyType:
    """separate: 연결 회사의 별도 실적·현금흐름 (현금흐름 기준 대조용).
    loss_years·damage_years: 턴어라운드의 영업적자·마진 훼손을 찾는 직전 사업연도 수."""
    rows = year_rows(amounts)
    separate_rows = year_rows(separate) if separate else []
    recent = rows[-HISTORY_YEARS:]
    if without_revenue(amounts):
        return CompanyType(UNDETERMINED, None, "매출액 계정이 없는 회사(은행·증권·보험 등)라 유형을 판정하지 않습니다", rows)
    if not rows:
        return CompanyType(UNDETERMINED, None, "사업보고서 실적이 없어 유형을 판정하지 않습니다", rows)

    checks: Dict[str, List[Check]] = {}
    last = rows[-1]
    three = rows[-3:]

    checks[EMERGING] = [
        Check(f"연간 실적 {HISTORY_YEARS}개년 미만 (이력 부족)", len(rows) < HISTORY_YEARS,
              f"사업보고서 {len(rows)}개년 ({rows[0].year}~{last.year})"),
        Check(f"최근 연도 매출 {PRE_REVENUE / 1e8:,.0f}억 원 미만 (상업화 전)",
              None if last.revenue is None else last.revenue < PRE_REVENUE, f"{last.year} 매출 {_eok(last.revenue)}"),
    ]

    accrual = _against_separate(_accrual, three, separate_rows)
    checks[COMPOUNDER] = [
        Check("매출 3개년 연속 증가", _rising([r.revenue for r in recent]) if len(recent) == HISTORY_YEARS else None,
              _series(recent, "revenue")),
        Check("영업이익 3개년 연속 증가 (모두 흑자)",
              _rising([r.operating_income for r in recent], positive=True) if len(recent) == HISTORY_YEARS else None,
              _series(recent, "operating_income")),
        Check(f"영업이익률 {HIGH_MARGIN:.0f}% 이상 ({last.year})", None if last.margin is None else last.margin >= HIGH_MARGIN,
              "-" if last.margin is None else f"{last.margin:.1f}%"),
        accrual,
    ]

    ttm = _ttm_operating(amounts, last)
    ocf_ttm = ttm_flow(amounts, OCF)
    troughs = []
    window = max(loss_years, damage_years)
    for prev, cur in zip(rows[-window - 1:-1], rows[-window:]):  # 오래된 순
        back = last.year - cur.year + 1  # 직전 몇 번째 사업연도인지
        if back <= loss_years and cur.operating_income is not None and cur.operating_income <= 0:
            troughs.append((cur, f"{cur.year} 영업적자 {_eok(cur.operating_income)}"))
        elif (back <= damage_years and cur.margin is not None and prev.margin is not None and prev.margin > 0
              and cur.margin < prev.margin * DAMAGED_MARGIN):
            troughs.append((cur, f"{cur.year} 영업이익률 {prev.margin:.1f}% → {cur.margin:.1f}%"))
    # 반등은 가장 최근 저점과 견준다 — 더 오래된 저점과 견주면 이익률이 계속 떨어지는 회사도 반등으로 본다
    trough_margin = troughs[-1][0].margin if troughs else None
    ttm_margin = ttm["operating_income"] / ttm["revenue"] * 100 if ttm and ttm["revenue"] and ttm["revenue"] > 0 else None
    if not ttm:
        rebound = Check("흑자 반등: 최근 4분기 영업이익 흑자, 가장 최근 저점보다 높은 이익률", None, "이어진 4개 분기 실적 없음")
    else:
        recovered = ttm["operating_income"] > 0 and (trough_margin is None or ttm_margin is None or ttm_margin > trough_margin)
        rebound = Check("흑자 반등: 최근 4분기 영업이익 흑자, 가장 최근 저점보다 높은 이익률", recovered,
                        f"{ttm['label']} 영업이익 {_eok(ttm['operating_income'])}"
                        + (f", 이익률 {ttm_margin:.1f}%" if ttm_margin is not None else ""))
    checks[TURNAROUND] = [
        Check(f"직전 {loss_years}개년 내 영업적자 또는 직전 {damage_years}개년 내 마진 훼손 (전년 이익률의 절반 아래)", bool(troughs),
              ", ".join(t for _, t in troughs) or "해당 연도 없음"),
        rebound,
        Check("영업현금흐름 흑자 (최근 4분기)", None if not ocf_ttm else ocf_ttm.amount > 0,
              f"{ocf_ttm.label} {_eok(ocf_ttm.amount)}" if ocf_ttm else "영업현금흐름 데이터 없음"),
    ]

    profitable = [r for r in recent if r.operating_income is not None]
    checks[CYCLICAL] = [
        Check(f"최근 {len(recent)}개년 중 {len(recent) - 1}개년 이상 영업흑자",
              None if len(profitable) < len(recent) or len(recent) < 3 else
              sum(r.operating_income > 0 for r in recent) >= len(recent) - 1,
              _series(recent, "operating_income")),
        _against_separate(_ocf_positive, three, separate_rows),
    ]

    for category in CATEGORIES:
        results = [c.passed for c in checks[category]]
        hit = any(results) if category == EMERGING else (results and all(r is True for r in results))
        if hit:
            met = [c.label for c in checks[category] if c.passed]
            return CompanyType(MATCHED, category, f"{category}: " + ", ".join(met), rows, checks,
                               {category: QUALITATIVE[category]})
    # 어긋난 기준이 없는데 데이터가 없는 기준이 있는 유형은 맞는지 모른다 — '해당 없음'이라고 하지 않는다
    unknown = [cat for cat in (COMPOUNDER, TURNAROUND, CYCLICAL)
               if not any(c.passed is False for c in checks[cat]) and any(c.passed is None for c in checks[cat])]
    held = [c for cat in unknown for c in checks[cat] if c.passed is None]
    if held:
        missing = [c.label + (" (연결·별도 엇갈림)" if "엇갈려" in c.detail else " (데이터 없음)") for c in held]
        return CompanyType(UNDETERMINED, None, "판정을 보류한 기준이 있어 유형을 정하지 않습니다: " + ", ".join(missing),
                           rows, checks)
    return CompanyType(NONE, None, "네 유형 중 기준을 모두 충족하는 유형이 없습니다", rows, checks)
