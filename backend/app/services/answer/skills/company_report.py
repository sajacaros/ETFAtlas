"""company_report: 정기보고서를 목차 트리(report_nodes)에서 골라 읽는다 — PageIndex 방식.

보고서는 dart_report_index DAG가 미리 색인한다 (원문 → 목차 트리 → 등록된 LLM의 노드 요약, app.services.report_tree).
  - need가 있으면: 목차(제목 + 노드 요약)를 보고 LLM이 노드를 고르고, 고른 노드의 본문(표는 병합 셀을 푼 마크다운)을
    읽어 답한다. 답 머리에 읽은 절을 밝힌다.
  - need가 없으면: 사업의 내용·경영진단·투자자 보호 사항·부문 주석을 요약한 개요. 보고서 표에 매출 구성이 있으면
    차트 영역을 먼저 나눈다. 개요와 매출 구성은 보고서마다 한 번 만들어 stock_reports에 남긴다.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy.orm import defer

from ....models.dart import ReportNode, StockReport
from ...content import Source
from ...entities import UnmanagedStock
from ...llm import NO_THINKING, build_model
from ...report_tree import SUMMARY_MIN_CHARS, Block, clip, filed_date, render
from . import report_breakdowns
from .base import Skill, SkillContext, SkillResult, empty, not_found, text_result, unmanaged_stock_result
from .company_disclosures import DART_VIEWER

logger = logging.getLogger(__name__)

READY = ("tree", "summarized")  # 트리만 있어도 제목으로 고를 수 있다
PICK_MAX = 3
READ_NODE_CHARS = 12000
READ_CHARS = 30000
OVERVIEW_CHAPTERS = ("II.", "IV.", "XI.")
OVERVIEW_CHARS = 48000
OVERVIEW_NODE_CHARS = (1500, 5000)  # 노드 하나에 줄 몫 (최소, 최대) — 장이 많아도 뒤쪽 장이 잘려 나가지 않게
SEGMENT_NOTE = "부문"  # '영업부문 (연결)', '부문별 보고 (연결)' — 회사마다 주석 이름이 다르다
MIX_SECTIONS = ("매출", "주요 제품")  # 매출 구성 표가 있는 절 (부문 주석과 함께)
MIX_CHARS = 16000
_WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_PARTICLE = re.compile(r"(와|과|의|및|은|는|이|가|을|를|에|로|으로|이랑|랑)$")

NAV_PROMPT = """당신은 DART 정기보고서의 목차를 보고 '찾을 것'의 답이 있는 절을 고릅니다.
목차의 각 줄은 '[id] 제목 (글자 수) — 이 절에 든 항목(있으면)'이고 들여쓰기가 계층입니다.
- 답이 있을 가능성이 높은 순서로 id를 1~3개 고르세요. 가능하면 가장 깊은(구체적인) 절을 고르세요.
- 목차에 있는 id만 쓰세요.
- keywords: 큰 표(임원 명단 등)에서 골라 읽을 행의 낱말이 있으면 적으세요 (사람 이름, 항목 이름). 없으면 비웁니다."""

LOOKUP_PROMPT = """당신은 DART 정기보고서에서 찾아 읽은 절로 질문에 답합니다.
- '읽은 절'에 있는 사실만 쓰세요. 답이 없으면 이 절들에서는 찾지 못했다고 쓰세요. 추측하지 마세요.
- 수치는 본문에 적힌 숫자와 단위를 그대로 옮기세요 (예: '27,362,722백만원'). 단위를 조·억원으로 바꾸지 마세요 — 자릿수를 틀리기 쉽습니다.
  본문 문장에 이미 '27조 3,627억원'처럼 적힌 값은 그대로 씁니다.
