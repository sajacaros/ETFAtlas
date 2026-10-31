"""
discord_notice — 디스코드 발송과 발송 이력(discord_notification_logs), 비중변화 알림

설정 해석·발송은 backend의 app.utils.discord를 쓴다. 메시지를 여러 개로 나눠 보내다 중간에 실패하면
보낸 데까지의 개수를 이력(message_count)에 남기고, Airflow 재시도가 그 뒤부터 이어 보낸다 — 앞 메시지가 두 번 가지 않게.
"""

import json
import logging
import os
from typing import Optional

from app.utils.discord import MAX_CONTENT, post_messages, resolve_settings

from rdb import connection

log = logging.getLogger(__name__)

CHANGE_TYPE_LABELS = {'added': '신규편입', 'removed': '편출', 'increased': '증가', 'decreased': '감소'}
HEADER_PAGE_ROOM = 12  # 둘째 메시지부터 헤더에 붙는 " (10/10)\n\n" 자리
CONTINUED_ROOM = 10  # 조각 제목에 붙는 " (계속)" 자리


def load_discord_settings(conn) -> dict:
    """디스코드 알림 설정. 웹(관리자 페이지)에서 저장한 discord_settings가 우선,
    저장 전이거나 주소가 비었으면 환경변수 DISCORD_WEBHOOK_URL을 쓴다. 꺼져 있으면 webhook_url은 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT enabled, webhook_url, threshold, added_threshold, rise_threshold "
                    "FROM discord_settings WHERE id = 1")
        row = cur.fetchone()
    keys = ('enabled', 'webhook_url', 'threshold', 'added_threshold', 'rise_threshold')
    return resolve_settings(dict(zip(keys, row)) if row else None, os.environ)


def split_messages(header: str, blocks: list[str], limit: int = MAX_CONTENT) -> list[str]:
    """헤더 + 블록들을 limit 이하 메시지들로 나눈다.

    블록은 쪼개지 않고 통째로 담고, 블록 하나가 limit을 넘을 때만 줄 단위로 나눈다
    (이어지는 조각엔 제목에 '(계속)'을 붙인다). 둘째 메시지부터는 헤더에 (n/N)을 단다.
    """
    # 헤더 자리(+ " (10/10)\n\n")를 남긴 만큼이 본문에 쓸 수 있는 길이
    room = limit - len(header) - HEADER_PAGE_ROOM
    pieces = []
    for block in blocks:
        if len(block) <= room:
            pieces.append(block)
            continue
        title, *lines = block.split("\n")
        cur = title
        for line in lines:
            line = line[:room - len(title) - CONTINUED_ROOM]  # 한 줄이 room을 넘는 극단적 경우 대비
            if len(cur) + 1 + len(line) > room:
                pieces.append(cur)
                cur = f"{title} (계속)"
            cur += "\n" + line
        pieces.append(cur)

    messages, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 2 + len(piece) > room:
            messages.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        messages.append(cur)

    total = len(messages)
    if total == 1:
        return [f"{header}\n\n{messages[0]}"]
    return [f"{header} ({i}/{total})\n\n{m}" for i, m in enumerate(messages, 1)]


# ──────────────────────────────────────────────
# 발송 이력
# ──────────────────────────────────────────────

def already_sent(conn, kind: str, date_str: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM discord_notification_logs "
                    "WHERE kind = %s AND base_date = %s AND status = 'sent' LIMIT 1", (kind, date_str))
        return cur.fetchone() is not None


def record_notification(conn, date_str: str, threshold: float, items, message_count: int,
                        error: str | None = None, kind: str = 'weight_change'):
    """디스코드로 보낸(또는 보내다 실패한) 알림을 discord_notification_logs에 남긴다.

    message_count는 보낸 메시지 수다 — 실패한 행이면 실패하기 전까지 간 개수(다음 시도가 그 뒤부터 보낸다).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO discord_notification_logs "
            "(kind, base_date, status, threshold, items, message_count, error, sent_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now() AT TIME ZONE 'utc')",
            (kind, date_str, 'failed' if error else 'sent', threshold,
             json.dumps(items, ensure_ascii=False), message_count, error),
        )
    conn.commit()


