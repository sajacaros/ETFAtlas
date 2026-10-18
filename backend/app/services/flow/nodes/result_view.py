from typing import List

from pydantic import BaseModel, Field

from ..base import FlowContext, Node, StockSet, result


class ResultParams(BaseModel):
    sort_by: str = Field("", title="정렬 기준", description="열 이름(예: ret, rsi). 비우면 들어온 순서", json_schema_extra={"widget": "field"})
    descending: bool = Field(True, title="큰 값부터")
    limit: int = Field(50, ge=1, le=300, title="최대 종목 수")


class ResultNode(Node):
    type = "result"
    label = "결과"
    category = "result"
    icon = "📋"
    description = "들어온 종목을 표로 모아 비교한다. 정렬 기준과 최대 종목 수를 정할 수 있다"
    Params = ResultParams

    async def run(self, params: ResultParams, inputs: List[StockSet], ctx: FlowContext):
        source = inputs[0]
        rows = list(source.rows.items())
        if params.sort_by:
            if params.sort_by not in source.fields:
                raise ValueError(f"정렬할 열이 없습니다: {params.sort_by} (가능: {', '.join(source.fields) or '없음'})")
            present = [r for r in rows if r[1].get(params.sort_by) is not None]
            absent = [r for r in rows if r[1].get(params.sort_by) is None]
            present.sort(key=lambda kv: kv[1][params.sort_by], reverse=params.descending)
            rows = present + absent  # 값 없는 종목은 항상 뒤로
        items = source.derive(dict(rows[: params.limit]))
        if len(rows) > params.limit:
            items.notes.append(f"{len(rows):,}종목 중 {params.limit}종목만 보여 줍니다")
        yield result(items)
