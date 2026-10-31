"""DART OpenAPI 클라이언트 (opendart.fss.or.kr) — 고유번호, 공시 목록, 다중회사 주요계정, 단일회사 현금흐름.

DART는 오류도 HTTP 200에 status 코드로 알린다: 000 정상, 013 데이터 없음, 020 요청 제한 초과.
일일 한도(키당 2만 건)가 넉넉해서 호출 간격만 둔다.
"""
import io
import json
import logging
import re
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
# 현금흐름표(fnlttSinglAcntAll의 sj_div=CF)에서 저장하는 계정: 저장 이름 → (IFRS 계정 id, 그 id가 없을 때 맞출 계정명,
# 그것도 없을 때 더할 세부 항목). 회사마다 표준 id를 안 쓰거나(이름만), 설비투자를 토지·건물·기계장치처럼 나눠 적는다
# (세부 항목 id나 이름의 합). 취득은 회사에 따라 부호가 양수·음수로 온다
PPE_PARTS = ("토지", "건물", "구축물", "기계장치", "차량운반구", "건설중인자산", "기타유형자산", "공기구비품", "비품", "공구와기구")
CASH_FLOW_ACCOUNTS = {
    "영업활동현금흐름": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",
                       ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로인한순현금흐름"), ()),
    "유형자산의취득": ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                     ("유형자산의취득", "유형자산및투자부동산의취득", "투자부동산및유형자산의취득"), PPE_PARTS),
    "무형자산의취득": ("ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities", ("무형자산의취득",), ()),
}
ANNUAL, Q1 = "11011", "11013"


RETRY_HTTP_STATUS = 429  # 그 밖의 4xx(키·요청 오류)는 다시 보내도 같다
_STATUS_RE = re.compile(rb"<status>\s*(\w+)\s*</status>")


class DartError(Exception):
    """status: DART 상태 코드(예: '014' 파일 없음, 오류 본문에서 읽었을 때), http_status: HTTP 상태 코드(HTTP 오류일 때)."""

    def __init__(self, message: str, status: Optional[str] = None, http_status: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def error_status(body: bytes) -> Optional[str]:
    """zip 대신 온 오류 본문(XML 또는 JSON)의 DART 상태 코드."""
    match = _STATUS_RE.search(body)
    if match:
        return match.group(1).decode()
    try:
        status = json.loads(body).get("status")
    except (ValueError, AttributeError):
        return None
    return str(status) if status is not None else None


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


def parse_cash_flow_rows(items: list[dict], stock_code: str, bsns_year: int, reprt_code: str, fs_div: str,
                         rcept_no: str) -> list[dict]:
    """fnlttSinglAcntAll 응답 → 현금흐름 계정의 stock_financials 행. 찾지 못한 계정도 금액 없이 한 행씩 남긴다
    (받아 본 보고서라는 표시 — 다음 실행에서 다시 부르지 않는다).
    현금흐름표는 분·반기 보고서도 연초부터의 누적만 준다: 1분기는 3개월 = 누적이라 둘 다, 반기·3분기는 누적에만,
    사업보고서는 연간 금액에 넣는다 (주요계정과 같은 뜻 — amount는 3개월·연간, amount_cum은 누적)."""
    cf = [{**i, "name": (i.get("account_nm") or "").replace(" ", "")} for i in items if i.get("sj_div") == "CF"]
    rows = []
    for account, (account_id, names, parts) in CASH_FLOW_ACCOUNTS.items():
        item = next((i for i in cf if i.get("account_id") == account_id), None) or next(
            (i for i in cf if i["name"].startswith(names)), None)
        if item:
            value = parse_amount(item.get("thstrm_amount"))
        else:
            found = [parse_amount(i.get("thstrm_amount")) for i in cf
                     if i["name"] in tuple(f"{p}의취득" for p in parts)]
            found = [v for v in found if v is not None]
            value = sum(found) if found else None
        rows.append({
            "stock_code": stock_code, "bsns_year": bsns_year, "reprt_code": reprt_code, "fs_div": fs_div,
            "account": account,
            "amount": value if reprt_code in (ANNUAL, Q1) else None,
            "amount_cum": value if reprt_code != ANNUAL else None,
            "rcept_no": rcept_no,
        })
    return rows


def cash_flow_targets(reports, done, year: int, quarter_years: int, limit: int) -> list[tuple]:
    """현금흐름을 받을 보고서 (stock_code, bsns_year, reprt_code, fs_div, rcept_no), 최근 보고서부터 limit개.
    reports: 주요계정이 있는 보고서들, done: 현금흐름을 이미 받은 보고서들 (같은 모양).
    분·반기 보고서는 최근 quarter_years개 사업연도만. 한 보고서에 연결·별도가 다 있으면 연결만 (챗봇이 연결을 쓴다) —
    사업보고서는 별도도 받는다: 금융 자회사의 대출 증감이 연결 영업현금흐름을 음수로 만드는 회사를 가려내는 대조용.
    접수번호가 바뀌면(정정) 다시 받는다. 같은 보고서면 연결을 먼저."""
    consolidated = {r[:3] for r in reports if r[3] == "CFS"}
    picked = [r for r in reports if r[3] == "CFS" or r[:3] not in consolidated or r[2] == ANNUAL]
    order = {code: i for i, code in enumerate(REPORT_CODES)}
    targets = [r for r in dict.fromkeys(picked) if r not in done
               and (r[2] == ANNUAL or r[1] > year - quarter_years)]
    targets.sort(key=lambda r: (r[1], order[r[2]], r[3] == "CFS"), reverse=True)
    return targets[:limit]


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
            last = attempt == MAX_RETRIES - 1
            self._throttle()
            # 예외 메시지엔 요청 주소(키 포함)가 들어가므로 종류·상태코드만 남긴다
            try:
                res = self.session.get(f"{self.base_url}/{path}", params=params, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as e:
                if last:
                    raise DartError(f"{path}: {type(e).__name__}") from None
                time.sleep(2 ** attempt)
                continue
            except requests.RequestException as e:
                raise DartError(f"{path}: {type(e).__name__}") from None
            if (res.status_code >= 500 or res.status_code == RETRY_HTTP_STATUS) and not last:
                time.sleep(2 ** attempt)
                continue
            if res.status_code >= 400:
                raise DartError(f"{path}: HTTP {res.status_code}", http_status=res.status_code)
            if raw:
                if not res.content.startswith(b"PK"):  # zip 대신 오류 XML/JSON이 왔다
                    raise DartError(f"{path}: {res.text[:200]}", status=error_status(res.content))
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
            raise DartError(f"{path}: {status} {body.get('message')}", status=status)
        raise DartError(f"{path}: retries exhausted", status=RATE_LIMITED)

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

    def statements(self, corp_code: str, bsns_year: int, reprt_code: str, fs_div: str) -> list[dict]:
        """단일회사 전체 재무제표 원본 행 (재무상태표·손익·현금흐름 등, 회사 하나·보고서 하나에 한 번)."""
        body = self._get("fnlttSinglAcntAll.json", {
            "corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code, "fs_div": fs_div,
        })
        return body.get("list", []) if body else []
