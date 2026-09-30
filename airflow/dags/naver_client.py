"""
네이버 증권 모바일 API — ETF 총보수(보수율) 조회

KIS/KRX Open API 모두 ETF 보수 정보를 제공하지 않아 사용한다.
비공식 API(m.stock.naver.com)이므로 실패하면 보수율만 비워 두고 수집은 계속한다.
"""

import logging
import time
from math import ceil
from typing import Optional

import requests

log = logging.getLogger(__name__)

ETF_ANALYSIS_URL = "https://m.stock.naver.com/api/stock/{code}/etfAnalysis"


def fetch_expense_ratio(code: str, session: Optional[requests.Session] = None) -> Optional[float]:
    """ETF 총보수(%)를 소수 둘째 자리 올림으로 반환. 조회 실패 시 None."""
    http = session or requests
    try:
        resp = http.get(ETF_ANALYSIS_URL.format(code=code), timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        fee = resp.json().get("totalFee")
        return ceil(float(fee) * 100) / 100 if fee is not None else None
    except Exception as e:
        log.warning(f"Failed to fetch expense ratio for {code}: {e}")
        return None


def fetch_expense_ratios(codes: list[str], interval: float = 0.1) -> dict[str, float]:
    """여러 ETF의 총보수 조회. 실패한 코드는 결과에서 빠진다."""
    session = requests.Session()
    result = {}
    for code in codes:
        fee = fetch_expense_ratio(code, session)
        if fee is not None:
            result[code] = fee
        time.sleep(interval)
    log.info(f"Loaded expense ratio for {len(result)}/{len(codes)} ETFs (naver)")
    return result
