"""답변 화면 오케스트레이터: 질문 재작성 → 레이아웃 설계 → 슬롯을 스킬로 채우며 이벤트를 흘려보낸다.

이벤트 (SSE로 그대로 나간다):
  status {stage: refining | planning}
  refined_question {question}
  layout {chat_log_id, layout}            슬롯 이벤트보다 항상 먼저
  slot {id, status, message?}             running → complete | empty | failed | stopped
  slot_delta {id, text}                   텍스트 슬롯이 흘려보내는 조각
  step_start / step / matched_examples    agent 스킬의 실행 과정 (data에 slot_id)
  answer {answer}                         마지막. 화면 전체를 텍스트로 옮긴 것 (대화 기억·관리자 검수용)

이 모듈은 특정 스킬을 모른다. 스킬이 늘어도 바뀌지 않는다.
"""
import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...models.chat import ChatSlot
from ...utils.time import utcnow
from ..ai_config import load_ai_config
from ..chat_memory import ChatMemory, ConversationContext
from . import refs
from .planner import PlannedSlot, Planner, layout_tree
from .resolver import EntityResolver
from .skills import REGISTRY
from .skills.base import Skill, SkillContext

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."
STOPPED_ANSWER = "요청하신 대로 중지했습니다."


def _event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": kind, "data": data}


def _slot_event(slot_id: str, status: str, message: Optional[str] = None) -> Dict[str, Any]:
    data = {"id": slot_id, "status": status}
    if message:
        data["message"] = message
    return _event("slot", data)


def answer_text(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]]) -> str:
    """화면을 텍스트로: 텍스트 슬롯은 본문, 데이터 슬롯은 요약."""
    parts = []
    for slot in slots:
        result = results.get(slot.id) or {}
        body = result.get("summary") or result.get("message") or ""
        if body:
            parts.append(f"### {slot.title}\n{body}" if slot.title else body)
    return "\n\n".join(parts) or FALLBACK_ANSWER


