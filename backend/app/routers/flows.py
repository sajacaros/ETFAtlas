import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.analysis_flow import AnalysisFlow, FlowRun
from ..services.ai_config import load_ai_config
from ..services.flow.base import FlowContext, node_spec
from ..services.flow.executor import FlowGraph, FlowGraphError, run_flow, topo_order
from ..services.flow.market_data import default_market_data
from ..services.flow.nodes import REGISTRY
from ..services.flow.performance import evaluate
from ..services.flow.records import PickCollector, record_run, recordable, today_kst
from ..services.flow.templates import TEMPLATES
from ..utils.session import get_current_user_id
from .chat import _with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter()


class FlowSave(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    graph: FlowGraph


class FlowRunIn(BaseModel):
    graph: FlowGraph
    flow_id: Optional[int] = None  # 저장한 흐름이고 그래프가 저장본과 같으면 고른 종목을 기록한다


class FlowSchedule(BaseModel):
    schedule_enabled: bool
    notify: bool


def _flow_out(flow: AnalysisFlow, with_graph: bool = True) -> Dict[str, Any]:
    out = {
        "id": flow.id,
        "name": flow.name,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
        "schedule_enabled": flow.schedule_enabled,
        "notify": flow.notify,
    }
    if with_graph:
        out["graph"] = flow.graph
    return out


def _get_own(db: Session, user_id: int, flow_id: int) -> AnalysisFlow:
    flow = db.query(AnalysisFlow).filter(AnalysisFlow.id == flow_id, AnalysisFlow.user_id == user_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="스크리너를 찾을 수 없습니다")
    return flow


@router.get("/catalog")
async def get_catalog(user_id: int = Depends(get_current_user_id)):
    return {"nodes": [node_spec(n) for n in REGISTRY.values()], "templates": TEMPLATES}


@router.get("")
async def list_flows(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    flows = db.query(AnalysisFlow).filter(AnalysisFlow.user_id == user_id).order_by(AnalysisFlow.updated_at.desc()).all()
    return [_flow_out(f, with_graph=False) for f in flows]


@router.post("", status_code=201)
async def create_flow(body: FlowSave, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    flow = AnalysisFlow(user_id=user_id, name=body.name.strip(), graph=body.graph.model_dump())
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _flow_out(flow)


@router.get("/{flow_id}")
async def get_flow(flow_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    return _flow_out(_get_own(db, user_id, flow_id))


@router.put("/{flow_id}")
async def update_flow(flow_id: int, body: FlowSave, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    flow = _get_own(db, user_id, flow_id)
    flow.name = body.name.strip()
    flow.graph = body.graph.model_dump()
    db.commit()
    db.refresh(flow)
    return _flow_out(flow)


@router.put("/{flow_id}/schedule")
async def update_schedule(flow_id: int, body: FlowSchedule, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """영업일 장 마감 뒤 자동 실행과 디스코드 알림. 그래프는 바꾸지 않는다."""
    flow = _get_own(db, user_id, flow_id)
    flow.schedule_enabled = body.schedule_enabled
    flow.notify = body.notify
    db.commit()
    db.refresh(flow)
    return _flow_out(flow)


@router.get("/{flow_id}/performance")
async def get_performance(flow_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """기록된 날마다 고른 종목의 사후 수익률을 기준 지수와 비교한다."""
    _get_own(db, user_id, flow_id)
    runs = db.query(FlowRun).filter(FlowRun.flow_id == flow_id).order_by(FlowRun.run_date.desc()).all()
    data = [{"run_date": r.run_date.isoformat(), "trigger": r.trigger, "picks": r.picks} for r in runs]
    return await asyncio.to_thread(evaluate, data, default_market_data())


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    db.delete(_get_own(db, user_id, flow_id))
    db.commit()


@router.post("/run")
async def run(body: FlowRunIn, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """저장하지 않은 그래프도 그대로 실행한다. 그래프 모양 오류는 스트림을 열기 전에 400으로.

    flow_id를 주고 그래프가 저장본과 같으면 결과 노드에 닿은 종목을 오늘 날짜로 기록한다 (run_done의 recorded).
    """
    try:
        topo_order(body.graph)
    except FlowGraphError as e:
        raise HTTPException(status_code=400, detail=str(e))
    flow = None
    if body.flow_id is not None:
        flow = db.query(AnalysisFlow).filter(AnalysisFlow.id == body.flow_id, AnalysisFlow.user_id == user_id).first()
    record = recordable(flow, body.graph)
    collector = PickCollector(body.graph)
    ctx = FlowContext(
        user_id=user_id,
        session_factory=SessionLocal,
        ai_config=load_ai_config(db),
        market=default_market_data(),
        stop=asyncio.Event(),
    )

    def _record(c: PickCollector) -> bool:
        picks = c.picks()
        if picks is None:
            return False
        session = SessionLocal()
        try:
            record_run(session, flow.id, today_kst(), "manual", picks)
        finally:
            session.close()
        return True

    async def events():
        try:
            async for event in run_flow(body.graph, ctx):
                collector.feed(event)
                if event["type"] == "run_done":
                    event["data"]["recorded"] = await asyncio.to_thread(_record, collector) if record and not ctx.stop.is_set() else False
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Flow run error")
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    async def stream():
        try:
            async for chunk in _with_heartbeat(events()):
                yield chunk
        finally:
            ctx.stop.set()  # 클라이언트가 끊으면 남은 LLM 호출을 보내지 않는다

    return StreamingResponse(stream(), media_type="text/event-stream")
