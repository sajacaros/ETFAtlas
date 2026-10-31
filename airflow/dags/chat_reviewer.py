"""
chat_reviewer — 전날 챗봇 대화를 검토해 제대로 안 나온 답과 고칠 곳을 디스코드로 알린다 (chat_review DAG의 태스크 본문)

단계 설명은 chat_review.py 맨 위에 있다.
"""

import ast
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from ai_config import load_ai_config
from discord_notice import already_sent, deliver, interrupted_send, load_discord_settings, resume_start, split_messages
from market_calendar import KST
from rdb import connection

log = logging.getLogger(__name__)

NOTICE_KIND = 'chat_review'
SKILLS_DIR = Path('/opt/backend/app/services/answer/skills')
SKILL_DESC_CHARS = 400  # 스킬 설명은 앞부분만 — 언제 쓰는지가 앞에 있다
ANSWER_CHARS = 1200
SLOT_SUMMARY_CHARS = 300
AGENT_ERROR_MIN = 2  # agent 도구 오류가 이만큼 쌓이면 신호로 본다
REVIEW_TIMEOUT = 300
REVIEW_MAX_TOKENS = 4096

CAUSE_LABELS = {
    'routing': '스킬 선택',
    'combination': '영역 구성',
    'skill': '스킬 결과',
    'tool': 'agent 도구',
    'missing': '없는 기능',
    'data': '데이터 없음',
    'system': '중단·오류',
}

REVIEW_SYSTEM_PROMPT = """당신은 ETF·주식 챗봇의 답변을 검수하는 개발자입니다. 사용자와 챗봇의 대화 한 세션을 보고, 제대로 답하지 못한 턴을 골라 원인과 고칠 곳을 적습니다.

챗봇 구조:
- 레이아웃 플래너가 질문을 보고 화면을 영역(슬롯)으로 나누고, 영역마다 스킬 하나를 고른다
- 스킬은 정해진 데이터를 가져와 표·차트·글로 보여 준다. 맞는 스킬이 없으면 agent(LLM이 도구로 직접 조회)가 맡는다
- narrative는 다른 영역 결과를 받아 요약 글을 쓴다
- 각 영역의 표시 방식(table, line, bar, donut, treemap, candlestick, text 등)은 영역 줄의 <표시>에 있다. 답변 텍스트는 화면을 글로 옮긴 것이라 차트도 표나 목록으로 적혀 있다
- 플래너는 비슷한 질문의 레이아웃 예시를 참고한다. 그래서 영역 구성 문제는 레이아웃 예시를 추가해 고칠 수 있다

원인(cause)은 하나만 고른다:
- routing: 맞는 스킬이 있는데 다른 스킬(특히 agent)을 골랐다 → 스킬 description 또는 레이아웃 예시
- combination: 스킬은 맞지만 영역이 모자라거나 남거나, 질문이 원한 표시(차트 종류 등)가 아니다 → 레이아웃 예시
- skill: 스킬이 틀린 값·빈 결과·질문과 어긋난 내용을 냈다 → 그 스킬 코드
- tool: agent가 도구 호출을 반복해서 틀렸다(쿼리 오류 등) → 도구 설명이나 코드
- missing: 이 질문에 답할 스킬·도구가 없다 → 새 스킬 또는 기존 스킬 확장
- data: 기능은 있는데 그 대상의 데이터가 없다 → 수집
- system: 답을 끝내지 못했다(멈춤·중단·오류)

판정 기준:
- 다음 턴에서 사용자가 지적하거나, 같은 걸 다시 묻거나, 다른 말로 다시 시키면 앞 턴은 문제다
- 답이 "데이터가 없다", "계산할 수 없다"인데 스킬 목록에 그걸 하는 스킬이 있으면 routing이다
- [신호]로 표시된 턴은 꼭 따져 보되, 답이 질문에 맞게 나왔으면 문제로 올리지 않는다
- 질문에 맞게 답한 턴은 올리지 않는다. 문제가 없으면 issues를 비운다
- 투자 판단 자체의 옳고 그름이나 문체는 따지지 않는다

쓰는 법:
- problem: 사용자 입장에서 무엇이 잘못 나왔는지 한 문장
- suggestion: 고칠 곳(스킬 이름, 레이아웃 예시, 도구 이름)과 방법을 한두 문장. 코드를 고쳐야 하면 무엇을 어떻게 바꿀지 적는다
- skills: 관련된 스킬 이름 (고른 스킬과 골랐어야 할 스킬)
- 한국어로, "~다" 체로 쓴다"""


