"""
네이버 증권 모바일 API — ETF 프로필(보수율, 설명, 기초지수, 상장일) 조회

KIS/KRX Open API 모두 ETF 보수·설명 정보를 제공하지 않아 사용한다.
비공식 API(m.stock.naver.com)이므로 실패하면 해당 ETF만 비워 두고 수집은 계속한다.
"""

import html
import logging
import re
import time
from math import ceil
from typing import Optional

import requests

log = logging.getLogger(__name__)

ETF_ANALYSIS_URL = "https://m.stock.naver.com/api/stock/{code}/etfAnalysis"

_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
_SPACE_RE = re.compile(r'\s+')


def clean_summary(text: Optional[str]) -> Optional[str]:
    """etfSummary의 HTML 태그·엔티티를 걷어내고 공백을 한 칸으로 정리. 빈 값이면 None."""
    if not text:
        return None
    text = _TAG_RE.sub(' ', _BR_RE.sub(' ', text))
    text = _SPACE_RE.sub(' ', html.unescape(text)).strip()
    return text or None


def _format_listed_date(raw: Optional[str]) -> Optional[str]:
    """'20021014' → '2002-10-14'. 형식이 다르면 None."""
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return None


def fetch_etf_profile(code: str, session: Optional[requests.Session] = None) -> Optional[dict]:
    """ETF 프로필 조회. 조회 실패 시 None.

    반환 키(값이 없으면 키 생략):
      expense_ratio — 총보수(%), 소수 둘째 자리 올림
      description   — 운용사 상품 설명 원문 (HTML 정리)
      base_index    — 기초지수명
      listed_date   — 상장일 (YYYY-MM-DD)
    """
    http = session or requests
    try:
        resp = http.get(ETF_ANALYSIS_URL.format(code=code), timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"Failed to fetch ETF profile for {code}: {e}")
        return None

    profile = {}
    fee = data.get("totalFee")
    if fee is not None:
        try:
            profile["expense_ratio"] = ceil(float(fee) * 100) / 100
        except (TypeError, ValueError):
            pass
    summary = clean_summary(data.get("etfSummary"))
    if summary:
        profile["description"] = summary
    base_index = (data.get("etfBaseIndex") or "").strip()
    if base_index:
        profile["base_index"] = base_index
    listed_date = _format_listed_date(data.get("listedDate"))
    if listed_date:
        profile["listed_date"] = listed_date
    return profile


def fetch_etf_profiles(codes: list[str], interval: float = 0.1) -> dict[str, dict]:
    """여러 ETF의 프로필 조회. 실패한 코드는 결과에서 빠진다."""
    session = requests.Session()
    result = {}
    for code in codes:
        profile = fetch_etf_profile(code, session)
        if profile is not None:
            result[code] = profile
        time.sleep(interval)
    log.info(f"Loaded ETF profile for {len(result)}/{len(codes)} ETFs (naver)")
    return result
