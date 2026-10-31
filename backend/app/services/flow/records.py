"""실행 기록: 저장한 흐름이 그날 고른 종목을 남긴다 (채점은 performance.py).

고른 종목 = 결과 노드에 닿은 종목 (결과 노드가 여럿이면 합치고 순서는 앞 노드부터).
화면에서 고친 뒤 저장하지 않은 그래프로 돌린 결과는 남기지 않는다 — 무엇을 채점하는지 흐려진다.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ...models.analysis_flow import AnalysisFlow, FlowRun
from ...utils.time import utcnow
from .executor import FlowGraph
from .nodes import REGISTRY

def _canonical(graph: FlowGraph) -> tuple:
    """위치·연결 id를 뺀 그래프 모양. 설정은 기본값을 채운 뒤 비교해 빈 값과 기본값을 같게 본다."""
    nodes = []
    for n in graph.nodes:
        params: Any = n.params
        if n.type in REGISTRY:
            try:
                params = REGISTRY[n.type].Params.model_validate(n.params).model_dump()
            except ValidationError:
                pass
        nodes.append((n.id, n.type, repr(sorted(params.items()))))
    return tuple(sorted(nodes)), tuple(sorted((e.source, e.target) for e in graph.edges))


def same_graph(a: FlowGraph, b: FlowGraph) -> bool:
    return _canonical(a) == _canonical(b)


class PickCollector:
    """실행 이벤트를 받아 결과 노드의 종목을 모은다. 결과 노드가 하나라도 끝나지 못하면 기록하지 않는다."""

    def __init__(self, graph: FlowGraph):
        self.result_ids = [n.id for n in graph.nodes if n.type in REGISTRY and REGISTRY[n.type].category == "result"]
        self.rows: Dict[str, List[Dict[str, str]]] = {}

    def feed(self, event: Dict[str, Any]) -> None:
        data = event.get("data", {})
        if event["type"] == "node_done" and data.get("id") in self.result_ids:
            self.rows[data["id"]] = [{"code": r["code"], "name": r.get("name") or r["code"]} for r in data["dataset"]["rows"]]

    def picks(self) -> Optional[List[Dict[str, str]]]:
        if not self.result_ids or any(i not in self.rows for i in self.result_ids):
            return None
        seen: Dict[str, Dict[str, str]] = {}
        for node_id in self.result_ids:
            for r in self.rows[node_id]:
                seen.setdefault(r["code"], r)
        return list(seen.values())


def record_run(db: Session, flow_id: int, run_date: date, trigger: str, picks: List[Dict[str, str]]) -> None:
    """흐름·날짜마다 한 행. 같은 날 다시 돌리면 마지막 결과로 덮어쓴다."""
    stmt = insert(FlowRun).values(flow_id=flow_id, run_date=run_date, trigger=trigger, picks=picks, created_at=utcnow())
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_flow_runs_flow_date",
        set_={"trigger": stmt.excluded.trigger, "picks": stmt.excluded.picks, "created_at": stmt.excluded.created_at},
    ))
    db.commit()


def previous_picks(db: Session, flow_id: int, before: date) -> Optional[List[Dict[str, str]]]:
    run = (
        db.query(FlowRun)
        .filter(FlowRun.flow_id == flow_id, FlowRun.run_date < before)
        .order_by(FlowRun.run_date.desc())
        .first()
    )
    return run.picks if run else None


def recordable(flow: Optional[AnalysisFlow], graph: FlowGraph) -> bool:
    return flow is not None and same_graph(FlowGraph.model_validate(flow.graph), graph)
