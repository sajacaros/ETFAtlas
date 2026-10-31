"""슬롯 간 참조: 한 슬롯의 인자가 다른 슬롯이 내보낸 대상(ETF·종목)을 '@이름.순위'로 가리킨다.

'@rank.1'은 rank 슬롯이 내보낸 목록의 1위, '@rank.1-3'은 1~3위(목록 인자 안에서만)다.
참조는 어느 스킬의 어느 문자열 인자에든 쓸 수 있고, 오케스트레이터가 실행 직전에 그 대상의 코드로 바꾼다.
참조가 있는 슬롯은 참조한 슬롯이 끝난 뒤에 돈다.
"""
import json
import re
from typing import Any, Dict, Iterable, Iterator, List, Set

REF_RE = re.compile(r"^@([A-Za-z_]\w*)\.(\d+)(?:-(\d+))?$")


class RefError(ValueError):
    pass


class RefPastEnd(RefError):
    """범위 참조('@rank.6-10')가 통째로 결과 밖이다. 필터처럼 결과 개수를 미리 알 수 없을 때 생기고,
    계획을 고쳐도 데이터가 늘지 않으므로 다시 설계하지 않는다."""


def strings(value: Any) -> Iterator[str]:
    """인자(model_dump 결과) 안의 문자열 전부 — 참조는 어느 문자열 인자에든 올 수 있다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def refs_in(args: Dict[str, Any]) -> Set[str]:
    """인자(model_dump 결과)가 참조하는 슬롯 이름들."""
    return {m.group(1) for s in strings(args) if (m := REF_RE.match(s.strip()))}


def with_dependents(slots: Iterable[Any], seeds: Set[str]) -> Set[str]:
    """seeds(슬롯 id)와, 그 결과를 참조로 (이어서) 받는 슬롯의 id. 슬롯은 id·depends_on이 있으면 된다."""
    slots = list(slots)
    out = set(seeds)
    changed = True
    while changed:
        changed = False
        for s in slots:
            if s.id not in out and set(s.depends_on) & out:
                out.add(s.id)
                changed = True
    return out


def _pick(match: re.Match, exports: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    name, start, end = match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))
    items = exports.get(name, [])
    if start < 1 or end < start:
        raise RefError(f"참조 범위가 잘못됐습니다: {match.group(0)}")
    if len(items) < start:
        if match.group(3):
            raise RefPastEnd(f"'{name}' 영역의 결과가 {len(items)}개뿐이라 이 영역에 보여줄 대상이 없습니다")
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


def expanded(args: Dict[str, Any]) -> Dict[str, Any]:
    """실행 때 참조가 펼쳐질 모양 (계획 검증용). 범위 참조는 끝 순위만큼의 항목이 된다 —
    앞 슬롯의 결과가 그보다 적으면 실행 때는 더 짧아지므로, 인자 개수 제한은 이 최대치로 검사한다."""
    ends: Dict[str, int] = {}
    for s in strings(args):
        m = REF_RE.match(s.strip())
        if m:
            ends[m.group(1)] = max(ends.get(m.group(1), 0), int(m.group(3) or m.group(2)))
    placeholder = {"code": "000000", "name": ""}
    return resolve(args, {name: [placeholder] * end for name, end in ends.items()})


def rank_gaps(values: List[Any]) -> Dict[str, List[int]]:
    """범위 참조('@rank.1-4')로 나눠 담은 순위 사이에 빠진 순위 {이름: [순위]}.
    '1위와 3위'처럼 한 순위씩 고른 참조만 있으면 일부러 고른 것으로 보고 묻지 않는다."""
    by_name: Dict[str, List[re.Match]] = {}
    for v in values:
        m = REF_RE.match(v.strip()) if isinstance(v, str) else None
        if m and int(m.group(2)) <= int(m.group(3) or m.group(2)):  # 거꾸로 된 범위는 따로 알린다
            by_name.setdefault(m.group(1), []).append(m)
    gaps = {}
    for name, matches in by_name.items():
        if not any(m.group(3) for m in matches):
            continue
        ranks = {r for m in matches for r in range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)}
        missing = [r for r in range(min(ranks), max(ranks) + 1) if r not in ranks]
        if missing:
            gaps[name] = missing
    return gaps


def split_hint(items: List[Any], max_items: int) -> str:
    """펼치면 max_items를 넘는 목록 인자를 슬롯 여럿으로 나누는 방법 (플래너에게 돌려줄 문구).
    이름으로 적은 항목은 슬롯마다 넣는다고 보고, 남은 자리만큼 순위를 나눈다.
    예: ['KODEX 200', '@rank.1-10'], 5 → '@rank.1-4', '@rank.5-8', '@rank.9-10' (슬롯마다 'KODEX 200' 포함)."""
    fixed = list(dict.fromkeys(v for v in items if not (isinstance(v, str) and REF_RE.match(v.strip()))))
    matches = [REF_RE.match(v.strip()) for v in items if isinstance(v, str) and REF_RE.match(v.strip())]
    names = {m.group(1) for m in matches}
    if len(names) != 1:
        return "범위를 줄이거나 같은 스킬 슬롯을 여럿으로 나눠 담으세요"
    name = names.pop()
    # 빠진 순위가 있으면 실수로 보고 처음~끝 순위를 빠짐없이 나눈다 (빠진 채로 나누라고 하면 그대로 굳는다)
    first = min(int(m.group(2)) for m in matches)
    last = max(int(m.group(3) or m.group(2)) for m in matches)
    ranks = list(range(first, last + 1))
    room = max_items - len(fixed)
    if room < 1:
        return f"이름으로 적은 항목이 {len(fixed)}개라 순위를 넣을 자리가 없습니다. 항목을 줄이세요"
    chunks = [ranks[i:i + room] for i in range(0, len(ranks), room)]
    # 순위만 보여 주면 이름으로 적은 항목을 빼먹고 옮겨 적는다 — 슬롯마다 넣을 목록 전체를 보여 준다
    lists = ", ".join(
        json.dumps([*fixed, f"@{name}.{c[0]}" if len(c) == 1 else f"@{name}.{c[0]}-{c[-1]}"], ensure_ascii=False)
        for c in chunks
    )
    keep = f" 이름으로 적은 {', '.join(repr(v) for v in fixed)}는 슬롯마다 넣어 슬롯당 순위는 {room}개까지입니다." if fixed else ""
    span = f"{ranks[0]}~{ranks[-1]}위" if len(ranks) > 1 else f"{ranks[0]}위"
    return (f"한 슬롯에 {max_items}개까지입니다.{keep} 이 스킬 슬롯들이 받는 {span}를 모두 합쳐, "
            f"기존 슬롯 대신 슬롯 {len(chunks)}개에 각각 {lists}를 담으세요")


def describe(args: Dict[str, Any], exports: Dict[str, List[Dict[str, str]]], titles: Dict[str, str]) -> List[str]:
    """화면에 남길 참조 풀이. 예: "'삼성전자 비중 높은 ETF' 1위: WON 200(448100)"."""
    notes = []
    for s in strings(args):
        m = REF_RE.match(s.strip())
        if not m:
            continue
        name, start, end = m.group(1), m.group(2), m.group(3)
        rank = f"{start}~{end}위" if end else f"{start}위"
        items = _pick(m, exports)
        notes.append(f"'{titles.get(name, name)}' {rank}: " + ", ".join(f"{i['name']}({i['code']})" for i in items))
    return notes
