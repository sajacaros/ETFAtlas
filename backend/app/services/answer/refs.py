"""슬롯 간 참조: 한 슬롯의 인자가 다른 슬롯이 내보낸 대상(ETF·종목)을 '@이름.순위'로 가리킨다.

'@rank.1'은 rank 슬롯이 내보낸 목록의 1위, '@rank.1-3'은 1~3위(목록 인자 안에서만)다.
참조는 어느 스킬의 어느 문자열 인자에든 쓸 수 있고, 오케스트레이터가 실행 직전에 그 대상의 코드로 바꾼다.
참조가 있는 슬롯은 참조한 슬롯이 끝난 뒤에 돈다.
"""
import re
from typing import Any, Dict, List, Set

REF_RE = re.compile(r"^@([A-Za-z_]\w*)\.(\d+)(?:-(\d+))?$")


class RefError(ValueError):
    pass


def _walk(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def refs_in(args: Dict[str, Any]) -> Set[str]:
    """인자(model_dump 결과)가 참조하는 슬롯 이름들."""
    return {m.group(1) for s in _walk(args) if (m := REF_RE.match(s.strip()))}


def _pick(match: re.Match, exports: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    name, start, end = match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))
    items = exports.get(name, [])
    if start < 1 or end < start:
        raise RefError(f"참조 범위가 잘못됐습니다: {match.group(0)}")
    if len(items) < start:
        raise RefError(f"'{name}' 영역의 결과가 {len(items)}개뿐이라 {start}위를 쓸 수 없습니다")
    return items[start - 1:end]


def resolve(args: Dict[str, Any], exports: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """참조를 대상 코드로 바꾼 새 인자. 목록 안의 범위 참조('@rank.1-3')는 여러 항목으로 펼친다."""
    def sub(value: Any) -> Any:
        if isinstance(value, str):
            m = REF_RE.match(value.strip())
            if not m:
                return value
            items = _pick(m, exports)
            if len(items) > 1:
                raise RefError(f"하나만 들어가는 인자에 범위를 참조했습니다: {value}")
            return items[0]["code"]
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            out: List[Any] = []
            for v in value:
                m = REF_RE.match(v.strip()) if isinstance(v, str) else None
                if m:
                    out.extend(i["code"] for i in _pick(m, exports))
                else:
                    out.append(sub(v))
            return out
        return value

    return sub(args)


def describe(args: Dict[str, Any], exports: Dict[str, List[Dict[str, str]]], titles: Dict[str, str]) -> List[str]:
    """화면에 남길 참조 풀이. 예: "'삼성전자 비중 높은 ETF' 1위: WON 200(448100)"."""
    notes = []
    for s in _walk(args):
        m = REF_RE.match(s.strip())
        if not m:
            continue
        name, start, end = m.group(1), m.group(2), m.group(3)
        rank = f"{start}~{end}위" if end else f"{start}위"
        items = _pick(m, exports)
        notes.append(f"'{titles.get(name, name)}' {rank}: " + ", ".join(f"{i['name']}({i['code']})" for i in items))
    return notes
