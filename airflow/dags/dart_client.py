"""DART OpenAPI 클라이언트 (opendart.fss.or.kr) — 고유번호, 공시 목록, 다중회사 주요계정.

DART는 오류도 HTTP 200에 status 코드로 알린다: 000 정상, 013 데이터 없음, 020 요청 제한 초과.
일일 한도(키당 2만 건)가 넉넉해서 호출 간격만 둔다.
"""
import io
import logging
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator, Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
OK, NO_DATA, RATE_LIMITED = "000", "013", "020"
MIN_INTERVAL = 0.1
MAX_RETRIES = 3

# 보고서 코드: 1분기, 반기, 3분기, 사업보고서 (stock_financials.reprt_code)
REPORT_CODES = ("11013", "11012", "11014", "11011")
# 주요계정 중 저장하는 것. DART 계정명이 회사마다 '당기순이익(손실)'처럼 달라 앞부분으로 맞춘다
ACCOUNTS = ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계")
MULTI_ACCOUNT_BATCH = 100  # fnlttMultiAcnt가 한 번에 받는 회사 수


class DartError(Exception):
    pass


def parse_amount(raw: Optional[str]) -> Optional[int]:
    """'1,234' / '-1,234' / '' / '-' → 정수 또는 None. 결측을 0으로 바꾸지 않는다."""
    if raw is None:
        return None
    text = raw.replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_account(name: str) -> Optional[str]:
    name = (name or "").replace(" ", "")
    for account in ACCOUNTS:
        if name.startswith(account):
            return account
    return None


def parse_corp_codes(zip_bytes: bytes) -> list[dict]:
    """corpCode.xml(zip) → [{corp_code, corp_name, stock_code|None, modify_date}]."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml = zf.read(zf.namelist()[0])
    corps = []
    for item in ET.fromstring(xml).iter("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corps.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": stock_code or None,
            "modify_date": (item.findtext("modify_date") or "").strip() or None,
        })
    return [c for c in corps if c["corp_code"] and c["corp_name"]]


def parse_financial_rows(items: list[dict]) -> list[dict]:
    """fnlttMultiAcnt 응답 행 → stock_financials 행. 저장하지 않는 계정은 버린다.
    같은 키(회사·연도·보고서·연결/별도·계정)가 두 번 오면 앞의 것을 쓴다 (손익·재무상태표에 같은 이름이 걸릴 때)."""
    rows, seen = [], set()
    for item in items:
        account = normalize_account(item.get("account_nm", ""))
        stock_code = (item.get("stock_code") or "").strip()
        if not account or not stock_code:
            continue
        key = (stock_code, int(item["bsns_year"]), item["reprt_code"], item.get("fs_div"), account)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "stock_code": stock_code,
            "bsns_year": int(item["bsns_year"]),
            "reprt_code": item["reprt_code"],
            "fs_div": item.get("fs_div") or "",
            "account": account,
            "amount": parse_amount(item.get("thstrm_amount")),
            "amount_cum": parse_amount(item.get("thstrm_add_amount")),
            "rcept_no": item.get("rcept_no"),
        })
    return rows


class DartClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self._last = 0.0

    def _throttle(self):
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, path: str, params: dict, raw: bool = False):
        params = {"crtfc_key": self.api_key, **params}
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                res = self.session.get(f"{self.base_url}/{path}", params=params, timeout=30)
                res.raise_for_status()
            except requests.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    raise DartError(f"{path}: {e}") from e
                time.sleep(2 ** attempt)
                continue
            if raw:
                if not res.content.startswith(b"PK"):  # zip 대신 오류 XML/JSON이 왔다
                    raise DartError(f"{path}: {res.text[:200]}")
                return res.content
            body = res.json()
            status = body.get("status")
            if status == OK:
                return body
            if status == NO_DATA:
                return None
            if status == RATE_LIMITED and attempt < MAX_RETRIES - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise DartError(f"{path}: {status} {body.get('message')}")
        raise DartError(f"{path}: retries exhausted")

    def corp_codes(self) -> list[dict]:
        return parse_corp_codes(self._get("corpCode.xml", {}, raw=True))

    def disclosures(self, bgn_de: str, end_de: str, corp_code: Optional[str] = None) -> Iterator[dict]:
        """공시 목록. corp_code 없이 부르면 전체 회사 (기간 3개월 이내만 된다)."""
        page = 1
        while True:
            params = {"bgn_de": bgn_de, "end_de": end_de, "page_no": page, "page_count": 100}
            if corp_code:
                params["corp_code"] = corp_code
            body = self._get("list.json", params)
            if not body:
                return
            yield from body.get("list", [])
            if page >= int(body.get("total_page") or 1):
                return
            page += 1

    def document(self, rcept_no: str) -> bytes:
        """공시 원문 zip (document.xml). 정기보고서 색인(dart_report_index)이 보관한다."""
        return self._get("document.xml", {"rcept_no": rcept_no}, raw=True)

    def financials(self, corp_codes: list[str], bsns_year: int, reprt_code: str) -> list[dict]:
        """다중회사 주요계정 원본 행 (회사 100개까지)."""
        body = self._get("fnlttMultiAcnt.json", {
            "corp_code": ",".join(corp_codes), "bsns_year": str(bsns_year), "reprt_code": reprt_code,
        })
        return body.get("list", []) if body else []
