"""흐름 그래프를 위상 순서로 실행한다.

그래프 모양이 잘못됐으면(모르는 노드, 없는 노드로 가는 연결, 순환) 실행 전에 FlowGraphError를 낸다.
노드 하나가 실패하면 그 뒤로 이어진 노드만 건너뛰고 다른 갈래는 계속 돈다.

내는 이벤트: {"type", "data"}
  run_start {order}  node_start {id}  node_progress {id, message}
  node_done {id, count, badge, dataset, notes, seconds}  node_error {id, message}  node_skipped {id, message}
  run_done {}
"""
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from .base import FlowContext, StockSet
from .nodes import REGISTRY

logger = logging.getLogger(__name__)


class FlowNodeIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: str
    params: Dict[str, Any] = {}
    position: Optional[Dict[str, float]] = None


class FlowEdgeIn(BaseModel):
    id: Optional[str] = None
    source: str
    target: str


class FlowGraph(BaseModel):
    nodes: List[FlowNodeIn] = Field(default_factory=list, max_length=50)
    edges: List[FlowEdgeIn] = Field(default_factory=list, max_length=200)


class FlowGraphError(ValueError):
    pass


def topo_order(graph: FlowGraph) -> List[str]:
    ids = [n.id for n in graph.nodes]
    if len(set(ids)) != len(ids):
        raise FlowGraphError("노드 id가 겹칩니다")
    for n in graph.nodes:
        if n.type not in REGISTRY:
            raise FlowGraphError(f"모르는 노드 종류입니다: {n.type}")
    known = set(ids)
    for e in graph.edges:
        if e.source not in known or e.target not in known:
            raise FlowGraphError("없는 노드로 이어진 연결이 있습니다")
        if e.source == e.target:
            raise FlowGraphError("노드가 자기 자신으로 이어져 있습니다")
    indegree = {i: 0 for i in ids}
    for e in graph.edges:
        indegree[e.target] += 1
    order, ready = [], [i for i in ids if indegree[i] == 0]
    while ready:
        current = ready.pop(0)
        order.append(current)
        for e in graph.edges:
            if e.source == current:
                indegree[e.target] -= 1
                if indegree[e.target] == 0:
                    ready.append(e.target)
    if len(order) != len(ids):
        raise FlowGraphError("연결이 순환합니다")
    return order


def _input_error(node_cls, count: int) -> Optional[str]:
    if node_cls.max_inputs == 0 and count:
        return f"{node_cls.label}에는 입력을 연결할 수 없습니다"
    if count < node_cls.min_inputs:
        return f"입력이 {node_cls.min_inputs}개 이상 필요합니다" if node_cls.min_inputs > 1 else "입력을 연결하세요"
    if node_cls.max_inputs is not None and count > node_cls.max_inputs:
        return f"입력은 {node_cls.max_inputs}개까지입니다"
    return None


def _params_error(e: ValidationError) -> str:
    first = e.errors()[0]
    return f"설정 오류 ({'.'.join(str(p) for p in first['loc'])}): {first['msg']}"


async def run_flow(graph: FlowGraph, ctx: FlowContext) -> AsyncIterator[Dict[str, Any]]:
    order = topo_order(graph)
    nodes = {n.id: n for n in graph.nodes}
    sources_of = {i: [e.source for e in graph.edges if e.target == i] for i in order}
    outputs: Dict[str, StockSet] = {}
    failed: set = set()

    yield {"type": "run_start", "data": {"order": order}}
    for node_id in order:
        if ctx.stop.is_set():
            break
        spec = nodes[node_id]
        node_cls = REGISTRY[spec.type]
        upstream = sources_of[node_id]
        if any(s in failed for s in upstream):
            failed.add(node_id)
            yield {"type": "node_skipped", "data": {"id": node_id, "message": "앞 노드가 실패해 실행하지 않았습니다"}}
            continue
        error = _input_error(node_cls, len(upstream))
        params = None
        if error is None:
            try:
                params = node_cls.Params.model_validate(spec.params)
            except ValidationError as e:
                error = _params_error(e)
        if error:
            failed.add(node_id)
            yield {"type": "node_error", "data": {"id": node_id, "message": error}}
            continue

        yield {"type": "node_start", "data": {"id": node_id}}
        started = time.monotonic()
        items: Optional[StockSet] = None
        try:
            async for event in node_cls().run(params, [outputs[s] for s in upstream], ctx):
                if event["type"] == "progress":
                    yield {"type": "node_progress", "data": {"id": node_id, "message": event["message"]}}
                elif event["type"] == "result":
                    items = event["items"]
        except ValueError as e:  # 사용자가 고칠 수 있는 설정·데이터 문제
            failed.add(node_id)
            yield {"type": "node_error", "data": {"id": node_id, "message": str(e)}}
            continue
        except Exception:
            logger.exception("Flow node %s (%s) failed", node_id, spec.type)  # 내부 오류 문구는 로그에만
            failed.add(node_id)
            yield {"type": "node_error", "data": {"id": node_id, "message": "실행 중 오류가 났습니다"}}
            continue
        if items is None:
            failed.add(node_id)
            yield {"type": "node_error", "data": {"id": node_id, "message": "결과가 없습니다"}}
            continue
        outputs[node_id] = items
        yield {"type": "node_done", "data": {
            "id": node_id,
            "count": len(items.rows),
            "badge": node_cls.badge(items),
            "dataset": items.dataset().model_dump(),
            "notes": items.notes,
            "seconds": round(time.monotonic() - started, 1),
        }}
    yield {"type": "run_done", "data": {}}
