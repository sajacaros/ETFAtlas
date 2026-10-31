"""데이터 스킬들이 함께 쓰는 도우미."""
from typing import Dict, List

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...content import BarView, DonutView, TableView, TreemapView
from ...entities import normalize_name
from ...graph_service import GraphService, node

DONUT_MAX_SLICES = 8  # 넘으면 나머지를 '기타'로 묶는다

# 질문에 기간이 없을 때의 기간. 가격 추이와 수익률 순위가 같은 기간을 써야 '수익률 상위 → 추이'가 맞물린다
DEFAULT_PERIOD = "1m"
PERIOD_DESCRIPTION = (
    "조회 기간. 숫자+단위(d 일, w 주, m 개월, y 년) 또는 ytd(올해·연초 이후). "
    "질문에 기간이 있으면 반드시 그 기간을 그대로 적는다 (예: '2주'→2w, '45일'→45d, '2개월'→2m, '2년'→2y, '올해'→ytd) "
    "— 가까운 다른 기간으로 바꾸지 않는다. "
    f"질문에 기간이 없으면 앞선 대화에서 정한 기간, 그것도 없으면 기본값 {DEFAULT_PERIOD}(1개월). 예시의 기간을 옮기지 않는다"
)


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


def period_span(start: str, end: str, label: str = "") -> str:
    """결과에 보이는 조회 구간 문구 (예: '조회 기간: 2026-09-24 ~ 2026-10-24 (1개월)')."""
    return f"조회 기간: {start} ~ {end}" + (f" ({label})" if label else "")


def share_view(display: str, name: str = "name", value: str = "weight"):
    """비중 목록(구성종목·합산 비중)의 표시 방식 → 화면 view. 고르지 않은 방식은 표."""
    if display == "treemap":
        return TreemapView(name=name, value=value)
    if display == "donut":
        return DonutView(name=name, value=value)
    if display == "bar":
        return BarView(x=name, y=[value], horizontal=True)
    return TableView()


def theme_word(theme: str) -> str:
    """'반도체 ETF' → '반도체'."""
    word = theme.strip()
    return word[:-3].strip() if word.upper().endswith("ETF") else word


def theme_etfs(db: Session, theme: str) -> List[Dict]:
    """태그 이름과 같으면 그 태그의 ETF, 아니면 이름에 그 단어가 든 ETF. 순자산 큰 순."""
    query = normalize_name(theme)
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