class Issue(BaseModel):
    log_id: int = Field(description="문제 턴의 번호(#)")
    cause: Literal['routing', 'combination', 'skill', 'tool', 'missing', 'data', 'system']
    problem: str
    suggestion: str
    skills: list[str] = []


class SessionReview(BaseModel):
    issues: list[Issue]


def load_skill_catalog(skills_dir: Path = SKILLS_DIR) -> list[tuple[str, str]]:
    """스킬 파일에서 클래스 속성 name·description을 읽는다 (import하지 않고 구문 트리로)."""
    catalog = []
    for path in sorted(skills_dir.glob('*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError) as e:
            log.warning(f"Skill file unreadable {path.name}: {e}")
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            attrs = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    target, value = stmt.targets[0].id, stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
                    target, value = stmt.target.id, stmt.value
                else:
                    continue
                if target in ('name', 'description'):
                    try:
                        attrs[target] = ast.literal_eval(value)
                    except ValueError:
                        pass  # f-string 등 — 이름만 있어도 목록에 올린다
            if isinstance(attrs.get('name'), str):
                catalog.append((attrs['name'], ' '.join(str(attrs.get('description', '')).split())))
    return catalog


def resolve_date(params: dict) -> str:
    """수동 실행의 date(YYYY-MM-DD) 또는 어제(KST)."""
    date_str = (params.get('date') or '').strip()
    if date_str:
        datetime.strptime(date_str, '%Y-%m-%d')  # 형식 확인
        return date_str
    return (datetime.now(KST) - timedelta(days=1)).strftime('%Y-%m-%d')


def collect_turns(conn, date_str: str) -> list[dict]:
    """date_str(KST) 하루의 질문과 영역 결과. created_at은 UTC로 저장돼 있다."""
    start = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=KST)
    utc = ZoneInfo('UTC')
    start_utc = start.astimezone(utc).replace(tzinfo=None)
    end_utc = (start + timedelta(days=1)).astimezone(utc).replace(tzinfo=None)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, session_id, question, refined_question, answer, result, status, layout, steps "
            "FROM chat_logs WHERE created_at >= %s AND created_at < %s ORDER BY id",
            (start_utc, end_utc),
        )
        logs = cur.fetchall()
        if not logs:
            return []
        cur.execute(
            "SELECT chat_log_id, slot_id, skill, status, message, summary FROM chat_slots "
            "WHERE chat_log_id = ANY(%s) ORDER BY chat_log_id, slot_id",
            ([r[0] for r in logs],),
        )
        slots = defaultdict(list)
        for log_id, slot_id, skill, status, message, summary in cur.fetchall():
            slots[log_id].append({'id': slot_id, 'skill': skill, 'status': status,
                                  'message': message, 'summary': summary})

    turns = []
    for log_id, session_id, question, refined, answer, result, status, layout, steps in logs:
        layout_slots = {}
        _layout_slots(layout, layout_slots)
        agent_errors = [s.get('observations', '')[:150] for s in (steps or [])
                        if s.get('error') or str(s.get('observations', '')).startswith('쿼리 오류')]
        turns.append({
            'id': log_id, 'session_id': session_id, 'question': question, 'refined': refined,
            'answer': answer or '', 'result': result, 'feedback': status,
            'slots': [dict(s, **layout_slots.get(s['id'], {'title': '', 'display': ''})) for s in slots[log_id]],
            'agent_errors': agent_errors,
        })
    return turns


def _layout_slots(node, out: dict):
    """레이아웃 트리 → 슬롯 id별 제목·표시 방식."""
    if not isinstance(node, dict):
        return
    if node.get('type') == 'slot' and node.get('id'):
        out[node['id']] = {'title': node.get('title') or '', 'display': node.get('display') or ''}
    for child in node.get('children') or []:
        _layout_slots(child, out)


