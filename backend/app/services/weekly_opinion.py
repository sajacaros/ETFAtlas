"""주간 매수 의견: 토요일 아침 ETF가 담은 주식 전체에 매수 의견(stock_opinion)을 내고, '사 볼 만하다' 상위 10개를 디스코드로 알린다.

- 종목마다 챗봇의 '살까 말까' 답과 같은 영역(차트·분기 실적·밸류에이션·유형·정기보고서 개요 — 레이아웃 예시 0038)을
  스킬로 채우고 stock_opinion이 관점별로 판정한다. 종합 의견은 규칙(app/domain/opinion.py)이 정한다.
- 순위: '사 볼 만하다' 중 점수(관점 평균) → 재무 판정 → 시가총액 순. 10개가 안 되면 있는 만큼만 알린다.
- 결과는 stock_opinions에 남는다. 백엔드가 중간에 다시 떠도 판정한 종목은 건너뛰고, 다음 주는 새로 들어온 종목을 표시한다.
- 회사 소개(50자)는 뽑힌 종목만 보고서 개요의 사업 구조로 만들어 stock_reports.tagline에 남긴다.
- 언제 돌지는 Airflow `weekly_opinion` DAG가 정해 내부 엔드포인트(routers/internal.py)로 start()를 부른다.
  airflow에는 pydantic_ai·챗봇 스킬이 없어 판정은 백엔드가 한다. DAG를 꺼 둔 로컬에서는 돌지 않는다.
  손으로 돌리려면 `python -m app.services.weekly_opinion --limit 5 --dry-run` (저장·발송 없이 메시지만 출력).
"""
import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from pydantic_ai import Agent
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from ..database import SessionLocal
from ..domain.opinion import BUY, SCORE, UNDECIDED
from ..models.dart import StockReport
from ..models.discord_notification_log import DiscordNotificationLog
from ..models.stock_opinion import OpinionRun, StockOpinion
from ..utils.discord import SAFE_CONTENT as DISCORD_MAX
from ..utils.time import KST, utcnow
from . import discord_notify
from .ai_config import AIConfig, load_ai_config
from .answer.skills import REGISTRY
from .answer.skills.base import SkillContext, related_text, skill_results
from .answer.skills.company_report import pick_report, report_rows
from .answer.skills.stock_opinion import PERSPECTIVES, TYPE_LABEL, overall
from .chat_memory import ConversationContext
from .entities import EntityResolver
from .flow.nodes.source import universe
from .llm import NO_THINKING, build_model

logger = logging.getLogger(__name__)

WORKERS = 3  # 동시에 판정할 종목 수. 챗봇과 같은 LLM을 나눠 쓴다
STALE = timedelta(minutes=30)  # 맡은 프로세스가 이만큼 소식이 없으면 다른 프로세스가 이어 맡는다
TOP = 10
TAGLINE_CHARS = 50
REASON_CHARS = 160
FAILED = "실패"
NOTICE_KIND = "weekly_opinion"

# 챗봇 '살까 말까' 답의 영역 (migrations 0038 _opinion_plan과 같다): (스킬, 제목, 화면, 인자)
SLOTS = (
    ("stock_technical", "차트 분석", "candlestick", lambda code: {"stock": code}),
    ("company_financials", "분기 실적", "bar", lambda code: {"stock": code, "basis": "quarter", "periods": 8}),
    ("company_valuation", "밸류에이션", "table", lambda code: {"stocks": [code]}),
    ("company_type", "유형 판정", "table", lambda code: {"stock": code}),
    ("company_report", "정기보고서", "markdown", lambda code: {"stock": code}),
)
# 메시지에 근거 한 줄을 고를 때 같은 판정이면 이 순서
REASON_ORDER = ("financials", "report", "chart")

TAGLINE_PROMPT = """아래는 한 회사의 정기보고서 요약 중 사업 구조입니다. 이 회사가 무엇을 하는 회사인지 한국어 한 문장, 50자 이내로 쓰세요.
- 주력 제품·서비스와 업종이 드러나게. 수치·연도·전망·평가는 넣지 마세요.
- 회사 이름으로 시작하지 말고 '~ 기업', '~ 회사'처럼 명사로 끝내세요. 머리말이나 따옴표 없이 그 문장만."""