def interrupted_send(conn, kind: str, date_str: str) -> Optional[dict]:
    """그 날짜의 마지막 발송이 메시지 몇 개를 보낸 뒤 실패했으면 {'sent': 보낸 개수, 'items': 그때 남긴 items}. 아니면 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT status, message_count, items FROM discord_notification_logs "
                    "WHERE kind = %s AND base_date = %s ORDER BY id DESC LIMIT 1", (kind, date_str))
        row = cur.fetchone()
    if row and row[0] == 'failed' and row[1]:
        return {'sent': row[1], 'items': row[2]}
    return None


def resume_start(interrupted: Optional[dict], messages: list[str]) -> int:
    """이어 보낼 위치. 보낸 개수가 메시지 수 이상이면 예전 형식 기록(message_count = 전체 메시지 수)이라 처음부터."""
    sent = interrupted['sent'] if interrupted else 0
    return sent if sent < len(messages) else 0


def deliver(conn, webhook_url: str, kind: str, date_str: str, threshold: float, items, messages: list[str],
            start: int = 0, failure: str = "Discord notification failed") -> None:
    """messages[start:]를 보내고 이력을 남긴다. 실패하면 예외를 올려 Airflow 재시도가 남은 메시지를 보내게 한다."""
    if start:
        log.info(f"Resuming Discord {kind} for {date_str} after {start}/{len(messages)} message(s)")
    sent, error = post_messages(webhook_url, messages, start)
    record_notification(conn, date_str, threshold, items, sent if error else len(messages), error, kind=kind)
    if error:
        # 예외 체인에도 웹훅 주소가 남지 않게 새 예외로 올린다
        raise RuntimeError(f"{failure}: {error}")


# ──────────────────────────────────────────────
# 비중변화 알림
# ──────────────────────────────────────────────

def group_weight_changes(rows) -> list[dict]:
    """weight_changes 행(변화량 큰 순) → ETF별 묶음. ETF는 가장 큰 변화가 큰 순, 종목은 변화량 큰 순."""
    items, by_etf = [], {}
    for etf_code, etf_name, prev_date, stock_code, stock_name, ct, pw, cw, diff in rows:
        if etf_code not in by_etf:
            by_etf[etf_code] = {'etf_code': etf_code, 'etf_name': etf_name, 'prev_date': prev_date, 'changes': []}
            items.append(by_etf[etf_code])
        by_etf[etf_code]['changes'].append({
            'stock_code': stock_code,
            'stock_name': stock_name,
            'change_type': ct,
            'previous_weight': pw,
            'current_weight': cw,
            'weight_change': diff,
        })
    return items


def weight_change_header(date_str: str) -> str:
    # 날짜는 구성종목 공시일 — 실제 매매는 직전 영업일 장중에 일어난 것
    return f"📊 **ETF 비중 변화 알림** ({date_str} 공시)"


def weight_change_blocks(items: list[dict]) -> list[str]:
    return [
        f"**{item['etf_name']}** ({item['etf_code']})\n" + "\n".join(
            f"  {CHANGE_TYPE_LABELS[c['change_type']]} {c['stock_name']}: "
            f"{c['previous_weight']:.1f}% → {c['current_weight']:.1f}% ({c['weight_change']:+.1f}%p)"
            for c in item['changes']
        )
        for item in items
    ]


def send_discord_notification(date_str: str):
    """weight_changes에 저장된 액티브 ETF 비중변화 중 기준값을 넘는 것을 디스코드로 발송. 없으면 없다고 한 번 보낸다.

    이미 보낸 날짜(발송 이력에 성공 기록)면 건너뛴다. 발송에 실패하면 이력에 남기고 예외를 올려
    Airflow 재시도가 남은 메시지부터 다시 보내게 한다.
    """
    with connection() as conn, conn.cursor() as cur:
        settings = load_discord_settings(conn)
        if not settings['enabled']:
            log.info("Discord notification disabled — skipping")
            return
        webhook_url = settings['webhook_url']
        if not webhook_url:
            log.info("Discord webhook URL not set — skipping Discord notification")
            return
        threshold, added_threshold = settings['threshold'], settings['added_threshold']

        # 변화 없음 알림만 보낸 날은 뒤 실행(16:30 재수집)에서 변화가 생기면 다시 보낸다
        cur.execute("SELECT items FROM discord_notification_logs "
                    "WHERE kind = 'weight_change' AND base_date = %s AND status = 'sent'",
                    (date_str,))
        sent = [r[0] for r in cur.fetchall()]
        if any(sent):
            log.info(f"Discord notification for {date_str} already sent — skipping")
            return

        cur.execute(
            "SELECT etf_code, etf_name, prev_date, stock_code, stock_name, change_type, "
            "previous_weight, current_weight, weight_change "
            "FROM weight_changes WHERE base_date = %s "
            "AND abs(weight_change) > CASE WHEN change_type = 'added' THEN %s ELSE %s END "
            "ORDER BY abs(weight_change) DESC",
            (date_str, added_threshold, threshold),
        )
        items = group_weight_changes(cur.fetchall())

        header = weight_change_header(date_str)
        if items:
            # 디스코드 메시지 발송 — 2000자 제한에 맞춰 나눠 보낸다
            messages = split_messages(header, weight_change_blocks(items))
        else:
            if sent:
                log.info(f"No-change notification for {date_str} already sent — skipping")
                return
            # 비중이 조금이라도 바뀐 ETF 수를 함께 적는다 — 0이면 계산이 비었는지 의심할 수 있다
            cur.execute("SELECT count(DISTINCT etf_code) FROM weight_changes WHERE base_date = %s", (date_str,))
            changed_etfs = cur.fetchone()[0]
            messages = [f"{header}\n\n기준값(비중 ±{threshold:g}%p, 신규편입 {added_threshold:g}%p)을 넘는 변화가 없습니다. "
                        f"(비중이 조금이라도 바뀐 액티브 ETF {changed_etfs}개)"]

        start = resume_start(interrupted_send(conn, 'weight_change', date_str), messages)
        deliver(conn, webhook_url, 'weight_change', date_str, threshold, items, messages, start)
        log.info(f"Discord notification sent: {len(items)} ETFs with changes in {len(messages)} message(s)")