def rule_signals(turns: list[dict]) -> dict[int, list[str]]:
    """LLM 없이 잡히는 신호. 턴 번호 → 신호 목록."""
    signals = defaultdict(list)
    for t in turns:
        if t['result'] != 'completed':
            signals[t['id']].append(f"답변 {t['result']}")
        if t['feedback'] == 'disliked':
            signals[t['id']].append("싫어요")
        bad = [s for s in t['slots'] if s['status'] != 'complete']
        if bad:
            signals[t['id']].append("영역 " + ", ".join(
                f"{s['id']} {s['skill']} {s['status']}" + (f"({s['message'][:40]})" if s['message'] else '')
                for s in bad))
        if t['result'] == 'completed' and not t['answer'].strip():
            signals[t['id']].append("빈 답변")
        if len(t['agent_errors']) >= AGENT_ERROR_MIN:
            signals[t['id']].append(f"agent 도구 오류 {len(t['agent_errors'])}회")

    # 같은 질문(맥락을 푼 질문 기준)인데 고른 스킬이 달랐던 경우
    by_question = defaultdict(list)
    for t in turns:
        key = ' '.join((t['refined'] or t['question']).rstrip('.?!').split())
        by_question[key].append(t)
    for same in by_question.values():
        variants = {tuple(sorted({s['skill'] for s in t['slots']})) for t in same}
        if len(variants) > 1:
            for t in same:
                signals[t['id']].append("같은 질문인데 구성 다름")
    return dict(signals)


def _describe_turn(t: dict, signals: list[str]) -> str:
    lines = [f"## #{t['id']} 질문: {t['question']}"]
    if t['refined']:
        lines.append(f"맥락을 푼 질문: {t['refined']}")
    lines.append(f"답변 상태: {t['result']}")
    if signals:
        lines.append("[신호] " + " / ".join(signals))
    for s in t['slots']:
        line = f"- 영역 {s['id']} [{s['skill']}] {s['title']} <{s['display'] or '?'}> → {s['status']}"
        if s['message']:
            line += f" ({s['message'][:100]})"
        if s['summary']:
            line += f"\n  요약: {' '.join(s['summary'].split())[:SLOT_SUMMARY_CHARS]}"
        lines.append(line)
    for err in t['agent_errors'][:3]:
        lines.append(f"- agent 도구 오류: {' '.join(err.split())}")
    answer = t['answer'].strip()
    lines.append("답변:\n" + (answer[:ANSWER_CHARS] + (' …(생략)' if len(answer) > ANSWER_CHARS else '')
                              if answer else '(없음)'))
    return "\n".join(lines)


def review_session(client, model: str, catalog_text: str, turns: list[dict],
                   signals: dict[int, list[str]]) -> list[Issue]:
    user = (f"# 스킬 목록\n{catalog_text}\n\n# 대화 (오래된 순)\n\n"
            + "\n\n".join(_describe_turn(t, signals.get(t['id'], [])) for t in turns))
    completion = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_format=SessionReview,
        temperature=0,
        max_tokens=REVIEW_MAX_TOKENS,
        extra_body={'chat_template_kwargs': {'enable_thinking': False}},  # 켜 두면 추론만으로 한도를 넘긴다
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM returned no parsable result")
    ids = {t['id'] for t in turns}
    return [i for i in parsed.issues if i.log_id in ids]


def format_report(date_str: str, turns: list[dict], issues: list[Issue], signals: dict[int, list[str]],
                  failed_sessions: list) -> tuple[str, list[str]]:
    header = f"🩺 **챗봇 점검** ({date_str})"
    sessions = {t['session_id'] for t in turns}
    by_id = {t['id']: t for t in turns}
    blocks = []

    counts = defaultdict(int)
    for i in issues:
        counts[i.cause] += 1
    summary = f"질문 {len(turns)}건 · 세션 {len(sessions)}개 · 문제 {len(issues)}건"
    if counts:
        summary += " (" + ", ".join(f"{CAUSE_LABELS[c]} {n}" for c, n in
                                    sorted(counts.items(), key=lambda x: -x[1])) + ")"
    blocks.append(summary)

    for i in sorted(issues, key=lambda x: (list(CAUSE_LABELS).index(x.cause), x.log_id)):
        t = by_id[i.log_id]
        cause = CAUSE_LABELS[i.cause] + (f" · {', '.join(i.skills)}" if i.skills else '')
        blocks.append(
            f"**#{i.log_id}** {(t['refined'] or t['question'])[:80]}\n"
            f"원인: {cause}\n문제: {i.problem}\n제안: {i.suggestion}"
        )

    # LLM이 문제로 올리지 않은 신호도 남긴다 — 판정이 놓쳤는지 사람이 볼 수 있게
    reported = {i.log_id for i in issues}
    leftover = defaultdict(list)  # 신호 → 턴들 (같은 질문 신호는 여러 턴에 함께 붙는다)
    for log_id, sigs in sorted(signals.items()):
        if log_id not in reported:
            for sig in sigs:
                leftover[sig].append(f"#{log_id}")
    if leftover:
        blocks.append("**판정에서 뺀 신호**\n" + "\n".join(f"{', '.join(ids)} {sig}" for sig, ids in leftover.items()))
    if failed_sessions:
        blocks.append("**판정 실패 세션** " + ", ".join(str(s) for s in failed_sessions) + " — 로그 확인")
    return header, blocks