DISCLAIMER = "-# 시세·DART 실적·정기보고서를 정해진 관점으로 읽은 참고 의견이며 투자 권유가 아닙니다. 업황·수급·뉴스는 보지 않았습니다."


# --- 종목 하나 ---

def _market_cap(event: Dict[str, Any]) -> Optional[float]:
    rows = ((event.get("content") or {}).get("dataset") or {}).get("rows") or []
    return rows[0].get("market_cap") if rows else None


async def judge_stock(stock: Dict[str, str], ai_config: AIConfig) -> Dict[str, Any]:
    """stock_opinions 한 행의 값. 판정하지 못하면 verdict가 판단 보류나 실패."""
    code, name = stock["code"], stock["name"]
    ctx = SkillContext(question=f"{name} 지금 사도 될까?", conversation=ConversationContext(),
                       session_factory=SessionLocal, resolver=EntityResolver(), ai_config=ai_config,
                       stop=asyncio.Event())
    row: Dict[str, Any] = {"stock_code": code, "name": name}
    related = []
    for skill_name, title, display, args in SLOTS:
        skill = REGISTRY[skill_name]
        title = f"{name} {title}"
        try:
            # 정기보고서는 매출 구성 차트로 영역을 나누면 영역마다 결과가 온다
            async for shown, result in skill_results(skill, skill.Args(**args(code)), display, ctx, title):
                related.append((shown, related_text(result)))
                if skill_name == "company_valuation":
                    row["market_cap"] = _market_cap(result)
        except Exception:
            logger.exception("Weekly opinion: %s (%s) %s failed", name, code, skill_name)
            related.append((title, "이 영역을 채우지 못했습니다"))
    ctx.related = related
    try:
        judged = await REGISTRY["stock_opinion"].judge(ctx, name)
    except Exception as e:
        logger.exception("Weekly opinion: %s (%s) opinion failed", name, code)
        return {**row, "verdict": FAILED, "error": str(e)[:500]}
    if judged is None:
        return {**row, "verdict": UNDECIDED, "error": "차트·실적·보고서 데이터가 없음"}
    opinion, company_type = judged
    verdict = overall(opinion, company_type)
    return {
        **row,
        "verdict": verdict.label, "score": verdict.score,
        **{f"{key}_rating": getattr(opinion, f"{key}_rating") for key, _ in PERSPECTIVES},
        "company_type": (company_type.category or TYPE_LABEL[company_type.status]) if company_type else None,
        "reasons": {**{key: getattr(opinion, f"{key}_reasons") for key, _ in PERSPECTIVES}, "check": opinion.check},
    }


# --- 순위와 메시지 ---

def ranked(rows: Iterable[Dict[str, Any]], limit: int = TOP) -> List[Dict[str, Any]]:
    """'사 볼 만하다' 중 점수 → 재무 판정 → 시가총액 순으로 limit개."""
    buys = [r for r in rows if r["verdict"] == BUY]
    return sorted(buys, key=lambda r: (-(r.get("score") or 0), -SCORE.get(r.get("financials_rating"), -3),
                                       -(r.get("market_cap") or 0), r["stock_code"]))[:limit]


def best_reason(row: Dict[str, Any]) -> Optional[str]:
    """판정이 가장 좋은 관점의 첫 근거."""
    reasons = row.get("reasons") or {}
    keys = sorted((k for k in REASON_ORDER if reasons.get(k)),
                  key=lambda k: -SCORE.get(row.get(f"{k}_rating"), -3))
    return reasons[keys[0]][0] if keys else None


def _block(rank: int, row: Dict[str, Any], tagline: Optional[str], new: bool) -> str:
    lines = [f"**{rank}. {row['name']}** `{row['stock_code']}` {row['score']:+.1f}점" + (" 🆕" if new else "")]
    if tagline:
        lines.append(tagline)
    ratings = " · ".join(f"{label.removesuffix(' 분석')} {row.get(f'{key}_rating')}" for key, label in PERSPECTIVES)
    lines.append(ratings + (f" | {row['company_type']}" if row.get("company_type") else ""))
    reason = best_reason(row)
    if reason:
        lines.append(f"└ {clip(reason, REASON_CHARS)}")
    return "\n".join(lines)


