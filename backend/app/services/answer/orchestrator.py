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
from .planner import PlannedSlot, Planner, data_lookups, layout_tree
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


def _related_text(result: Dict[str, Any]) -> str:
    """뒤 슬롯(해설)에 넘기는 앞 영역의 내용: 요약과, 화면에 함께 표시되는 주석
    (관리하지 않는 ETF·데이터 기간 같은 사실은 주석에만 있어 빠뜨리면 해설이 엉뚱하게 설명한다)."""
    text = result.get("summary") or result.get("message") or ""
    notes = (result.get("content") or {}).get("notes") or []
    return "\n".join([text, *(f"(참고) {n}" for n in notes)]) if notes else text


def needs_replan(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]], stop: asyncio.Event) -> bool:
    """고칠 수 있는 실패가 있고, 중지·되묻기 중이 아니면 다시 설계한다."""
    if stop.is_set() or any(r.get("clarify") for r in results.values()):
        return False
    return any(results.get(s.id, {}).get("retryable") for s in slots)


def _rerun_ids(old: List[PlannedSlot], new: List[PlannedSlot], results: Dict[str, Dict[str, Any]]) -> set:
    """다시 실행할 슬롯: 계획이 바뀐 슬롯, 고칠 수 있다고 했던 슬롯, 그 결과를 (참조로 이어서) 받는 슬롯."""
    before = {s.id: s for s in old}
    rerun = {s.id for s in new if s.id not in before or (s.skill, s.args, s.display) != (
        before[s.id].skill, before[s.id].args, before[s.id].display) or results.get(s.id, {}).get("retryable")}
    rerun = {i for i in rerun if results.get(i, {}).get("status") != "complete" or i not in before}
    changed = True
    while changed:
        changed = False
        for s in new:
            if s.id not in rerun and set(s.depends_on) & rerun:
                rerun.add(s.id)
                changed = True
    return rerun


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

    def replace(self, chat_log_id: int, slots: List[PlannedSlot]) -> None:
        """다시 설계해 다시 실행할 슬롯: 스킬을 바꾸고 결과를 비운다."""
        db = self._session_factory()
        try:
            for s in slots:
                row = db.get(ChatSlot, (chat_log_id, s.id))
                if row is not None:
                    row.skill, row.status, row.content, row.summary, row.message = s.skill, "pending", None, None, None
                    row.updated_at = utcnow()
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
        refine: bool = True,
    ) -> AsyncIterator[Dict[str, Any]]:
        # refine=False는 사용자가 재작성을 거부하고 원문 그대로 다시 물은 경우다
        question = message
        if refine and not context.is_empty():  # 맥락이 없으면 재작성하지 않는다
            yield _event("status", {"stage": "refining"})
            question = await asyncio.to_thread(self.memory.refine, message, context)
        if question != message:
            yield _event("refined_question", {"question": question})
        if stop.is_set():
            yield _event("answer", {"answer": STOPPED_ANSWER})
            return

        yield _event("status", {"stage": "planning"})
        planner = self._planner or Planner(self._config, self._registry, **data_lookups(self._session_factory))
        rows = await planner.plan(question, context)
        slots = [s for row in rows for s in row]
        await asyncio.to_thread(self._store.create, chat_log_id, slots)
        yield _event("layout", {"chat_log_id": chat_log_id, "layout": layout_tree(rows)})

        # 데이터 슬롯 → (고칠 수 있는 실패가 있으면) 한 번 다시 설계해 그 슬롯만 다시 실행 → 해설 같은 after_others 슬롯
        results: Dict[str, Dict[str, Any]] = {}
        data = [s for s in slots if not self._registry[s.skill].after_others]
        async for event in self._run_slots(data, question, context, chat_log_id, stop, results, all_slots=slots):
            yield event

        if needs_replan(slots, results, stop) and hasattr(planner, "replan"):
            yield _event("status", {"stage": "replanning"})
            new_rows = await planner.replan(question, context, rows, results)
            if new_rows:
                rows, rerun = new_rows, _rerun_ids(slots, [s for row in new_rows for s in row], results)
                slots = [s for row in rows for s in row]
                if rerun:
                    again = [s for s in slots if s.id in rerun]
                    logger.info("Replanned slots %s", sorted(rerun))
                    await asyncio.to_thread(self._store.replace, chat_log_id, again)
                    for s in again:
                        results.pop(s.id, None)
                    yield _event("layout", {"chat_log_id": chat_log_id, "layout": layout_tree(rows)})
                    yield _event("status", {"stage": "filling"})
                    data_again = [s for s in again if not self._registry[s.skill].after_others]
                    async for event in self._run_slots(data_again, question, context, chat_log_id, stop, results,
                                                       all_slots=slots):
                        yield event

        later = [s for s in slots if self._registry[s.skill].after_others]
        async for event in self._run_slots(later, question, context, chat_log_id, stop, results, all_slots=slots):
            yield event
        yield _event("answer", {"answer": answer_text(slots, results)})

    async def _run_slots(
        self, slots: List[PlannedSlot], question: str, context: ConversationContext,
        chat_log_id: int, stop: asyncio.Event, results: Dict[str, Dict[str, Any]],
        all_slots: Optional[List[PlannedSlot]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """slots를 실행한다. 슬롯은 의존하는 슬롯이 끝나기를 기다렸다가 돌고, 서로 의존하지 않는 슬롯은 동시에 돈다.
        의존: '@이름.순위'로 참조한 슬롯, after_others 스킬은 after_others가 아닌 슬롯 전부.
        all_slots는 화면의 슬롯 전부 — 이번에 돌지 않는 슬롯의 결과는 results에 이미 있다.
        중지는 스킬이 ctx.stop을 보고 스스로 멈추고, 아직 시작하지 않은 슬롯은 stopped로 마감한다."""
        all_slots = all_slots or slots
        queue: asyncio.Queue = asyncio.Queue()
        done = object()
        resolver = EntityResolver()
        finished = {s.id: asyncio.Event() for s in slots}
        by_id = {s.id: s for s in all_slots}
        names = {s.name: s.id for s in all_slots if s.name}

        def deps_of(slot: PlannedSlot) -> List[str]:
            deps = list(slot.depends_on)
            if self._registry[slot.skill].after_others:
                deps += [s.id for s in all_slots if not self._registry[s.skill].after_others and s.id not in deps]
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
                        # 참조 범위를 고치면 나아질 수 있다 (예: 결과가 3개뿐인데 5위를 참조)
                        await finish(slot, {"status": "empty", "message": message, "retryable": True}, message)
                        return

                related = [(by_id[d].title, _related_text(results[d])) for d in deps if d in results]
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
