"""데이터 스킬들이 함께 쓰는 도우미."""
import re
from datetime import date, timedelta
from typing import Annotated, Any, Dict, List, Optional

from pydantic import AfterValidator, BaseModel, Field

from ...graph_service import GraphService

# 기간 표기: 숫자+단위(d 일, w 주, m 개월, y 년) 또는 ytd(올해, 작년 마지막 거래일 대비). 개월·년은 30·365일로 센다
_PERIOD_RE = re.compile(r"(\d{1,3})([dwmy])|ytd")
_UNITS = {"d": ("일", 1), "w": ("주", 7), "m": ("개월", 30), "y": ("년", 365)}
# 질문에 기간이 없을 때의 기간. 가격 추이와 수익률 순위가 같은 기간을 써야 '수익률 상위 → 추이'가 맞물린다
DEFAULT_PERIOD = "1m"
PERIOD_DESCRIPTION = (
    "조회 기간. 숫자+단위(d 일, w 주, m 개월, y 년) 또는 ytd(올해·연초 이후). "
    "질문에 기간이 있으면 반드시 그 기간을 그대로 적는다 (예: '2주'→2w, '45일'→45d, '2개월'→2m, '2년'→2y, '올해'→ytd) "
    "— 가까운 다른 기간으로 바꾸지 않는다. "
    f"질문에 기간이 없으면 앞선 대화에서 정한 기간, 그것도 없으면 기본값 {DEFAULT_PERIOD}(1개월). 예시의 기간을 옮기지 않는다"
)


def _check_period(spec: str) -> str:
    spec = spec.strip().lower()
    match = _PERIOD_RE.fullmatch(spec)
    if not match or (match.group(1) and int(match.group(1)) == 0):
        raise ValueError(f"기간 표기가 맞지 않습니다: '{spec}' (예: 1w, 45d, 3m, 1y, ytd)")
    return spec


Period = Annotated[str, AfterValidator(_check_period)]


def period_label(spec: str) -> str:
    if spec == "ytd":
        return "연초 이후"
    n, unit = int(spec[:-1]), spec[-1]
    return f"{n}{_UNITS[unit][0]}"


def period_start(spec: str, end: date) -> date:
    """end에서 거슬러 간 시작 기준일. 수익률은 이 날 이전의 가장 가까운 거래일 종가에서 센다."""
    if spec == "ytd":
        return date(end.year - 1, 12, 31)
    n, unit = int(spec[:-1]), spec[-1]
    return end - timedelta(days=n * _UNITS[unit][1])


def period_days(spec: str) -> int:
    """기간의 시작점까지 가져오려면 오늘부터 거슬러 가져올 가격 일수 (시작점 앞 휴장일 여유 포함)."""
    today = date.today()
    return (today - period_start(spec, today)).days + 10


def period_base(prices: List[Dict], spec: str) -> Optional[Dict]:
    """기간의 시작점: 마지막 거래일에서 기간만큼 거슬러 간 날 이전의 가장 가까운 거래일 가격. 데이터가 그만큼 없으면 None.
    가격 추이·기간 수익률·수익률 순위가 모두 이 시작점을 써서 같은 기간이면 같은 수익률이 나온다."""
    target = period_start(spec, date.fromisoformat(prices[-1]["date"])).isoformat()
    past = [p for p in prices if p["date"] <= target]
    return past[-1] if past else None


ETF_NAMES_DESCRIPTION = "ETF 이름 또는 6자리 코드. 사용자가 말한 이름을 그대로 적는다 (예: 'KODEX 200')"


class ETFListArgs(BaseModel):
    etfs: List[str] = Field(min_length=1, max_length=5, description=ETF_NAMES_DESCRIPTION)


def min_weight_field(target: str):
    return Field(None, gt=0, le=100, description=(
        f"이 비중(%) 이상인 {target}만 남긴다 (예: '비중 10% 넘는'이면 10). 조건이 없으면 비운다. "
        "남는 개수는 실행해 봐야 알므로, 이 결과를 받는 슬롯은 나눠 만들지 말고 하나만 만든다 (예: '@이름.1-5')"
    ))


def cut_note(passed: int, shown: int, target: str) -> List[str]:
    """비중 조건을 통과한 대상이 표시 개수보다 많으면 잘렸다고 알린다 ('10% 넘는 ETF들'이 몇 개인지 숨기지 않게)."""
    return [f"조건에 맞는 {target} {passed}개 중 상위 {shown}개만 표시했습니다"] if passed > shown else []


def object_particle(word: str) -> str:
    """목적격 조사: 마지막 글자가 한글이면 받침으로 을/를을 고르고, 영문·숫자로 끝나면 '을(를)'."""
    last = word.strip()[-1:] if word.strip() else ""
    if not ("가" <= last <= "힣"):
        return "을(를)"
    return "을" if (ord(last) - ord("가")) % 28 else "를"


def missing_notes(missing: List[str]) -> List[str]:
    return [f"찾지 못한 ETF: {', '.join(missing)}"] if missing else []


def node(graph: GraphService, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # DB 오류를 "데이터 없음"으로 삼키지 않고 슬롯 실패로 드러낸다
    return [GraphService.parse_agtype(r["result"]) for r in graph.execute_cypher(cypher, params, raise_errors=True)]


def period_span(start: str, end: str, label: str = "") -> str:
    """결과에 보이는 조회 구간 문구 (예: '조회 기간: 2026-09-24 ~ 2026-10-24 (1개월)')."""
    return f"조회 기간: {start} ~ {end}" + (f" ({label})" if label else "")


def pct_change(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if not start or end is None:
        return None
    return round((end - start) / start * 100, 2)


def format_value(value: Any, fmt: str) -> str:
    """요약 텍스트용 서식 (LLM이 단위를 헷갈리지 않게). 화면 표시 서식은 프런트가 따로 한다."""
    if value is None:
        return "-"
    if fmt == "percent":
        return f"{value:.2f}%"
    if fmt == "krw":
        eok = int(value) // 1_0000_0000
        return f"{eok // 1_0000:,}조 {eok % 1_0000:,}억원" if eok >= 1_0000 else f"{eok:,}억원"
    if fmt == "price":
        return f"{value:,.0f}원"
    if fmt == "number" and isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)