def chunk(blocks: List[str], limit: int = DISCORD_MAX) -> List[str]:
    """블록을 자르지 않고 limit자 안으로 묶는다. 블록 하나가 limit보다 길면 그 블록만 자른다."""
    messages: List[str] = []
    for block in blocks:
        block = clip(block, limit)
        if messages and len(messages[-1]) + 2 + len(block) <= limit:
            messages[-1] += "\n\n" + block
        else:
            messages.append(block)
    return messages


def format_report(run_on: date, rows: List[Dict[str, Any]], picks: List[Dict[str, Any]],
                  taglines: Dict[str, Optional[str]], previous: Optional[Set[str]]) -> List[str]:
    """previous: 지난 차례에 알린 종목 코드 (첫 차례면 None — 새로 들어옴을 표시하지 않는다)."""
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    order = [BUY, "지켜본다", "사지 않는 편이 낫다", UNDECIDED, FAILED]
    header = [f"📊 **주간 매수 의견** {run_on.isoformat()} — ETF가 담은 주식 {len(rows)}종목",
              " · ".join(f"{v} {counts[v]}" for v in order if counts.get(v))]
    if picks:
        header.append(f"'{BUY}' 상위 {len(picks)}개 (점수는 차트·재무·보고서 판정 평균, 긍정 +2 ~ 부정 −2)")
    else:
        header.append(f"이번 주는 '{BUY}' 종목이 없습니다.")
    blocks = ["\n".join(header)]
    blocks += [_block(i, r, taglines.get(r["stock_code"]), previous is not None and r["stock_code"] not in previous)
               for i, r in enumerate(picks, 1)]
    blocks.append(DISCLAIMER)
    return chunk(blocks)


# --- 회사 소개 ---

def business_section(overview: str) -> str:
    """개요의 '사업 구조' 부분 (없으면 앞부분)."""
    head = "#### 사업 구조"
    if head not in overview:
        return overview[:1500]
    body = overview.split(head, 1)[1]
    return body.split("####", 1)[0].strip()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_tagline(text: str) -> str:
    return clip(next((ln.strip(" -*•'\"“”") for ln in (text or "").splitlines() if ln.strip()), ""), TAGLINE_CHARS)


def _latest_report(code: str) -> Optional[StockReport]:
    db = SessionLocal()
    try:
        row = pick_report(report_rows(db, code), None)
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def _save_tagline(rcept_no: str, tagline: str) -> None:
    db = SessionLocal()
    try:
        db.execute(update(StockReport).where(StockReport.rcept_no == rcept_no).values(tagline=tagline))
        db.commit()
    finally:
        db.close()


async def tagline(code: str, name: str, ai_config: AIConfig) -> Optional[str]:
    """최신 보고서의 회사 소개. 남긴 게 없으면 개요로 만들어 남긴다. 개요가 없으면 None."""
    report = await asyncio.to_thread(_latest_report, code)
    if report is None or not report.overview:
        return None
    if report.tagline:
        return report.tagline
    agent = Agent(build_model(ai_config), instructions=TAGLINE_PROMPT, model_settings={**NO_THINKING, "temperature": 0})
    try:
        result = await agent.run(f"## 회사\n{name}\n\n## 사업 구조\n{business_section(report.overview)}")
    except Exception:
        logger.warning("Weekly opinion: tagline for %s failed", name, exc_info=True)
        return None
    text = clean_tagline(result.output)
    if text:
        await asyncio.to_thread(_save_tagline, report.rcept_no, text)
    return text or None


# --- 저장 ---