- 표에서 읽은 값은 어느 기간(열)의 값인지 밝히세요. 표 머리말의 'A / B'는 위 단계 / 아래 단계 머리말입니다.
- 매수·매도 권유나 투자 의견은 쓰지 마세요.
- 제목이나 머리말 없이 짧은 글머리표 2~6개로 답하세요."""

OVERVIEW_PROMPT = """당신은 DART 정기보고서 본문을 요약합니다. 아래 '보고서 본문'은 보고서에서 사업의 내용, 경영진단, 투자자 보호 사항, 부문 주석만 뽑은 것입니다.
- 본문에 있는 사실만 쓰세요. 본문에 없는 수치·전망·평가를 만들지 마세요.
- 수치는 본문에 적힌 숫자와 단위를 그대로 옮기세요 (예: '1,234,567백만원'). 단위를 조·억원으로 바꾸지 마세요 — 자릿수를 틀리기 쉽습니다. 본문 문장에 이미 '12조 3,456억원'처럼 적힌 값은 그대로 씁니다.
- 매수·매도 권유나 투자 의견은 쓰지 마세요.
- 제목(#, ##)이나 머리말 없이 바로 아래 형식으로 시작하세요. 항목마다 2~4개의 짧은 글머리표. 본문에 내용이 없는 항목은 통째로 빼세요.

#### 사업 구조
(무엇을 팔아 돈을 버는지, 주력 제품·부문. 매출 구성은 따로 차트로 보여 주므로 표의 금액을 모두 옮기지 말고 비중이 큰 것만)
#### 이번 기간 영업 상황
(가격·출하·수주·가동률 등 본문이 설명하는 실적 배경, 경영진 설명이 있으면 그 요지)
#### 위험 요인
(본문이 밝힌 시장·환율·금리·원재료 등 위험과 대응)
#### 소송·제재·기준일 이후 주요사항
(우발부채, 제재, 작성기준일 이후 발생한 주요사항, 진행 중인 공시사항)"""

FOOTER = "\n\n_보고서 본문을 AI가 읽고 정리했습니다. 정확한 내용은 원문을 확인하세요._"


class CompanyReportArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")
    need: Optional[str] = Field(
        default=None,
        description="보고서에서 찾을 것 한 줄 (예: '연구개발비용과 매출액 대비 비율', '직원 수와 1인 평균 급여액', "
                    "'최대주주와 지분율'). 사업 전반 요약(기업 분석·무슨 사업)이면 비운다")
    period: Optional[str] = Field(
        default=None,
        description="보고서 기간 'YYYY.MM' (예: '2025.12'는 2025년 사업보고서, '2026.06'은 반기보고서). 없으면 가장 최근")


@dataclass
class Report:
    rcept_no: str
    report_nm: str
    breakdowns: Optional[str]
    overview: Optional[str]

    @property
    def filed(self) -> str:
        return filed_date(self.rcept_no).isoformat()


@dataclass
class Entry:
    """목차의 한 줄 (본문 없이)."""
    node_id: str
    parent_id: Optional[str]
    level: int
    title: str
    path: str
    chars: int
    summary: Optional[str]


def pick_report(rows: Sequence[StockReport], period: Optional[str]) -> Optional[StockReport]:
    """색인을 마친 보고서 중 가장 최근 기간, 같은 기간이면 가장 최근 접수(정정본). period가 있으면 그 기간의 보고서.
    접수번호만 보면 옛 기간을 뒤늦게 정정한 보고서(6월에 낸 사업보고서 정정)가 새 분기보고서보다 앞선다."""
    ready = [r for r in rows if r.status in READY and (not period or r.period == period)]
    return max(ready, key=lambda r: (r.period or "", r.rcept_no), default=None)


def prepare_report(stock_arg: str, ctx: SkillContext, period: Optional[str] = None):
    """(종목, 보고서, 목차) 또는 결과(SkillResult)."""
    db = ctx.session_factory()
    try:
        try:
            stock = ctx.resolver.stock(db, stock_arg)
        except UnmanagedStock as e:  # 그래프 밖의 회사면 무엇을 분석하는지와 함께 왜 안 되는지 알린다
            return unmanaged_stock_result(e)
        if stock is None:
            return not_found(f"종목을 찾지 못했습니다: {stock_arg}")
        name = stock["name"]
        rows = [r for r in db.query(StockReport).filter(StockReport.stock_code == stock["code"]).all()
                if r.stock_code == stock["code"]]
        row = pick_report(rows, period)
        if row is None:
            same = [r for r in rows if r.period == period] if period else rows
            if same and all(r.status == "missing" for r in same):
                return empty(f"{name}의 {period + ' 기간 ' if period else ''}정기보고서는 DART가 원문을 주지 않아 "
                             "색인하지 못했습니다 (정정 공시에서 생깁니다)")
            if period and same:
                return empty(f"{name}의 {period} 기간 정기보고서는 아직 색인하지 못했습니다 (매일 저녁 색인합니다)")
            if period and pick_report(rows, None):
                return empty(f"{name}의 {period} 기간 정기보고서는 색인돼 있지 않습니다 (최근 1년 보고서만 둡니다)")
            if rows:
                return empty(f"{name}의 정기보고서를 아직 색인하지 못했습니다 (매일 저녁 색인합니다)")
            return empty(f"{name}의 정기보고서를 찾지 못했습니다 (DART 수집 전이거나 정기보고서를 내지 않는 종목)")
        report = Report(row.rcept_no, row.report_nm, row.breakdowns, row.overview)
        nodes = (db.query(ReportNode).options(defer(ReportNode.blocks))
                 .filter(ReportNode.rcept_no == report.rcept_no).order_by(ReportNode.seq).all())
        entries = [Entry(n.node_id, n.parent_id, n.level, n.title, n.path, n.chars, n.summary)
                   for n in sorted(nodes, key=lambda n: n.seq) if n.rcept_no == report.rcept_no]
    finally:
        db.close()
    if not entries:
        return empty(f"{name}의 {report.report_nm} 목차가 비어 있습니다")
    return stock, report, entries


def load_blocks(ctx: SkillContext, rcept_no: str, node_ids: Sequence[str]) -> Dict[str, List[Block]]:
    db = ctx.session_factory()
    try:
        rows = db.query(ReportNode).filter(ReportNode.rcept_no == rcept_no, ReportNode.node_id.in_(list(node_ids))).all()
        return {r.node_id: [Block.from_json(b) for b in json.loads(r.blocks)]
                for r in rows if r.rcept_no == rcept_no and r.node_id in node_ids}
    finally:
        db.close()


def save_report(ctx: SkillContext, rcept_no: str, **fields) -> None:
    """개요·매출 구성 중 새로 만든 것만 보고서에 남긴다."""
    db = ctx.session_factory()
    try:
        row = db.get(StockReport, rcept_no)
        if row is None:  # 그사이 오래된 보고서로 정리됐다
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


# --- 목차 ---

def outline(entries: Sequence[Entry]) -> str:
    parents = {e.parent_id for e in entries}
    return "\n".join(
        f'{"  " * (e.level - 1)}[{e.node_id}] {e.title} ({e.chars:,})' + (f" — {e.summary}" if e.summary else "")
        for e in entries if e.chars >= SUMMARY_MIN_CHARS or e.node_id in parents)


def expand(entries: Sequence[Entry], ids: Iterable[str]) -> List[Entry]:
    """고른 노드. 본문이 거의 없는 장(하위 절만 있는)을 고르면 그 하위 절들을 읽는다."""
    by_id = {e.node_id: e for e in entries}
    picked: List[Entry] = []
    for node_id in ids:
        e = by_id.get(node_id)
        if e is None or e in picked:
            continue
        children = [c for c in entries if c.parent_id == node_id]
        if e.chars < SUMMARY_MIN_CHARS and children:
            picked += [c for c in children if c not in picked]
        else:
            picked.append(e)
    return picked


def keywords(*texts: Optional[str]) -> List[str]:
    """큰 표에서 행을 고를 낱말. '연구개발비와' → '연구개발비'."""
    words = []
    for text in texts:
        for w in _WORD.findall(text or ""):
            w = _PARTICLE.sub("", w)
            if len(w) >= 2 and w not in words:
                words.append(w)
    return words


class NodePick(BaseModel):
    ids: List[str] = Field(description="답이 있을 가능성이 높은 순서로 목차의 id 1~3개")
    keywords: List[str] = Field(default_factory=list, description="큰 표에서 골라 읽을 행의 낱말. 없으면 비움")


async def pick_nodes(ctx: SkillContext, entries: Sequence[Entry], need: str) -> tuple[List[Entry], List[str]]:
    """목차에서 노드를 고른다. 목차에 없는 id만 고르면 한 번 더 묻는다."""
    agent = Agent(build_model(ctx.ai_config), output_type=NodePick, instructions=NAV_PROMPT,
                  model_settings={**NO_THINKING, "temperature": 0})
    prompt = f"## 목차\n{outline(entries)}\n\n## 찾을 것\n{need}\n\n## 사용자 질문\n{ctx.question}"
    result = await agent.run(prompt)
    picked = expand(entries, result.output.ids[:PICK_MAX])
    if not picked:
        result = await agent.run(f"{prompt}\n\n## 주의\n방금 고른 id({', '.join(result.output.ids)})는 목차에 없습니다. "
                                 "목차의 [ ] 안에 있는 id만 고르세요.")
        picked = expand(entries, result.output.ids[:PICK_MAX])
    return picked, result.output.keywords


def read_nodes(picked: Sequence[Entry], blocks: Dict[str, List[Block]], words: Sequence[str],
               node_chars: int, total: int) -> str:
    parts, used = [], 0
    for e in picked:
        if e.node_id not in blocks or used >= total:
            continue
        body = render(blocks[e.node_id], keywords=words, limit=min(node_chars, total - used))
        parts.append(f"## {e.path}\n{body}")  # id를 넣으면 답에 '[447]'처럼 따라 나온다
        used += len(body)
    return "\n\n".join(parts)


# --- 화면 ---

def _header(report: Report, paths: Sequence[str] = ()) -> str:
    # 보고서 이름은 영역 제목에 있다
    head = f"{report.filed} 접수 · [DART 원문]({DART_VIEWER}{report.rcept_no})"
    if paths:
        head += "\n\n읽은 절: " + " · ".join(paths)
    return head + "\n\n"


def short_path(path: str) -> str:
    """'II. 사업의 내용 > 6. 주요계약 및 연구개발활동' → 'II. 사업의 내용 > 주요계약 및 연구개발활동'"""
    parts = path.split(" > ")
    return " > ".join([parts[0], *(re.sub(r"^(\d+(-\d+)?|[가-하])\.\s*", "", p) for p in parts[1:])])


async def stream_answer(ctx: SkillContext, instructions: str, prompt: str, tagged):
    """LLM 답을 흘려보내며 모은다. 중간에 멈추면 (텍스트, False)."""
    agent = Agent(build_model(ctx.ai_config), instructions=instructions, model_settings=NO_THINKING)
    text = ""
    async with agent.run_stream(prompt) as result:
        async for delta in result.stream_text(delta=True):
            text += delta
            yield tagged({"type": "delta", "text": delta})
            if ctx.stop.is_set():
                break
    yield text.strip()


def chart_events(name: str, report: Report, charts: List[Dict[str, Any]], text_part: Optional[Dict[str, str]] = None):
    """매출 구성 차트로 영역을 나누는 split 이벤트와 차트마다의 result. text_part가 있으면 차트 아래 영역으로 둔다."""
    source = Source(label=f"DART {report.report_nm}", as_of=report.filed)
    titles = [report_breakdowns.chart_title(name, b) for b in charts]
    yield {"type": "split", "parts": [
        *({"id": f"chart{i}", "title": t, "display": report_breakdowns.chart_display(b)}
          for i, (t, b) in enumerate(zip(titles, charts), 1)),
        *([text_part] if text_part else []),
    ]}
    for i, (t, b) in enumerate(zip(titles, charts), 1):
        yield {**report_breakdowns.chart_result(t, b, source).event(), "part": f"chart{i}"}


# --- 매출 구성 ---

def segment_notes(entries: Sequence[Entry]) -> List[Entry]:
    """재무제표 주석의 부문 정보. 연결이 있으면 연결만."""
    notes = [e for e in entries if e.path.startswith("III.") and SEGMENT_NOTE in e.title and e.chars >= SUMMARY_MIN_CHARS]
    consolidated = [e for e in notes if "(연결)" in e.title]
    return (consolidated or notes)[:1]


def mix_sources(entries: Sequence[Entry]) -> List[Entry]:
    business = [e for e in entries if e.path.startswith("II.") and any(k in e.title for k in MIX_SECTIONS)
                and e.chars >= SUMMARY_MIN_CHARS]
    return business + segment_notes(entries)


async def load_breakdowns(ctx: SkillContext, report: Report, entries: Sequence[Entry]) -> List[Dict[str, Any]]:
    """보고서의 매출 구성. 남긴 것이 없으면 매출·부문 표에서 뽑아 남긴다. 뽑다 실패하면 남기지 않아 다음에 다시 뽑는다."""
    if report.breakdowns is not None:
        return json.loads(report.breakdowns)
    sources = mix_sources(entries)
    blocks = await asyncio.to_thread(load_blocks, ctx, report.rcept_no, [e.node_id for e in sources])
    source = clip("\n\n".join(f"## {e.path}\n{render(blocks[e.node_id])}" for e in sources if e.node_id in blocks),
                  MIX_CHARS)
    try:
        found = await report_breakdowns.extract(ctx.ai_config, source) if source else []
    except Exception:
        logger.warning("Could not extract the revenue mix", exc_info=True)
        return []
    report.breakdowns = report_breakdowns.dumps(found)
    await asyncio.to_thread(save_report, ctx, report.rcept_no, breakdowns=report.breakdowns)
    return found


# --- 개요 ---

def overview_entries(entries: Sequence[Entry]) -> List[Entry]:
    chapters = [e for e in entries if e.path.startswith(OVERVIEW_CHAPTERS) and e.chars >= SUMMARY_MIN_CHARS]
    return chapters + segment_notes(entries)


def overview_source(picked: Sequence[Entry], blocks: Dict[str, List[Block]]) -> str:
    low, high = OVERVIEW_NODE_CHARS
    share = max(low, min(high, OVERVIEW_CHARS // max(len(picked), 1)))
    return clip("\n\n".join(f"## {e.path}\n{render(blocks[e.node_id], limit=share)}"
                            for e in picked if e.node_id in blocks), OVERVIEW_CHARS)


class CompanyReportSkill(Skill):
    name = "company_report"
    description = (
        "개별 종목(상장사)의 정기보고서(사업·반기·분기보고서, 기본은 가장 최근)를 목차에서 골라 읽는다. "
        "need를 비우면 개요(사업 구조, 이번 기간 영업 상황, 위험 요인, 소송·제재·기준일 이후 주요사항)와 보고서 표의 매출 구성 차트 — "
        "기업 분석, 무슨 사업을 하는지 물을 때. need에 찾을 것을 적으면 보고서의 그 절을 읽어 답한다 — 연구개발비, 직원 수·급여, "
        "최대주주·지분, 배당, 자기주식, 소송·제재, 원재료·가동률·시설투자, 임원 보수, 계열회사, 감사의견 등 보고서에 적힌 사실을 물을 때. "
        "주요 고객·매출 구성 차트만 필요하면 company_revenue_mix, 매출·영업이익 같은 주요계정 수치는 company_financials. "
        "종목 하나만 받는다"
    )
    Args = CompanyReportArgs
    displays = ("markdown",)
    uses_llm = True
    subject = "stock"
    entity_args = {"stock": "stock"}

    async def run(self, args: CompanyReportArgs, display: str, ctx: SkillContext):
        prepared = await asyncio.to_thread(prepare_report, args.stock, ctx, args.period)
        if isinstance(prepared, SkillResult):
            yield prepared.event()
            return
        stock, report, entries = prepared
        need = (args.need or "").strip()
        events = self._lookup(stock["name"], report, entries, need, ctx) if need \
            else self._overview(stock["name"], report, entries, ctx)
        async for event in events:
            yield event

    async def _lookup(self, name: str, report: Report, entries: List[Entry], need: str, ctx: SkillContext):
        # 계획 단계에서는 어느 보고서인지 모르므로 영역 제목에 실제 보고서 이름을 넣는다
        yield {"type": "title", "title": f"{name} {report.report_nm}: {need}"}
        try:
            picked, words = await pick_nodes(ctx, entries, need)
        except Exception as e:
            logger.warning("Could not pick report nodes", exc_info=True)
            yield SkillResult(status="failed", message=f"보고서 목차에서 절을 고르지 못했습니다: {str(e)[:120]}").event()
            return
        if not picked:
            yield empty(f"{name}의 {report.report_nm} 목차에서 '{need}'에 맞는 절을 찾지 못했습니다").event()
            return
        blocks = await asyncio.to_thread(load_blocks, ctx, report.rcept_no, [e.node_id for e in picked])
        body = read_nodes(picked, blocks, [*words, *keywords(need)], READ_NODE_CHARS, READ_CHARS)
        paths = [short_path(e.path) for e in picked]
        header = _header(report, paths)
        yield {"type": "delta", "text": header}
        prompt = f"## 보고서\n{name} {report.report_nm}\n\n## 질문\n{ctx.question}\n\n## 찾을 것\n{need}\n\n## 읽은 절\n{body}"
        answer = ""
        async for item in stream_answer(ctx, LOOKUP_PROMPT, prompt, lambda e: e):
            if isinstance(item, str):
                answer = item
            else:
                yield item
        if not answer:
            yield SkillResult(status="failed", message=f"{report.report_nm}에서 답을 정리하지 못했습니다").event()
            return
        yield {"type": "delta", "text": FOOTER}
        result = text_result(header + answer + FOOTER, kind="markdown")
        result.summary = (f"{name}의 {report.report_nm} ({report.filed} 접수)에서 '{need}'을(를) 찾아 읽은 절 "
                          f"({', '.join(paths)}):\n{answer}")
        yield result.event()

    async def _overview(self, name: str, report: Report, entries: List[Entry], ctx: SkillContext):
        title = f"{name} {report.report_nm} 요약"
        breakdowns = await load_breakdowns(ctx, report, entries)
        charts = report_breakdowns.choose(breakdowns, ctx.question)
        part = None
        if charts:  # 매출 구성이 있으면 차트 영역과 요약 영역으로 나눈다 — 요약을 흘려보내기 전에
            part = "text"
            for event in chart_events(name, report, charts, {"id": part, "title": title, "display": "markdown"}):
                yield event
        else:
            yield {"type": "title", "title": title}

        def tagged(event: Dict[str, Any]) -> Dict[str, Any]:
            return {**event, "part": part} if part else event

        def done(summary: str) -> Dict[str, Any]:
            # 화면은 흘려받은 텍스트를 그대로 두므로 본문은 머리줄 + 요약 + 꼬리말, 흘려보낸 순서와 같게 만든다
            result = text_result(_header(report) + summary + FOOTER, kind="markdown")
            result.summary = f"{name}의 {report.report_nm} ({report.filed} 접수) 본문 요약:\n{summary}"
            return tagged(result.event())

        if report.overview:
            yield done(report.overview)
            return
        picked = overview_entries(entries)
        blocks = await asyncio.to_thread(load_blocks, ctx, report.rcept_no, [e.node_id for e in picked])
        source = overview_source(picked, blocks)
        if not source:
            yield tagged(empty(f"{report.report_nm}에서 사업의 내용을 찾지 못했습니다").event())
            return
        yield tagged({"type": "delta", "text": _header(report)})
        summary = ""
        async for item in stream_answer(ctx, OVERVIEW_PROMPT, f"## 보고서\n{name} {report.report_nm}\n\n## 보고서 본문\n{source}",
                                        tagged):
            if isinstance(item, str):
                summary = item
            else:
                yield item
        if not summary:
            yield tagged(SkillResult(status="failed", message=f"{report.report_nm}을(를) 요약하지 못했습니다").event())
            return
        yield tagged({"type": "delta", "text": FOOTER})
        if not ctx.stop.is_set():  # 중간에 멈춘 요약은 남기지 않는다
            await asyncio.to_thread(save_report, ctx, report.rcept_no, overview=summary, model=ctx.ai_config.llm_model)
        yield done(summary)
