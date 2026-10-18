from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from ..base import FlowContext, Node, StockSet, result


class CombineParams(BaseModel):
    op: Literal["intersection", "union"] = Field(
        "intersection", title="합치는 방식",
        json_schema_extra={"options": {"intersection": "교집합 (모든 입력에 있는 종목)", "union": "합집합 (하나라도 있는 종목)"}},
    )


def combine(inputs: List[StockSet], op: str) -> StockSet:
    """첫 입력의 순서를 따르고, 같은 종목의 값은 입력 순서대로 합친다 (앞 입력 값이 남는다)."""
    if op == "intersection":
        common = set(inputs[0].rows).intersection(*(i.rows for i in inputs[1:]))
        codes = [c for c in inputs[0].rows if c in common]
    else:
        codes = list(dict.fromkeys(c for i in inputs for c in i.rows))
    rows: Dict[str, Dict] = {}
    for code in codes:
        merged: Dict = {}
        for i in reversed(inputs):
            merged.update(i.rows.get(code, {}))
        rows[code] = merged
    out = StockSet(rows=rows)
    for i in inputs:
        for key, f in i.fields.items():
            out.fields.setdefault(key, f)
        out.notes.extend(n for n in i.notes if n not in out.notes)
    return out


class CombineNode(Node):
    type = "combine"
    label = "합치기"
    category = "combine"
    icon = "∩"
    description = "두 개 이상의 갈래를 합친다. 교집합은 모든 입력에 있는 종목만, 합집합은 하나라도 있는 종목을 남긴다"
    Params = CombineParams
    min_inputs = 2
    max_inputs = None

    async def run(self, params: CombineParams, inputs: List[StockSet], ctx: FlowContext):
        items = combine(inputs, params.op)
        name = "교집합" if params.op == "intersection" else "합집합"
        items.notes.append(f"입력 {len(inputs)}개의 {name}: " + " · ".join(f"{len(i.rows):,}" for i in inputs) + f" → {len(items.rows):,}종목")
        yield result(items)
