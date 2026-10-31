"""
daily_report — 장 마감 뒤 일일 리포트(오늘의 특징·상승 ETF)를 디스코드로 보낸다
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel

from age_db import age_cursor, fetch_maps
from ai_config import load_ai_config
from discord_notice import already_sent, deliver, interrupted_send, load_discord_settings, resume_start, split_messages
from market_calendar import BUSINESS_DAY_REFERENCE_CODE
from rdb import connection

log = logging.getLogger(__name__)

NOTICE_KIND = 'daily_report'
# 일일 리포트: 목록에 보일 상승 ETF 수, 특징 요약에 넘길 최대 ETF 수, 상승 ETF마다 넘길 구성종목 수
REPORT_TOP_RISING = 10
REPORT_LLM_MAX_ETFS = 100
REPORT_TOP_HOLDINGS = 5
REPORT_PRICE_LOOKBACK_DAYS = 14  # 1일 수익률의 직전 거래일을 찾는 기간 (연휴 여유)
FEATURES_TIMEOUT = 120
FEATURES_MAX_TOKENS = 2048

DAILY_FEATURES_PROMPT = """한국 ETF 시장 분석가입니다.
그날 시장 수익률(KODEX 200)과 많이 오른 ETF 목록(이름, 1일 수익률, 비중 상위 구성종목의 비중·1일 수익률)을 받습니다.
오늘 장에서만 볼 수 있는 특징을 1~3개 항목으로 정리합니다.

규칙:
- 시장보다 뚜렷하게 더 오른 테마 묶음, 그 묶음을 끌어올린 종목, 혼자 크게 튄 종목·ETF를 쓴다
- 시장만큼 오른 ETF(지수 추종, 시가총액 상위 종목 위주 ETF)는 쓰지 않는다. 대형주 비중이 커서 함께 올랐다는 식의 구조 설명도 쓰지 않는다
- 비슷한 ETF는 하나로 묶고 개별 ETF를 하나씩 나열하지 않는다
- 항목끼리 같은 내용을 되풀이하지 않는다. 쓸 만한 특징이 하나뿐이면 하나만 쓴다
- 주어진 숫자만 쓴다. 지수 내 비중처럼 주어지지 않은 숫자를 만들지 않고, 뉴스·실적·정책 같은 상승 원인도 추측하지 않는다
- 항목마다 한 문장, "~했다" 체로 쓴다"""


class DailyFeatures(BaseModel):
    features: list[str]


def daily_return(prices: list[tuple[str, float]], date_str: str) -> float | None:
    """(날짜, 종가) 목록에서 date_str(YYYY-MM-DD) 종가의 직전 거래일 대비 수익률(%). 그날 가격이나 직전 가격이 없으면 None."""
    by_date = dict(prices)
    close = by_date.get(date_str)
    prev = [d for d in by_date if d < date_str]
    if not close or not prev:
        return None
    prev_close = by_date[max(prev)]
    if not prev_close:
        return None
    return round((close - prev_close) / prev_close * 100, 2)


def find_rising_etfs(prices: dict[str, list[tuple[str, float]]], names: dict[str, str],
                     date_str: str, threshold: float) -> list[dict]:
    """ETF별 (날짜, 종가)로 date_str 1일 수익률이 threshold(%) 이상인 ETF. 많이 오른 순."""
    rising = []
    for code, rows in prices.items():
        ret = daily_return(rows, date_str)
        if ret is not None and ret >= threshold:
            rising.append({'etf_code': code, 'etf_name': names.get(code) or code, 'return_1d': ret})
    rising.sort(key=lambda r: r['return_1d'], reverse=True)
    return rising


def price_rows(rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """{code, date, close} 행 → code별 (날짜, 종가) 목록."""
    out = defaultdict(list)
    for data in rows:
        if data.get('date') and data.get('close') is not None:
            out[data['code']].append((data['date'], float(data['close'])))
    return out


def top_holdings_with_returns(rows: list[dict], date_str: str) -> list[dict]:
    """{code, name, weight, date, close} 행(구성종목 × 가격) → 비중 상위 REPORT_TOP_HOLDINGS개와 1일 수익률."""
    holdings = {}
    for data in rows:
        holdings[data['code']] = {'stock_name': data.get('name') or data['code'], 'weight': data.get('weight') or 0}
    stock_prices = price_rows(rows)
    top = sorted(holdings.items(), key=lambda kv: kv[1]['weight'], reverse=True)[:REPORT_TOP_HOLDINGS]
    return [{'stock_code': code, **h, 'return_1d': daily_return(stock_prices.get(code, []), date_str)}
            for code, h in top]


def collect_daily_report(date_str: str, rise_threshold: float) -> dict:
    """date_str(YYYY-MM-DD)에 rise_threshold(%) 이상 오른 ETF(상위 구성종목·등락 포함)와 시장(KODEX 200) 수익률."""
    since = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=REPORT_PRICE_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    with age_cursor() as (_, cur):
        names = {d['code']: d.get('name') for d in fetch_maps(cur, "MATCH (e:ETF) RETURN {code: e.code, name: e.name}")}

        etf_prices = price_rows(fetch_maps(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= $from_date AND p.date <= $to_date
            RETURN {code: e.code, date: p.date, close: p.close}
        """, {'from_date': since, 'to_date': date_str}))

        rising = find_rising_etfs(etf_prices, names, date_str, rise_threshold)
        for etf in rising:
            etf['holdings'] = top_holdings_with_returns(fetch_maps(cur, """
                MATCH (e:ETF {code: $code})-[h:CURRENT_HOLDS]->(s:Stock)
                OPTIONAL MATCH (s)-[:HAS_PRICE]->(p:Price)
                WHERE p.date >= $from_date AND p.date <= $to_date
                RETURN {code: s.code, name: s.name, weight: h.weight, date: p.date, close: p.close}
            """, {'code': etf['etf_code'], 'from_date': since, 'to_date': date_str}), date_str)

    market_return = daily_return(etf_prices.get(BUSINESS_DAY_REFERENCE_CODE, []), date_str)
    return {'rising': rising, 'market_return': market_return}


