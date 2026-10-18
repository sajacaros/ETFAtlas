"""자동 실행: 자동 실행을 켠 흐름을 영업일 장 마감 뒤 하루 한 번 돌려 기록하고, 켜 두었으면 바뀐 종목을 디스코드로 알린다.

- 백엔드 프로세스 안에서 CHECK_EVERY마다 깨어나고, 한국 시각 평일 START~END 사이에만 일한다.
- 오늘 일봉이 아직 없으면(휴장일·시세 지연) 다음 번에 다시 본다. END까지 없으면 그날은 건너뛴다.
- 흐름마다 last_scheduled_on을 조건부 UPDATE로 먼저 맡아 프로세스가 여럿이어도 한 번만 돈다.
  실패해도 맡은 날은 되돌리지 않는다 (같은 날 재시도로 LLM 호출을 되풀이하지 않는다).
"""
import asyncio
import logging
import os
import time
from datetime import date, datetime, time as dtime
from typing import Dict, List, Optional

import httpx
from sqlalchemy import or_, update

from ...database import SessionLocal
from ...models.analysis_flow import AnalysisFlow
from ...models.discord_setting import DiscordSetting
from ...models.user import User
from ..ai_config import load_ai_config
from .base import FlowContext
from .executor import FlowGraph, FlowGraphError, run_flow, topo_order
from .market_data import FreshMarketData, MarketData, default_market_data
from .performance import BENCHMARK
from .records import KST, PickCollector, previous_picks, record_run

logger = logging.getLogger(__name__)

CHECK_EVERY = 600  # 초
START, END = dtime(16, 10), dtime(20, 0)  # 장 마감(15:30) 뒤 일봉이 들어올 시간을 둔다
DISCORD_MAX = 1900  # 디스코드 2,000자 제한에 여유를 둔다
LIST_NAMES = 15  # 새로 들어옴·빠짐 목록에 이름을 보여 줄 최대 수


def in_window(now: datetime) -> bool:
    return now.weekday() < 5 and START <= now.time() < END


def has_bar_for(market: MarketData, day: date) -> bool:
    bars = market.bars([BENCHMARK["code"]]).get(BENCHMARK["code"], [])
    return bool(bars) and bars[-1]["date"] == day.isoformat()


def due_flow_ids(today: date) -> List[int]:
    db = SessionLocal()
    try:
        rows = db.query(AnalysisFlow.id).filter(
            AnalysisFlow.schedule_enabled.is_(True),
            or_(AnalysisFlow.last_scheduled_on.is_(None), AnalysisFlow.last_scheduled_on < today),
        ).order_by(AnalysisFlow.id).all()
        return [r[0] for r in rows]
    finally:
        db.close()


def claim(flow_id: int, today: date) -> bool:
    db = SessionLocal()
    try:
        claimed = db.execute(
            update(AnalysisFlow)
            .where(
                AnalysisFlow.id == flow_id,
                AnalysisFlow.schedule_enabled.is_(True),
                or_(AnalysisFlow.last_scheduled_on.is_(None), AnalysisFlow.last_scheduled_on < today),
            )
            .values(last_scheduled_on=today)
            .returning(AnalysisFlow.id)
        ).first()
        db.commit()
        return claimed is not None
    finally:
        db.close()


def _names(picks: List[Dict[str, str]]) -> str:
    shown = ", ".join(p["name"] for p in picks[:LIST_NAMES])
    return shown + (f" 외 {len(picks) - LIST_NAMES}" if len(picks) > LIST_NAMES else "")


def change_message(name: str, owner: str, day: date, picks: List[Dict[str, str]],
                   previous: Optional[List[Dict[str, str]]]) -> Optional[str]:
    """바뀐 것이 없으면 None (알리지 않는다)."""
    header = f"🧭 **스크리너: {name}** ({day.isoformat()}, {owner}) — {len(picks)}종목"
    if previous is None:
        lines = [header + " · 첫 기록"]
        if picks:
            lines.append(f"종목: {_names(picks)}")
    else:
        before = {p["code"] for p in previous}
        now = {p["code"] for p in picks}
        added = [p for p in picks if p["code"] not in before]
        removed = [p for p in previous if p["code"] not in now]
        if not added and not removed:
            return None
        lines = [header]
        if added:
            lines.append(f"🆕 새로 들어옴 ({len(added)}): {_names(added)}")
        if removed:
            lines.append(f"👋 빠짐 ({len(removed)}): {_names(removed)}")
        lines.append(f"유지 {len(now & before)}종목")
    text = "\n".join(lines)
    return text if len(text) <= DISCORD_MAX else text[: DISCORD_MAX - 1] + "…"