class SlotStore:
    """슬롯마다 따로 세션을 열어 저장한다 (여러 슬롯이 동시에 끝난다)."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def create(self, chat_log_id: int, slots: List[PlannedSlot]) -> None:
        db = self._session_factory()
        try:
            db.add_all(ChatSlot(chat_log_id=chat_log_id, slot_id=s.id, skill=s.skill, status="pending",
                                updated_at=utcnow()) for s in slots)
            db.commit()
        finally:
            db.close()

    def save(self, chat_log_id: int, slot_id: str, result: Dict[str, Any]) -> None:
        db = self._session_factory()
        try:
            slot = db.get(ChatSlot, (chat_log_id, slot_id))
            if slot is None:
                return
            slot.status = result["status"]
            slot.content = result.get("content")
            slot.summary = result.get("summary")
            slot.message = result.get("message")
            slot.updated_at = utcnow()
            db.commit()
        finally:
            db.close()


class AnswerService:
    def __init__(
        self, db: Session, session_factory: Callable[[], Session] = SessionLocal,
        registry: Dict[str, Skill] = REGISTRY, planner: Optional[Planner] = None,
    ):
        self.memory = ChatMemory(db)
        self._config = load_ai_config(db)
        self._session_factory = session_factory
        self._registry = registry
        self._planner = planner
        self._store = SlotStore(session_factory)

    async def stream(
        self, message: str, context: ConversationContext, chat_log_id: int, stop: asyncio.Event,
    ) -> AsyncIterator[Dict[str, Any]]:
        if not context.is_empty():  # 맥락이 없으면 재작성하지 않는다
            yield _event("status", {"stage": "refining"})
        question = await asyncio.to_thread(self.memory.refine, message, context)
        if question != message:
            yield _event("refined_question", {"question": question})
        if stop.is_set():
            yield _event("answer", {"answer": STOPPED_ANSWER})
            return

        yield _event("status", {"stage": "planning"})
        planner = self._planner or Planner(self._config, self._registry)
        rows = await planner.plan(question, context)
        slots = [s for row in rows for s in row]
        await asyncio.to_thread(self._store.create, chat_log_id, slots)
        yield _event("layout", {"chat_log_id": chat_log_id, "layout": layout_tree(rows)})

        results: Dict[str, Dict[str, Any]] = {}
        async for event in self._run_slots(slots, question, context, chat_log_id, stop, results):
            yield event
        yield _event("answer", {"answer": answer_text(slots, results)})

    async def _run_slots(
        self, slots: List[PlannedSlot], question: str, context: ConversationContext,
        chat_log_id: int, stop: asyncio.Event, results: Dict[str, Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """슬롯은 의존하는 슬롯이 끝나기를 기다렸다가 돌고, 서로 의존하지 않는 슬롯은 동시에 돈다.
        의존: '@이름.순위'로 참조한 슬롯, after_others 스킬은 after_others가 아닌 슬롯 전부.
        중지는 스킬이 ctx.stop을 보고 스스로 멈추고, 아직 시작하지 않은 슬롯은 stopped로 마감한다."""
        queue: asyncio.Queue = asyncio.Queue()
        done = object()
        resolver = EntityResolver()
        finished = {s.id: asyncio.Event() for s in slots}
        by_id = {s.id: s for s in slots}
        names = {s.name: s.id for s in slots if s.name}

        def deps_of(slot: PlannedSlot) -> List[str]:
            deps = list(slot.depends_on)
            if self._registry[slot.skill].after_others:
                deps += [s.id for s in slots if not self._registry[s.skill].after_others and s.id not in deps]
            return deps

        async def finish(slot: PlannedSlot, result: Dict[str, Any], announce: Optional[str] = None) -> None:
            results[slot.id] = result
            await asyncio.to_thread(self._store.save, chat_log_id, slot.id, result)
            await queue.put(_slot_event(slot.id, result["status"], announce))

        def blocked(slot: PlannedSlot, deps: List[str]) -> Optional[Dict[str, Any]]:
            """의존한 슬롯 결과로는 돌 수 없으면 그 슬롯에 남길 결과."""
            if stop.is_set():
                return {"status": "stopped", "message": "중지했습니다"}
            # 대상을 정하지 못해 되묻는 슬롯이 있으면 뒤 슬롯은 쓸 거리가 없다 — 사용자의 답을 기다린다
            if any(results.get(d, {}).get("clarify") for d in deps):
                return {"status": "empty", "message": "대상을 정하면 이어서 보여 드립니다"}
            for d in slot.depends_on:  # 참조한 슬롯은 결과가 있어야 한다 (after_others는 실패 문구도 해설한다)
                if results.get(d, {}).get("status") != "complete":
                    title = by_id[d].title if d in by_id else d
                    return {"status": "empty", "message": f"'{title}' 영역의 결과가 없어 채우지 못했습니다"}
            return None

        async def run_slot(slot: PlannedSlot) -> None:
            try:
                deps = deps_of(slot)
                for d in deps:
                    if d in finished:
                        await finished[d].wait()
                stopped_or_empty = blocked(slot, deps)
                if stopped_or_empty:
                    status = stopped_or_empty["status"]
                    await finish(slot, stopped_or_empty, None if status == "stopped" else stopped_or_empty["message"])
                    return

                args, ref_notes = slot.args, []
                if slot.depends_on:
                    exports = {n: results.get(i, {}).get("exports") or [] for n, i in names.items()}
                    titles = {n: by_id[i].title for n, i in names.items()}
                    dumped = slot.args.model_dump()
                    try:
                        args = type(slot.args).model_validate(refs.resolve(dumped, exports))
                        ref_notes = refs.describe(dumped, exports, titles)
                    except (refs.RefError, ValidationError) as e:
                        logger.warning("Slot %s could not use referenced results: %s", slot.id, e)
                        message = str(e) if isinstance(e, refs.RefError) else "앞 영역의 결과를 이 영역에 쓸 수 없습니다"
                        await finish(slot, {"status": "empty", "message": message}, message)
                        return

                related = [(by_id[d].title, results[d].get("summary") or results[d].get("message") or "")
                           for d in deps if d in results]
                ctx = SkillContext(
                    question=question, conversation=context, session_factory=self._session_factory,
                    resolver=resolver, ai_config=self._config, stop=stop, related=related,
                )
                await queue.put(_slot_event(slot.id, "running"))
                result: Dict[str, Any] = {"status": "failed", "message": "결과가 없습니다"}
                try:
                    async for event in self._registry[slot.skill].run(args, slot.display, ctx):
                        kind = event["type"]
                        if kind == "result":
                            result = event
                        elif kind == "delta":
                            await queue.put(_event("slot_delta", {"id": slot.id, "text": event["text"]}))
                        else:
                            await queue.put(_event(kind, {**event["data"], "slot_id": slot.id}))
                except Exception:
                    logger.exception("Slot %s (%s) failed", slot.id, slot.skill)
                    result = {"status": "failed", "message": "이 영역을 채우지 못했습니다"}
                content = result.get("content")
                if ref_notes and content and content.get("type") == "data":  # 어느 대상을 받아 그렸는지 남긴다
                    content["notes"] = [*ref_notes, *content.get("notes", [])]
                await finish(slot, result, result.get("message"))
            finally:
                finished[slot.id].set()

        async def drive() -> None:
            try:
                await asyncio.gather(*(run_slot(s) for s in slots))
            finally:
                await queue.put(done)

        driver = asyncio.create_task(drive())
        try:
            while True:
                event = await queue.get()
                if event is done:
                    break
                yield event
            await driver  # 진행 중 예외가 있었으면 여기서 드러난다
        finally:
            driver.cancel()  # 클라이언트가 끊으면 남은 슬롯도 멈춘다