def describe_rising_etf(etf: dict) -> str:
    parts = [f"{h['stock_name']} {h['weight']:.1f}%"
             + (f" {h['return_1d']:+.2f}%" if h['return_1d'] is not None else "")
             for h in etf.get('holdings', [])]
    return f"- {etf['etf_name']} {etf['return_1d']:+.2f}%: " + ", ".join(parts)


def features_prompt(rising: list[dict], market_return: float | None) -> str:
    shown = rising[:REPORT_LLM_MAX_ETFS]
    user = [f"시장(KODEX 200) {market_return:+.2f}%" if market_return is not None else "시장 수익률 없음",
            f"상승 ETF {len(rising)}개" + (f" (많이 오른 {len(shown)}개만)" if len(shown) < len(rising) else "")]
    user += [describe_rising_etf(e) for e in shown]
    return "\n".join(user)


def summarize_rising_etfs(rising: list[dict], market_return: float | None) -> list[str]:
    """상승 ETF 전체와 시장 수익률(KODEX 200)을 보고 오늘 장만의 특징을 LLM으로 몇 줄 정리한다.

    LLM 설정이 없거나 호출이 실패하면 빈 목록 — 리포트는 특징 없이도 보낸다.
    """
    from openai import OpenAI

    if not rising:
        return []
    with connection() as conn:
        ai = load_ai_config(conn)
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping daily features")
        return []

    client = OpenAI(base_url=ai['llm_api_base'], api_key=ai['llm_api_key'], timeout=FEATURES_TIMEOUT)
    try:
        completion = client.chat.completions.parse(
            model=ai['llm_model'],
            messages=[
                {"role": "system", "content": DAILY_FEATURES_PROMPT},
                {"role": "user", "content": features_prompt(rising, market_return)},
            ],
            response_format=DailyFeatures,
            temperature=0.3,
            max_tokens=FEATURES_MAX_TOKENS,
            # 숫자를 묶어 옮기는 짧은 글이라 추론을 끈다 — 켜 두면 추론만으로 토큰 한도를 넘긴다
            extra_body={'chat_template_kwargs': {'enable_thinking': False}},
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsable result")
    except Exception as e:
        log.warning(f"Daily features failed: {e}")
        return []
    features = [f.strip() for f in parsed.features if f.strip()]
    log.info(f"Daily features: {len(features)} items from {len(rising)} rising ETFs")
    return features


def format_daily_report(date_str: str, report: dict, threshold: float, new_etfs: list[dict]) -> tuple[str, list[str]]:
    """일일 리포트 → (디스코드 헤더, 블록들). 블록은 split_messages가 2,000자에 맞춰 묶는다."""
    blocks = []
    if new_etfs:
        blocks.append("신규 편입: " + ", ".join(f"{e['name']}({e['code']})" for e in new_etfs))

    rising = report['rising']
    if not rising:
        blocks.append(f"1일 {threshold:+.1f}% 이상 오른 ETF가 없습니다.")
        return f"📈 **ETF 일일 리포트** ({date_str})", blocks
    if report.get('features'):
        blocks.append("**오늘의 특징**\n" + "\n".join(f"• {f}" for f in report['features']))
    top = rising[:REPORT_TOP_RISING]
    title = f"**상승 ETF** (1일 {threshold:+.1f}% 이상 {len(rising)}개"
    title += f" 중 상위 {len(top)}개)" if len(top) < len(rising) else ")"
    blocks.append(title + "\n" + "\n".join(
        f"{i}. {etf['etf_name']} ({etf['etf_code']}) {etf['return_1d']:+.2f}%" for i, etf in enumerate(top, 1)))
    return f"📈 **ETF 일일 리포트** ({date_str})", blocks


def send_daily_report(date_str: str, new_etfs: list[dict] | None = None):
    """date_str(YYYY-MM-DD) 오늘의 특징과 상승 ETF를 디스코드로 보낸다. 알림이 꺼져 있거나 이미 보낸 날짜면 건너뛴다.

    발송에 실패하면 이력에 남기고 예외를 올려 Airflow 재시도가 다시 보내게 한다. 몇 개를 보낸 뒤 실패했으면
    재시도는 그때 남긴 리포트(이력의 items)로 같은 메시지를 다시 만들어 남은 것만 보낸다 — LLM 특징이 바뀌지 않게.
    """
    with connection() as conn:
        settings = load_discord_settings(conn)
        if not settings['enabled']:
            log.info("Discord notification disabled — skipping daily report")
            return
        webhook_url = settings['webhook_url']
        if not webhook_url:
            log.info("Discord webhook URL not set — skipping daily report")
            return
        if already_sent(conn, NOTICE_KIND, date_str):
            log.info(f"Daily report for {date_str} already sent — skipping")
            return
        interrupted = interrupted_send(conn, NOTICE_KIND, date_str)

    threshold = settings['rise_threshold']
    if interrupted:
        report = interrupted['items']
    else:
        report = collect_daily_report(date_str, threshold)
        report['features'] = summarize_rising_etfs(report['rising'], report['market_return'])
    header, blocks = format_daily_report(date_str, report, threshold, new_etfs or [])
    messages = split_messages(header, blocks)

    with connection() as conn:
        deliver(conn, webhook_url, NOTICE_KIND, date_str, threshold, report, messages,
                resume_start(interrupted, messages), failure="Discord daily report failed")
    log.info(f"Daily report sent: {len(report['rising'])} rising ETFs in {len(messages)} message(s)")
