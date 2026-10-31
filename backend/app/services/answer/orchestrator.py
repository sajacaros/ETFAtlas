"""답변 화면 오케스트레이터: 질문 재작성 → 레이아웃 설계 → 슬롯을 스킬로 채우며 이벤트를 흘려보낸다.

이벤트 (SSE로 그대로 나간다):
  status {stage: refining | planning | replanning | filling}
  refined_question {question}
  layout {chat_log_id, layout}            슬롯 이벤트보다 항상 먼저. 다시 설계하거나 스킬이 영역 제목을 바꾸거나
                                          영역을 나누면 다시 온다 (나눈 영역은 '원래 id-1', '원래 id-2' …)
  slot {id, status, message?}             running → complete | empty | failed | stopped
  slot_delta {id, text}                   텍스트 슬롯이 흘려보내는 조각
  step_start / step / matched_examples    agent 스킬의 실행 과정 (data에 slot_id)
  answer {answer, result}                 마지막. 화면 전체를 텍스트로 옮긴 것 (대화 기억·관리자 검수용)과
                                          답변을 어떻게 마쳤는지 (completed | cancelled | failed | clarifying)

스킬이 내는 이벤트(skills/base.py의 SkillEvent)는 SlotRunner가 위 이벤트로 바꾼다.
이 모듈은 특정 스킬을 모른다. 스킬이 늘어도 바뀌지 않는다.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...models.chat import ChatLogResult, ChatSlot
from ...utils.time import utcnow
from ..ai_config import AIConfig
from ..chat_memory import ChatMemory, ConversationContext
from ..chat_service import FALLBACK_ANSWER
from ..entities import EntityResolver
from . import refs
from .planner import PlannedSlot, Planner, data_lookups, layout_tree
from .skills import REGISTRY
from .skills.base import PROCESS_EVENTS, ResultEvent, Skill, SkillContext, SplitEvent, related_text

logger = logging.getLogger(__name__)

# 한 답변 안에서 LLM을 부르는 슬롯(보고서 읽기·해설·agent 등)이 동시에 도는 최대 수. 나머지는 자리가 나면 돈다
MAX_LLM_SLOTS = 3
STOPPED_ANSWER = "요청하신 대로 중지했습니다."
STOPPED = {"status": "stopped", "message": "중지했습니다"}
UNFILLED = "이 영역을 채우지 못했습니다"

Rows = List[List[PlannedSlot]]


@runtime_checkable
class LayoutPlanner(Protocol):
    async def plan(self, question: str, context: ConversationContext) -> Rows: ...


@runtime_checkable
class Replanner(Protocol):
    """실행 결과를 보고 고칠 수 있는 슬롯만 다시 설계한다. 배치는 그대로라 슬롯 id가 유지된다. 실패하면 None."""

    async def replan(self, question: str, context: ConversationContext, rows: Rows,
                     results: Dict[str, Dict[str, Any]]) -> Optional[Rows]: ...


async def _gated(events: AsyncIterator[Dict[str, Any]], gate: Optional[asyncio.Semaphore]) -> AsyncIterator[Dict[str, Any]]:
    """LLM을 쓰는 스킬은 자리가 날 때까지 기다렸다가 돈다 (자리를 잡은 채 이벤트를 흘려보낸다)."""
    if gate is None:
        async for event in events:
            yield event
        return
    async with gate:
        async for event in events:
            yield event


def _event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": kind, "data": data}


def _slot_event(slot_id: str, status: str, message: Optional[str] = None) -> Dict[str, Any]:
    data = {"id": slot_id, "status": status}
    if message:
        data["message"] = message
    return _event("slot", data)


def shared_notice(results: List[Dict[str, Any]]) -> Optional[str]:
    """모든 결과가 같은 문구로 비었으면 그 문구. 하나라도 결과가 있거나 문구가 다르면 None."""
    messages = {r.get("message") for r in results}
    if not results or any(r.get("status") != "empty" for r in results) or len(messages) != 1:
        return None
    return messages.pop()


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
    return refs.with_dependents(new, rerun)


def shown_slots(slots: List[PlannedSlot], splits: Dict[str, List[PlannedSlot]]) -> List[PlannedSlot]:
    """화면에 보이는 영역: 스킬이 나눈 슬롯은 나눈 영역들로."""
    return [part for s in slots for part in splits.get(s.id, [s])]


def split_result(parts: List[PlannedSlot], results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """나눈 슬롯의 원래 id에 남기는 결과: 다시 설계·되묻기·해설 대기 같은 슬롯 단위 판단이 그대로 쓴다."""
    states = [results.get(p.id, {}) for p in parts]
    complete = [r for r in states if r.get("status") == "complete"]
    if not complete:
        return states[0] if states else {"status": "failed", "message": "결과가 없습니다"}
    summary = "\n\n".join(f"{p.title}: {r.get('summary') or r.get('message') or ''}" for p, r in zip(parts, states))
    return {"status": "complete", "summary": summary}


def answer_text(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]],
                splits: Optional[Dict[str, List[PlannedSlot]]] = None) -> str:
    """화면을 텍스트로: 텍스트 슬롯은 본문, 데이터 슬롯은 요약."""
    parts = []
    for slot in shown_slots(slots, splits or {}):
        result = results.get(slot.id) or {}
        body = result.get("summary") or result.get("message") or ""
        if body:
            parts.append(f"### {slot.title}\n{body}" if slot.title else body)
    return "\n\n".join(parts) or FALLBACK_ANSWER


def answer_result(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]], stop: asyncio.Event) -> str:
    """답변 전체의 결과. 일부 영역만 비거나 실패했으면 완료로 본다 (영역별 상태는 chat_slots에 있다)."""
    if stop.is_set():
        return ChatLogResult.CANCELLED.value
    if any(r.get("clarify") for r in results.values()):
        return ChatLogResult.CLARIFYING.value
    if all((results.get(s.id) or {}).get("status") == "failed" for s in slots):
        return ChatLogResult.FAILED.value
    return ChatLogResult.COMPLETED.value


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

    def split(self, chat_log_id: int, slot_id: str, parts: List[PlannedSlot]) -> None:
        """스킬이 영역을 나눴다: 나눈 영역의 행을 만든다. 원래 슬롯의 행에는 나눈 영역들을 합친 결과가 남는다."""
        db = self._session_factory()
        try:
            for s in parts:
                db.merge(ChatSlot(chat_log_id=chat_log_id, slot_id=s.id, skill=s.skill, status="pending",
                                  updated_at=utcnow()))
            db.commit()
        finally:
            db.close()

    def replace(self, chat_log_id: int, slots: List[PlannedSlot]) -> None:
        """다시 설계해 다시 실행할 슬롯: 스킬을 바꾸고 결과를 비운다. 나눴던 영역은 지운다."""
        db = self._session_factory()
        try:
            for s in slots:
                db.query(ChatSlot).filter(ChatSlot.chat_log_id == chat_log_id,
                                          ChatSlot.slot_id.like(f"{s.id}-%")).delete(synchronize_session=False)
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


@dataclass
class AnswerRun:
    """답변 하나의 상태. 다시 설계하면 rows가 바뀌고, results·splits는 슬롯 묶음을 여러 번 돌려도 이어진다."""
    question: str
    context: ConversationContext
    chat_log_id: int
    stop: asyncio.Event
    rows: Rows
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    splits: Dict[str, List[PlannedSlot]] = field(default_factory=dict)  # 스킬이 나눈 슬롯 id → 나눈 영역. 계획은 그대로 둔다

    @property
    def slots(self) -> List[PlannedSlot]:
        return [s for row in self.rows for s in row]

    def layout(self) -> Dict[str, Any]:
        return _event("layout", {"chat_log_id": self.chat_log_id, "layout": layout_tree(self.rows, self.splits)})

    def relayout(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """스킬이 실행하며 제목을 정하거나(보고서 이름 등) 영역을 나누면 레이아웃을 다시 보낸다. 마지막 레이아웃이 저장된다."""
        return self.layout() if event["type"] in ("slot_title", "slot_split") else event


class SlotRunner:
    """슬롯 묶음을 실행한다. 슬롯은 의존하는 슬롯이 끝나기를 기다렸다가 돌고, 서로 의존하지 않는 슬롯은 동시에 돈다.
    의존: '@이름.순위'로 참조한 슬롯, after_others 스킬은 after_others가 아닌 슬롯 전부.
    이번에 돌지 않는 슬롯(화면의 다른 슬롯)의 결과는 answer.results에 이미 있다.
    중지는 스킬이 ctx.stop을 보고 스스로 멈추고, 아직 시작하지 않은 슬롯은 stopped로 마감한다.
    스킬이 split 이벤트로 영역을 나누면 answer.splits에 남기고, 그 뒤의 delta·result는 part로 나눈 영역을 가리킨다."""

    def __init__(self, answer: AnswerRun, registry: Dict[str, Skill], store: "SlotStore",
                 session_factory: Callable[[], Session], config: Optional[AIConfig]):
        self.answer = answer
        self.registry = registry
        self.store = store
        self.session_factory = session_factory
        self.config = config
        self.resolver = EntityResolver()
        self.llm_slots = asyncio.Semaphore(MAX_LLM_SLOTS)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.finished: Dict[str, asyncio.Event] = {}
        self.by_id = {s.id: s for s in answer.slots}
        self.names = {s.name: s.id for s in answer.slots if s.name}

    async def run(self, slots: List[PlannedSlot]) -> AsyncIterator[Dict[str, Any]]:
        self.finished = {s.id: asyncio.Event() for s in slots}
        done = object()

        async def drive() -> None:
            try:
                await asyncio.gather(*(self._run_slot(s) for s in slots))
            finally:
                await self.queue.put(done)

        driver = asyncio.create_task(drive())
        try:
            while True:
                event = await self.queue.get()
                if event is done:
                    break
                yield event
            await driver  # 진행 중 예외가 있었으면 여기서 드러난다
        finally:
            driver.cancel()  # 클라이언트가 끊으면 남은 슬롯도 멈춘다

    # --- 슬롯 하나 ---

    async def _run_slot(self, slot: PlannedSlot) -> None:
        try:
            deps = self._deps_of(slot)
            for d in deps:
                if d in self.finished:
                    await self.finished[d].wait()
            blocked = self._blocked(slot, deps)
            if blocked:
                await self._finish(slot, blocked, None if blocked["status"] == "stopped" else blocked["message"])
                return
            args, ref_notes, unusable = self._resolve_refs(slot)
            if unusable:
                await self._finish(slot, unusable, unusable["message"])
                return
            await self.queue.put(_slot_event(slot.id, "running"))
            result, parts = await self._execute(slot, args, self._context(deps))
            if parts:
                for sub in parts.values():  # 결과를 내지 못하고 끝난 영역
                    if sub.id not in self.answer.results:
                        await self._finish(sub, dict(STOPPED) if self.answer.stop.is_set()
                                           else {"status": "failed", "message": UNFILLED})
                await self._finish(slot, split_result(list(parts.values()), self.answer.results), shown=False)
                return
            content = result.get("content")
            if ref_notes and content and content.get("type") == "data":  # 어느 대상을 받아 그렸는지 남긴다
                content["notes"] = [*ref_notes, *content.get("notes", [])]
            await self._finish(slot, result, result.get("message"))
        finally:
            self.finished[slot.id].set()

    def _deps_of(self, slot: PlannedSlot) -> List[str]:
        deps = list(slot.depends_on)
        if self.registry[slot.skill].after_others:
            deps += [s.id for s in self.answer.slots if not self.registry[s.skill].after_others and s.id not in deps]
        return deps

    def _blocked(self, slot: PlannedSlot, deps: List[str]) -> Optional[Dict[str, Any]]:
        """의존한 슬롯 결과로는 돌 수 없으면 그 슬롯에 남길 결과."""
        results = self.answer.results
        if self.answer.stop.is_set():
            return dict(STOPPED)
        # 대상을 정하지 못해 되묻는 슬롯이 있으면 뒤 슬롯은 쓸 거리가 없다 — 사용자의 답을 기다린다
        if any(results.get(d, {}).get("clarify") for d in deps):
            return {"status": "empty", "message": "대상을 정하면 이어서 보여 드립니다"}
        if self.registry[slot.skill].after_others:
            notice = shared_notice([results.get(d, {}) for d in deps])
            if notice:  # 모든 영역이 같은 안내(분석하지 않는 종목 등)로 비었으면 해설도 그 안내만 — LLM이 되풀이할 것이 없다
                return {"status": "empty", "message": notice}
        for d in slot.depends_on:  # 참조한 슬롯은 결과가 있어야 한다 (after_others는 결과와 실패 문구가 섞여 있으면 함께 해설한다)
            if results.get(d, {}).get("status") != "complete":
                title = self.by_id[d].title if d in self.by_id else d
                return {"status": "empty", "message": f"'{title}' 영역의 결과가 없어 채우지 못했습니다"}
        return None

    def _resolve_refs(self, slot: PlannedSlot) -> Tuple[BaseModel, List[str], Optional[Dict[str, Any]]]:
        """(참조를 대상 코드로 바꾼 인자, 화면에 남길 참조 풀이, 쓸 수 없으면 그 슬롯에 남길 결과)."""
        if not slot.depends_on:
            return slot.args, [], None
        exports = {n: self.answer.results.get(i, {}).get("exports") or [] for n, i in self.names.items()}
        titles = {n: self.by_id[i].title for n, i in self.names.items()}
        dumped = slot.args.model_dump()
        try:
            # 계획의 인자 모델은 목록 최소 개수를 낮춘 것이라 원래 Args로 검사한다
            args = self.registry[slot.skill].Args.model_validate(refs.resolve(dumped, exports))
            return args, refs.describe(dumped, exports, titles), None
        except (refs.RefError, ValidationError) as e:
            logger.warning("Slot %s could not use referenced results: %s", slot.id, e)
            message = str(e) if isinstance(e, refs.RefError) else "앞 영역의 결과를 이 영역에 쓸 수 없습니다"
            # 참조 범위를 고치면 나아질 수 있다 (예: 결과가 3개뿐인데 5위를 참조). 범위가 통째로 결과 밖이면 아니다
            return slot.args, [], {"status": "empty", "message": message, "retryable": not isinstance(e, refs.RefPastEnd)}

    def _context(self, deps: List[str]) -> SkillContext:
        a = self.answer
        related = [(s.title, related_text(a.results[s.id]))
                   for s in shown_slots([self.by_id[d] for d in deps if d in self.by_id], a.splits) if s.id in a.results]
        return SkillContext(
            question=a.question, conversation=a.context, session_factory=self.session_factory,
            resolver=self.resolver, ai_config=self.config, stop=a.stop, related=related, registry=self.registry,
        )

    async def _execute(self, slot: PlannedSlot, args: BaseModel,
                       ctx: SkillContext) -> Tuple[Dict[str, Any], Dict[str, PlannedSlot]]:
        """스킬을 돌려 스킬 이벤트를 화면 이벤트로 바꾼다. (나누지 않았을 때의 결과, 나눈 영역: part id → 하위 슬롯)."""
        skill = self.registry[slot.skill]
        result: Dict[str, Any] = {"status": "failed", "message": "결과가 없습니다"}
        parts: Dict[str, PlannedSlot] = {}
        try:
            async for event in _gated(skill.run(args, slot.display, ctx), self.llm_slots if skill.uses_llm else None):
                kind = event["type"]
                part = parts.get(event.get("part", ""))
                if kind == "split":
                    parts = await self._split(slot, event)
                elif kind == "result" and part:
                    await self._finish(part, event, event.get("message"))
                elif kind == "result":
                    result = event
                elif kind == "delta":
                    await self.queue.put(_event("slot_delta", {"id": (part or slot).id, "text": event["text"]}))
                elif kind == "title":
                    slot.title = event["title"]
                    await self.queue.put(_event("slot_title", {"id": slot.id, "title": slot.title}))
                elif kind in PROCESS_EVENTS:
                    await self.queue.put(_event(kind, {**event["data"], "slot_id": slot.id}))
        except Exception:
            logger.exception("Slot %s (%s) failed", slot.id, slot.skill)
            result = {"status": "failed", "message": UNFILLED}
        return result, parts

    async def _split(self, slot: PlannedSlot, event: SplitEvent) -> Dict[str, PlannedSlot]:
        subs = [PlannedSlot(id=f"{slot.id}-{n}", skill=slot.skill, title=p["title"], display=p["display"], args=slot.args)
                for n, p in enumerate(event["parts"], 1)]
        self.answer.splits[slot.id] = subs
        await asyncio.to_thread(self.store.split, self.answer.chat_log_id, slot.id, subs)
        await self.queue.put(_event("slot_split", {"id": slot.id}))
        for sub in subs:
            await self.queue.put(_slot_event(sub.id, "running"))
        return {p["id"]: sub for p, sub in zip(event["parts"], subs)}

    async def _finish(self, slot: PlannedSlot, result: Dict[str, Any] | ResultEvent, announce: Optional[str] = None,
                      shown: bool = True) -> None:
        self.answer.results[slot.id] = result
        await asyncio.to_thread(self.store.save, self.answer.chat_log_id, slot.id, result)
        if shown:  # 나눈 슬롯의 원래 영역은 화면에 없다
            await self.queue.put(_slot_event(slot.id, result["status"], announce))


class AnswerService:
    def __init__(
        self, config: Optional[AIConfig], session_factory: Callable[[], Session] = SessionLocal,
        registry: Dict[str, Skill] = REGISTRY, planner: Optional[LayoutPlanner] = None,
        memory: Optional[ChatMemory] = None,
    ):
        """config는 요청마다 읽은 접속 설정. memory는 질문 재작성(refine)에만 쓰므로 DB 세션이 없어도 된다."""
        self._config = config
        self.memory = memory or ChatMemory(None, config)
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
            yield _event("answer", {"answer": STOPPED_ANSWER, "result": ChatLogResult.CANCELLED.value})
            return

        yield _event("status", {"stage": "planning"})
        planner = self._planner or Planner(
            self._config, self._registry, **data_lookups(self._session_factory, self._config))
        answer = AnswerRun(question, context, chat_log_id, stop, await planner.plan(question, context))
        await asyncio.to_thread(self._store.create, chat_log_id, answer.slots)
        yield answer.layout()

        # 데이터 슬롯 → (고칠 수 있는 실패가 있으면) 한 번 다시 설계해 그 슬롯만 다시 실행 → 해설 같은 after_others 슬롯
        async for event in self._fill(answer, self._data_slots(answer.slots)):
            yield event
        if needs_replan(answer.slots, answer.results, stop) and isinstance(planner, Replanner):
            async for event in self._replan(answer, planner):
                yield event
        async for event in self._fill(answer, [s for s in answer.slots if self._registry[s.skill].after_others]):
            yield event
        yield _event("answer", {"answer": answer_text(answer.slots, answer.results, answer.splits),
                                "result": answer_result(answer.slots, answer.results, stop)})

    def _data_slots(self, slots: List[PlannedSlot]) -> List[PlannedSlot]:
        return [s for s in slots if not self._registry[s.skill].after_others]

    async def _fill(self, answer: AnswerRun, slots: List[PlannedSlot]) -> AsyncIterator[Dict[str, Any]]:
        runner = SlotRunner(answer, self._registry, self._store, self._session_factory, self._config)
        async for event in runner.run(slots):
            yield answer.relayout(event)

    async def _replan(self, answer: AnswerRun, planner: Replanner) -> AsyncIterator[Dict[str, Any]]:
        """고칠 수 있는 실패를 보고 한 번 다시 설계해, 바뀐 슬롯과 그 결과를 받는 슬롯만 다시 실행한다."""
        yield _event("status", {"stage": "replanning"})
        new_rows = await planner.replan(answer.question, answer.context, answer.rows, answer.results)
        if not new_rows:
            return
        old = answer.slots
        rerun = _rerun_ids(old, [s for row in new_rows for s in row], answer.results)
        shown = {s.id: s.title for s in old}
        answer.rows = new_rows
        for s in answer.slots:  # 다시 돌지 않는 슬롯은 화면의 제목(스킬이 정한 제목 포함)을 그대로 둔다
            if s.id not in rerun and s.id in shown:
                s.title = shown[s.id]
        if not rerun:
            return
        again = [s for s in answer.slots if s.id in rerun]
        logger.info("Replanned slots %s", sorted(rerun))
        await asyncio.to_thread(self._store.replace, answer.chat_log_id, again)
        for s in again:
            answer.results.pop(s.id, None)
            for part in answer.splits.pop(s.id, []):
                answer.results.pop(part.id, None)
        yield answer.layout()
        yield _event("status", {"stage": "filling"})
        async for event in self._fill(answer, self._data_slots(again)):
            yield event
