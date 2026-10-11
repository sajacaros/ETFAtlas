"""스킬: 답변 화면의 한 영역(슬롯)을 채우는 기능 단위.

레이아웃 에이전트는 등록된 스킬의 name/description/Args/displays만 보고 슬롯을 설계하고,
오케스트레이터는 스킬의 run()이 내는 이벤트만 다룬다. 새 기능은 스킬을 하나 만들어 registry에 올리면 된다.

run()이 내는 이벤트 (dict):
  {"type": "delta", "text"}                         텍스트를 흘려보낼 때
  {"type": "step_start" | "step" | "matched_examples", "data"}  실행 과정(디버그 패널용)
  {"type": "result", ...SkillResult}                마지막에 한 번
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, ClassVar, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ...ai_config import AIConfig
from ...chat_memory import ConversationContext
from ..resolver import EntityResolver
from ..schemas import DataContent, Dataset, Source, TextContent


@dataclass
class SkillContext:
    question: str
    conversation: ConversationContext
    session_factory: Callable[[], Session]
    resolver: EntityResolver
    ai_config: AIConfig
    stop: asyncio.Event
    # 먼저 끝난 슬롯들의 (제목, 요약) — after_others 스킬만 받는다
    related: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class SkillResult:
    status: str  # complete | empty | failed
    content: Optional[Dict[str, Any]] = None
    # 다른 슬롯(요약 텍스트)과 대화 기억에 넘기는 짧은 텍스트. 숫자는 여기서만 LLM에 전달된다
    summary: str = ""
    message: Optional[str] = None  # empty/failed일 때 그 영역에 보여줄 문구

    def event(self) -> Dict[str, Any]:
        return {"type": "result", "status": self.status, "content": self.content,
                "summary": self.summary, "message": self.message}


def empty(message: str) -> SkillResult:
    return SkillResult(status="empty", summary=message, message=message)


def data_result(
    dataset: Dataset, view: BaseModel, summary: str,
    sources: Optional[List[Source]] = None, notes: Optional[List[str]] = None,
) -> SkillResult:
    try:
        content = DataContent(dataset=dataset, view=view, sources=sources or [], notes=notes or [])
    except ValidationError as e:  # 스킬 버그 — 깨진 데이터를 보내지 않는다
        return SkillResult(status="failed", summary="", message=f"결과 형식 오류: {e.errors()[0]['msg']}")
    return SkillResult(status="complete", content=content.model_dump(), summary=summary)


def text_result(text: str, kind: str = "text") -> SkillResult:
    return SkillResult(status="complete", content=TextContent(type=kind, text=text).model_dump(), summary=text)


class Skill:
    name: ClassVar[str]
    # 레이아웃 에이전트가 읽는 설명: 언제 쓰는지, 무엇을 보여주는지
    description: ClassVar[str]
    Args: ClassVar[Type[BaseModel]]
    # 지원하는 표시 방식. 첫 번째가 기본값 (table, line, bar, donut, treemap, radar, candlestick, text, markdown)
    displays: ClassVar[Tuple[str, ...]]
    # True면 다른 슬롯이 모두 끝난 뒤, 그 요약(context.related)을 받아 실행한다
    after_others: ClassVar[bool] = False

    async def run(self, args: BaseModel, display: str, ctx: SkillContext) -> AsyncIterator[Dict[str, Any]]:
        raise NotImplementedError
        yield  # pragma: no cover


class DataSkill(Skill):
    """DB에서 결정적으로 데이터를 만드는 스킬. fetch()는 슬롯 전용 DB 세션으로 스레드에서 돈다."""

    def fetch(self, args: BaseModel, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        raise NotImplementedError

    async def run(self, args: BaseModel, display: str, ctx: SkillContext) -> AsyncIterator[Dict[str, Any]]:
        def work() -> SkillResult:
            db = ctx.session_factory()
            try:
                return self.fetch(args, display, db, ctx.resolver)
            finally:
                db.close()

        result = await asyncio.to_thread(work)
        yield result.event()
