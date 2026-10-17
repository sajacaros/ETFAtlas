"""노드: 분석 흐름의 한 단계. 노드 1종 = 파일 1개 (Params 스키마 + run).

노드 사이로는 StockSet(종목 → 행)이 흐른다. 행에는 종목코드·이름과 앞 노드들이 계산한 값이 쌓이고,
fields가 그 값의 이름·서식을 들고 다녀서 결과 표가 열을 따로 정하지 않아도 된다.

run()이 내는 이벤트 (dict):
  {"type": "progress", "message"}   진행 상황 (AI 분석처럼 오래 걸리는 노드)
  {"type": "result", "items"}       마지막에 한 번, items는 StockSet
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, ClassVar, Dict, List, Literal, Optional, Type, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_config import AIConfig
from ..answer.schemas import DataField, Dataset
from .market_data import MarketData

PREVIEW_ROWS = 300  # 노드 결과 탭에 보내는 최대 행 수


@dataclass
class StockSet:
    rows: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 코드 → {code, name, ...값}, 순서가 표시 순서
    fields: Dict[str, DataField] = field(default_factory=dict)  # code·name 외 값 열
    notes: List[str] = field(default_factory=list)

    def add_field(self, key: str, label: str, fmt: str = "number") -> None:
        self.fields[key] = DataField(key=key, label=label, format=fmt)

    def derive(self, rows: Dict[str, Dict[str, Any]]) -> "StockSet":
        """같은 열 정의로 행만 바꾼 새 집합 (거르기·정렬)."""
        return StockSet(rows=rows, fields=dict(self.fields), notes=list(self.notes))

    def dataset(self, limit: int = PREVIEW_ROWS) -> Dataset:
        fields = [DataField(key="code", label="코드", format="text"), DataField(key="name", label="종목", format="text")]
        fields += list(self.fields.values())
        keys = [f.key for f in fields]
        rows = [{k: row.get(k) for k in keys} for row in list(self.rows.values())[:limit]]
        return Dataset(fields=fields, rows=rows)


@dataclass
class FlowContext:
    user_id: int
    session_factory: Callable[[], Session]
    ai_config: Optional[AIConfig]
    market: MarketData
    stop: asyncio.Event


class Node:
    type: ClassVar[str]
    label: ClassVar[str]
    category: ClassVar[str]  # source | filter | combine | ai | result
    description: ClassVar[str]
    icon: ClassVar[str] = ""
    Params: ClassVar[Type[BaseModel]]
    min_inputs: ClassVar[int] = 1
    max_inputs: ClassVar[Optional[int]] = 1

    async def run(self, params: BaseModel, inputs: List[StockSet], ctx: FlowContext) -> AsyncIterator[Dict[str, Any]]:
        raise NotImplementedError
        yield {}

    @staticmethod
    def badge(items: StockSet) -> str:
        """캔버스 노드에 붙는 짧은 결과 문구."""
        return f"{len(items.rows):,}종목"


def result(items: StockSet) -> Dict[str, Any]:
    return {"type": "result", "items": items}


def _param_type(annotation) -> tuple[str, Optional[List[Dict[str, str]]], bool]:
    """pydantic 필드 타입 → (입력 종류, 선택지, 비워도 되는지)."""
    nullable = False
    if get_origin(annotation) is not None and type(None) in get_args(annotation):
        nullable = True
        annotation = next(a for a in get_args(annotation) if a is not type(None))
    if get_origin(annotation) is Literal:
        return "select", [{"value": v, "label": v} for v in get_args(annotation)], nullable
    if annotation is bool:
        return "bool", None, nullable
    if annotation in (int, float):
        return "number", None, nullable
    return "text", None, nullable


def param_spec(model: Type[BaseModel]) -> List[Dict[str, Any]]:
    """설정 폼을 그리는 데 필요한 것만. 선택지 이름은 json_schema_extra={"options": {값: 이름}}로 붙인다."""
    specs = []
    for key, f in model.model_fields.items():
        kind, options, nullable = _param_type(f.annotation)
        extra = f.json_schema_extra if isinstance(f.json_schema_extra, dict) else {}
        if options and extra.get("options"):
            options = [{"value": o["value"], "label": extra["options"].get(o["value"], o["value"])} for o in options]
        specs.append({
            "key": key,
            "label": f.title or key,
            "help": f.description or "",
            "type": extra.get("widget", kind),
            "options": options,
            "nullable": nullable,
            "default": f.default,
            "show_if": extra.get("show_if"),  # {"param": 값 목록} — 다른 설정값에 따라 보일 때만
        })
    return specs


def node_spec(node: Type[Node]) -> Dict[str, Any]:
    return {
        "type": node.type,
        "label": node.label,
        "category": node.category,
        "description": node.description,
        "icon": node.icon,
        "min_inputs": node.min_inputs,
        "max_inputs": node.max_inputs,
        "params": param_spec(node.Params),
    }