def claim(run_on: date) -> bool:
    """이 차례를 맡는다. 처음이거나, 맡은 프로세스가 STALE 동안 소식이 없으면 True."""
    db = SessionLocal()
    try:
        now = utcnow()
        inserted = db.execute(insert(OpinionRun).values(run_on=run_on, status="running", started_at=now, heartbeat_at=now)
                              .on_conflict_do_nothing()).rowcount
        if not inserted:
            inserted = db.execute(update(OpinionRun).where(
                OpinionRun.run_on == run_on, OpinionRun.status == "running", OpinionRun.heartbeat_at < now - STALE,
            ).values(heartbeat_at=now)).rowcount
        db.commit()
        return bool(inserted)
    finally:
        db.close()


ROW_FIELDS = ("name", "verdict", "score", "chart_rating", "financials_rating", "report_rating", "company_type",
              "reasons", "market_cap", "rank", "error")


def _as_dict(o: StockOpinion) -> Dict[str, Any]:
    return {"stock_code": o.stock_code, **{f: getattr(o, f) for f in ROW_FIELDS}}


def load_rows(run_on: date) -> Dict[str, Dict[str, Any]]:
    db = SessionLocal()
    try:
        return {o.stock_code: _as_dict(o) for o in db.query(StockOpinion).filter(StockOpinion.run_on == run_on)}
    finally:
        db.close()