def webhook_url() -> Optional[str]:
    """비중 변화 알림과 같은 웹훅을 쓴다. 관리자가 디스코드 알림을 꺼 두었으면 보내지 않는다."""
    db = SessionLocal()
    try:
        setting = db.get(DiscordSetting, 1)
        if setting is not None:
            return setting.webhook_url if setting.enabled else None
        return os.environ.get("DISCORD_WEBHOOK_URL") or None
    finally:
        db.close()


async def send_discord(content: str) -> None:
    url = webhook_url()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"content": content})
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.json().get("retry_after", 1)))
                resp = await client.post(url, json={"content": content})
            resp.raise_for_status()
    except httpx.HTTPError as e:
        # 예외 메시지에 웹훅 주소(토큰 포함)가 들어가므로 종류만 남긴다
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        logger.warning("Flow Discord notification failed: %s status=%s", type(e).__name__, status)


async def run_scheduled(flow_id: int, today: date, market: MarketData) -> None:
    db = SessionLocal()
    try:
        flow = db.get(AnalysisFlow, flow_id)
        if flow is None:
            return
        owner = db.get(User, flow.user_id)
        name, notify, user_id = flow.name, flow.notify, flow.user_id
        owner_name = (owner.name or owner.username) if owner else "?"
        graph = FlowGraph.model_validate(flow.graph)
        ai_config = load_ai_config(db)
    finally:
        db.close()

    try:
        topo_order(graph)
    except FlowGraphError as e:
        logger.warning("Scheduled flow %s has a bad graph: %s", flow_id, e)
        if notify:
            await send_discord(f"⚠️ **스크리너: {name}** ({today.isoformat()}, {owner_name}) 자동 실행 실패: {e}")
        return

    ctx = FlowContext(user_id=user_id, session_factory=SessionLocal, ai_config=ai_config, market=market, stop=asyncio.Event())
    collector = PickCollector(graph)
    errors: List[str] = []
    async for event in run_flow(graph, ctx):
        collector.feed(event)
        if event["type"] == "node_error":
            errors.append(event["data"]["message"])
    picks = collector.picks()
    if picks is None:
        reason = errors[0] if errors else "결과 노드가 없거나 끝나지 않았습니다"
        logger.warning("Scheduled flow %s produced no picks: %s", flow_id, reason)
        if notify:
            await send_discord(f"⚠️ **스크리너: {name}** ({today.isoformat()}, {owner_name}) 자동 실행 실패: {reason}")
        return

    db = SessionLocal()
    try:
        previous = previous_picks(db, flow_id, today)
        record_run(db, flow_id, today, "schedule", picks)
    finally:
        db.close()
    logger.info("Scheduled flow %s recorded %d picks", flow_id, len(picks))
    if notify:
        message = change_message(name, owner_name, today, picks, previous)
        if message:
            await send_discord(message)


async def tick(now: datetime) -> None:
    if not in_window(now):
        return
    today = now.date()
    ids = await asyncio.to_thread(due_flow_ids, today)
    if not ids:
        return
    # 장중에 받아 둔 일봉(미완성)을 쓰지 않도록 이번 차례 시작 뒤에 받은 시세만 쓴다
    market = FreshMarketData(default_market_data(), since=time.time())
    if not await asyncio.to_thread(has_bar_for, market, today):
        logger.info("No %s bar for %s yet — waiting", BENCHMARK["name"], today)
        return
    for flow_id in ids:
        if not await asyncio.to_thread(claim, flow_id, today):
            continue
        try:
            await run_scheduled(flow_id, today, market)
        except Exception:
            logger.exception("Scheduled flow %s failed", flow_id)


async def loop() -> None:
    while True:
        try:
            await tick(datetime.now(KST).replace(tzinfo=None))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Flow scheduler tick failed")
        await asyncio.sleep(CHECK_EVERY)
