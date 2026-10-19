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
from ..resolver import CANDIDATE_LIMIT, AmbiguousETF, EntityResolver, UnmanagedETF, UnmanagedStock, _normalize
from ..schemas import DataContent, Dataset, Source, TextContent
from ..universe import STOCK_SCOPE
from .common import format_value

CHOICES_SHOWN = 10  # 되물을 때 보여주는 후보 수


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
    # 대상을 하나로 정하지 못해 사용자에게 되묻는 결과. 오케스트레이터는 이때 해설 같은 뒤 슬롯을 돌리지 않는다
    clarify: bool = False
    # 다른 슬롯이 '@이름.순위'로 참조할 수 있는 대상 목록 [{code, name}], 순위 순. 스킬의 exports가 무엇인지 정한다
    exports: List[Dict[str, str]] = field(default_factory=list)
    # 계획을 고치면 나아질 수 있는 실패 (이름을 찾지 못함 등). 오케스트레이터가 플래너에게 한 번 다시 설계하게 한다.
    # 관리하지 않는 ETF·데이터 없음처럼 다시 설계해도 같은 결과면 False
    retryable: bool = False

    def event(self) -> Dict[str, Any]:
        return {"type": "result", "status": self.status, "content": self.content,
                "summary": self.summary, "message": self.message, "clarify": self.clarify,
                "exports": self.exports, "retryable": self.retryable}


def empty(message: str) -> SkillResult:
    return SkillResult(status="empty", summary=message, message=message)


def not_found(message: str) -> SkillResult:
    """인자로 받은 대상(이름)을 찾지 못했다 — 다른 스킬이나 인자로 다시 설계하면 나아질 수 있다."""
    return SkillResult(status="empty", summary=message, message=message, retryable=True)


def data_result(
    dataset: Dataset, view: BaseModel, summary: str,
    sources: Optional[List[Source]] = None, notes: Optional[List[str]] = None,
    exports: Optional[List[Dict[str, str]]] = None,
) -> SkillResult:
    try:
        content = DataContent(dataset=dataset, view=view, sources=sources or [], notes=notes or [])
    except ValidationError as e:  # 스킬 버그 — 깨진 데이터를 보내지 않는다
        return SkillResult(status="failed", summary="", message=f"결과 형식 오류: {e.errors()[0]['msg']}")
    return SkillResult(status="complete", content=content.model_dump(), summary=summary, exports=exports or [])


def choice_result(question: str, header: List[str], rows: List[List[str]], footer: str = "") -> SkillResult:
    """후보를 번호 붙인 표로 보여주고 되묻는다. 본문이 그대로 답변 텍스트(대화 기억)에 들어가므로
    다음 턴의 "두 번째 거" 같은 답을 질문 재작성이 풀 수 있다."""
    def cell(v: str) -> str:
        return str(v).replace("|", "\\|")

    lines = [f"**{question}**", "", "| 번호 | " + " | ".join(header) + " |", "|---:|" + "---|" * len(header)]
    lines += [f"| {i} | " + " | ".join(cell(v) for v in row) + " |" for i, row in enumerate(rows, 1)]
    lines += ["", (footer + " " if footer else "") + "번호나 이름으로 알려 주세요."]
    text = "\n".join(lines)
    return SkillResult(status="complete", content=TextContent(type="markdown", text=text).model_dump(),
                       summary=text, clarify=True)


def _is_stock_name(db: Session, resolver: EntityResolver, name: str) -> bool:
    try:
        stock = resolver.stock(db, name)
    except UnmanagedStock as e:  # 그래프 밖의 종목이어도 종목 이름이다 — 종목 스킬로 다시 설계하면 그쪽에서 안내한다
        stock = e.corp
    return bool(stock) and _normalize(stock["name"]) == _normalize(name)


def ambiguous_etf_result(e: AmbiguousETF) -> SkillResult:
    shown = e.candidates[:CHOICES_SHOWN]
    total = f"{CANDIDATE_LIMIT}개 이상" if len(e.candidates) >= CANDIDATE_LIMIT else f"{len(e.candidates)}개"
    footer = f"후보 {total} 중 순자산 상위 {len(shown)}개입니다." if len(e.candidates) > len(shown) else ""
    return choice_result(
        f"'{e.name}'에 해당하는 ETF가 여러 개입니다. 어느 ETF인가요?",
        ["ETF", "코드", "순자산"],
        [[c["name"], c["code"], format_value(c.get("net_assets"), "krw")] for c in shown],
        footer,
    )


def unmanaged_etf_result(e: UnmanagedETF) -> SkillResult:
    return empty(f"ETF Atlas에서 관리하지 않는 ETF입니다: {e.etf['name']}({e.etf['code']}). 구성종목·가격 데이터가 없습니다")


def unmanaged_stock_result(e: UnmanagedStock) -> SkillResult:
    name = f"{e.corp['name']}({e.corp['code']})" if e.corp["code"] else e.corp["name"]
    if not e.listed:
        return empty(f"{name}은(는) 상장 종목이 아니어서 분석할 수 없습니다. {STOCK_SCOPE}")
    return empty(f"{STOCK_SCOPE} {name} 종목은 지금 수집하는 ETF 어디에도 담겨 있지 않아 분석할 수 없습니다")


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
    # 결과로 내보내는 대상 목록의 설명 (예: "ETF 목록, 그 종목 비중 높은 순"). 비어 있으면 참조할 수 없는 스킬이다.
    # 내보내는 쪽은 결과의 exports에 {code, name}을 순위 순으로 담는다
    exports: ClassVar[str] = ""

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
            except AmbiguousETF as e:  # 어느 스킬이든 ETF 이름이 애매하면 고르지 않고 되묻는다
                if _is_stock_name(db, ctx.resolver, e.name):  # 종목 이름을 ETF 자리에 넣은 것 — 설계를 고칠 일이다
                    return not_found(f"'{e.name}'은(는) ETF가 아니라 개별 종목입니다")
                return ambiguous_etf_result(e)
            except UnmanagedETF as e:  # 상장 ETF지만 관리 대상이 아니면 '찾지 못했다'가 아니라 그렇다고 알린다
                return unmanaged_etf_result(e)
            except UnmanagedStock as e:  # 그래프 밖의 회사면 무엇을 분석하는지와 함께 왜 안 되는지 알린다
                return unmanaged_stock_result(e)
            finally:
                db.close()

        result = await asyncio.to_thread(work)
        yield result.event()