def save_row(run_on: date, row: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        values = {f: row.get(f) for f in ROW_FIELDS}
        db.execute(insert(StockOpinion).values(run_on=run_on, stock_code=row["stock_code"], created_at=utcnow(), **values)
                   .on_conflict_do_update(index_elements=["run_on", "stock_code"], set_=values))
        db.execute(update(OpinionRun).where(OpinionRun.run_on == run_on).values(heartbeat_at=utcnow()))
        db.commit()
    finally:
        db.close()


def save_ranks(run_on: date, picks: List[Dict[str, Any]]) -> None:
    db = SessionLocal()
    try:
        db.execute(update(StockOpinion).where(StockOpinion.run_on == run_on).values(rank=None))
        for i, r in enumerate(picks, 1):
            db.execute(update(StockOpinion).where(StockOpinion.run_on == run_on, StockOpinion.stock_code == r["stock_code"])
                       .values(rank=i))
        db.commit()
    finally:
        db.close()


def previous_picks(run_on: date) -> Optional[Set[str]]:
    """지난 차례(마친 것 중 가장 최근)에 알린 종목. 지난 차례가 없으면 None."""
    db = SessionLocal()
    try:
        last = (db.query(OpinionRun.run_on).filter(OpinionRun.run_on < run_on, OpinionRun.status == "done")
                .order_by(OpinionRun.run_on.desc()).first())
        if last is None:
            return None
        return {c for (c,) in db.query(StockOpinion.stock_code)
                .filter(StockOpinion.run_on == last[0], StockOpinion.rank.isnot(None))}
    finally:
        db.close()


def already_sent(run_on: date) -> bool:
    db = SessionLocal()
    try:
        return db.query(DiscordNotificationLog.id).filter(
            DiscordNotificationLog.kind == NOTICE_KIND, DiscordNotificationLog.base_date == run_on.isoformat(),
            DiscordNotificationLog.status == "sent").first() is not None
    finally:
        db.close()


def finish(run_on: date) -> None:
    db = SessionLocal()
    try:
        db.execute(update(OpinionRun).where(OpinionRun.run_on == run_on).values(status="done", finished_at=utcnow()))
        db.commit()
    finally:
        db.close()


def record_notice(run_on: date, picks: List[Dict[str, Any]], count: int, error: Optional[str]) -> None:
    db = SessionLocal()
    try:
        db.add(DiscordNotificationLog(
            kind=NOTICE_KIND, base_date=run_on.isoformat(), status="failed" if error else "sent", threshold=0,
            items=[{"rank": i, "code": r["stock_code"], "name": r["name"], "score": r["score"]} for i, r in enumerate(picks, 1)],
            message_count=count, error=error))
        db.commit()
    finally:
        db.close()


async def send(messages: List[str]) -> Optional[str]:
    """보내지 못하면 그 이유. 웹훅이 없거나 꺼져 있으면 보내지 않고 None."""
    return await discord_notify.send(messages, "Weekly opinion")


# --- 한 차례 ---

def _context() -> tuple:
    db = SessionLocal()
    try:
        stocks = sorted(universe(db), key=lambda s: s["code"])
        return load_ai_config(db), stocks
    finally:
        db.close()


async def run_week(run_on: date, limit: Optional[int] = None, dry_run: bool = False,
                   codes: Optional[Set[str]] = None) -> List[str]:
    """맡은 차례를 끝까지 돈다 (dry_run이면 저장·발송 없이 메시지만 돌려준다). 보낸(보낼) 메시지 목록."""
    ai_config, stocks = await asyncio.to_thread(_context)
    stocks = [s for s in stocks if s["code"] in codes] if codes else stocks
    stocks = stocks[:limit] if limit else stocks
    rows = {} if dry_run else await asyncio.to_thread(load_rows, run_on)
    todo = [s for s in stocks if s["code"] not in rows]
    logger.info("Weekly opinion %s: %d stocks, %d already judged", run_on, len(stocks), len(stocks) - len(todo))
    gate = asyncio.Semaphore(WORKERS)

    async def one(stock: Dict[str, str]) -> None:
        async with gate:
            row = await judge_stock(stock, ai_config)
        rows[stock["code"]] = row
        if not dry_run:
            await asyncio.to_thread(save_row, run_on, row)
        if len(rows) % 50 == 0:
            logger.info("Weekly opinion %s: %d/%d judged", run_on, len(rows), len(stocks))

    await asyncio.gather(*(one(s) for s in todo))
    picks = ranked(rows.values())
    taglines = {r["stock_code"]: await tagline(r["stock_code"], r["name"], ai_config) for r in picks}
    previous = None if dry_run else await asyncio.to_thread(previous_picks, run_on)
    messages = format_report(run_on, list(rows.values()), picks, taglines, previous)
    if dry_run:
        return messages
    await asyncio.to_thread(save_ranks, run_on, picks)
    if not await asyncio.to_thread(already_sent, run_on):
        error = await send(messages)
        await asyncio.to_thread(record_notice, run_on, picks, len(messages), error)
    await asyncio.to_thread(finish, run_on)
    logger.info("Weekly opinion %s done: %d picks", run_on, len(picks))
    return messages


_running: Set[asyncio.Task] = set()  # 끝나기 전에 가비지 컬렉션되지 않게 잡아 둔다


async def _run_logged(run_on: date) -> None:
    try:
        await run_week(run_on)
    except Exception:
        # 차례는 running으로 남고, STALE이 지나면 DAG가 다시 부를 때 이어 맡는다
        logger.exception("Weekly opinion %s failed", run_on)


async def start(run_on: date) -> bool:
    """이 차례를 맡을 수 있으면 백그라운드로 시작한다. 이미 끝났거나 다른 프로세스가 돌고 있으면 False."""
    if not await asyncio.to_thread(claim, run_on):
        return False
    task = asyncio.create_task(_run_logged(run_on))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="주간 매수 의견을 손으로 돌린다")
    parser.add_argument("--date", help="차례 날짜 YYYY-MM-DD (기본: 오늘, 한국 시각)")
    parser.add_argument("--limit", type=int, help="앞에서부터 이 종목 수만 (시험용)")
    parser.add_argument("--codes", help="이 종목만, 쉼표로 구분 (시험용)")
    parser.add_argument("--dry-run", action="store_true", help="저장·발송 없이 메시지만 출력")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_on = date.fromisoformat(args.date) if args.date else datetime.now(KST).date()
    if (args.limit or args.codes) and not args.dry_run:  # 일부만 돌고 차례를 마치면 그 주는 다시 돌지 않는다
        parser.error("--limit·--codes는 --dry-run과 함께만 쓴다")
    if not args.dry_run and not claim(run_on):
        raise SystemExit(f"{run_on} 차례는 이미 끝났거나 다른 프로세스가 돌고 있습니다")
    for message in asyncio.run(run_week(run_on, args.limit, args.dry_run,
                                          set(args.codes.split(",")) if args.codes else None)):
        print(message, end="\n\n---\n\n")


if __name__ == "__main__":
    main()