def notice_items(issues: list[Issue], failed_sessions: list) -> dict:
    """발송 이력(items)에 남길 판정 결과. 보내다 끊기면 재시도가 이것으로 같은 메시지를 다시 만든다."""
    return {'issues': [i.model_dump() for i in issues], 'failed_sessions': list(failed_sessions)}


def issues_from_items(items) -> tuple[list[Issue], list]:
    """notice_items의 반대. 예전 기록(items가 판정 목록)도 읽는다."""
    if isinstance(items, list):
        return [Issue(**i) for i in items], []
    return [Issue(**i) for i in items.get('issues', [])], items.get('failed_sessions', [])


def review_turns(conn, turns: list[dict], signals: dict[int, list[str]]) -> tuple[list[Issue], list]:
    """세션마다 등록 LLM으로 판정. (문제 목록, 판정에 실패한 세션)."""
    from openai import OpenAI

    ai = load_ai_config(conn)
    client = OpenAI(base_url=ai['llm_api_base'], api_key=ai['llm_api_key'], timeout=REVIEW_TIMEOUT)
    catalog_text = "\n".join(f"- {name}: {desc[:SKILL_DESC_CHARS]}" for name, desc in load_skill_catalog())
    by_session = defaultdict(list)
    for t in turns:
        by_session[t['session_id']].append(t)
    issues, failed_sessions = [], []
    for session_id, session_turns in by_session.items():
        try:
            found = review_session(client, ai['llm_model'], catalog_text, session_turns, signals)
        except Exception as e:
            log.warning(f"Session {session_id} review failed: {e}")
            failed_sessions.append(session_id)
            continue
        log.info(f"Session {session_id}: {len(session_turns)} turns, {len(found)} issues")
        issues.extend(found)
    return issues, failed_sessions


def run_review(date_str: str, dry_run: bool = False):
    """date_str(YYYY-MM-DD, KST) 대화를 점검해 디스코드로 보낸다. dry_run이면 보내지 않고 로그로만."""
    with connection() as conn:
        settings = load_discord_settings(conn)
        interrupted = None
        if not dry_run:
            if not settings['webhook_url']:
                log.info("Discord disabled or webhook not set — skipping chat review")
                return
            if already_sent(conn, NOTICE_KIND, date_str):
                log.info(f"Chat review for {date_str} already sent — skipping")
                return
            interrupted = interrupted_send(conn, NOTICE_KIND, date_str)

        turns = collect_turns(conn, date_str)
        signals = rule_signals(turns)
        if interrupted:
            # 몇 개를 보낸 뒤 끊겼다 — 그때의 판정으로 같은 메시지를 다시 만들어 남은 것만 보낸다
            issues, failed_sessions = issues_from_items(interrupted['items'])
        elif turns:
            issues, failed_sessions = review_turns(conn, turns, signals)
        else:
            issues, failed_sessions = [], []

        if turns:
            header, blocks = format_report(date_str, turns, issues, signals, failed_sessions)
            messages = split_messages(header, blocks)
        else:
            messages = [f"🩺 **챗봇 점검** ({date_str})\n\n챗봇 개선 제안이 없습니다."]

        if dry_run:
            for m in messages:
                log.info("Dry run message:\n%s", m)
            return

        deliver(conn, settings['webhook_url'], NOTICE_KIND, date_str, 0, notice_items(issues, failed_sessions),
                messages, resume_start(interrupted, messages))
        log.info(f"Chat review sent: {len(turns)} turns, {len(issues)} issues in {len(messages)} message(s)")
