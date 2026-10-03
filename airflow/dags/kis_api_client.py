"""
한국투자증권(KIS) Open API Client (시세 조회 전용)

- ETF 구성종목시세[국내주식-073] (FHKST121600C0): ETF 현재 구성종목(PDF)
  날짜 지정 파라미터가 없어 "호출 시점"의 구성종목만 조회 가능 (과거 백필 불가)
- 국내주식기간별시세[v1_국내주식-016] (FHKST03010100): 종목/ETF 일봉 (호출당 최대 100건)
- 국내휴장일조회 (CTCA0903R): 개장일 여부 (KIS 요청: 가급적 1일 1회 호출)
- ETF/ETN 현재가[v1_국내주식-068] (FHPST02400000): NAV, 순자산총액, 상장주수 (현재 시점)
- 종목 마스터 파일(kospi_code.mst, 인증 불필요): 전체 ETF 코드/이름 목록

접근 토큰은 24시간 유효, 발급은 1분 1회 제한 → 토큰 캐시(kis_tokens 테이블) 사용
"""

import hashlib
import io
import logging
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"  # 실전투자
KOSPI_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
MASTER_TAIL_LEN = 227   # 행 끝 고정폭 영역(그룹코드부터) 길이 — 공식 샘플 kis_kospi_code_mst.py 기준
ETF_GROUP_CODE = "EF"


def fetch_etf_master(session: Optional[requests.Session] = None) -> list[tuple[str, str]]:
    """KIS 종목 마스터 파일에서 ETF(그룹코드 EF) (단축코드, 한글명) 목록을 반환한다. 인증 불필요."""
    http = session or requests
    resp = http.get(KOSPI_MASTER_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        text = zf.read(zf.namelist()[0]).decode("cp949")
    etfs = []
    for row in text.splitlines():
        if len(row) <= MASTER_TAIL_LEN:
            continue
        head, tail = row[:-MASTER_TAIL_LEN], row[-MASTER_TAIL_LEN:]
        if tail[:2] != ETF_GROUP_CODE:
            continue
        code, name = head[0:9].strip(), head[21:].strip()
        if code and name:
            etfs.append((code, name))
    return etfs


@dataclass
class ETFComponent:
    """ETF 구성종목 데이터 클래스 (output2 한 행)"""
    stock_code: str     # 주식 단축 종목코드 (stck_shrn_iscd)
    stock_name: str     # HTS 한글 종목명 (hts_kor_isnm)
    weight: float       # ETF 구성종목 비중 % (etf_cnfg_issu_rlim)
    value: int          # ETF 구성종목 내 평가금액 (etf_vltn_amt)
    price: int          # 주식 현재가 (stck_prpr)

    @property
    def shares(self) -> int:
        """구성 수량 추정치 (평가금액 / 현재가). API에 수량 필드가 없어 역산."""
        return round(self.value / self.price) if self.price > 0 else 0


@dataclass
class DailyBar:
    """일봉 데이터 (output2 한 행)"""
    date: str           # 영업일자 YYYYMMDD (stck_bsop_date)
    open: int           # 시가 (stck_oprc)
    high: int           # 고가 (stck_hgpr)
    low: int            # 저가 (stck_lwpr)
    close: int          # 종가 (stck_clpr)
    volume: int         # 누적 거래량 (acml_vol)
    change_rate: float  # 전일 대비율 % (prdy_vrss로 계산)
    trade_value: int = 0  # 누적 거래대금 (acml_tr_pbmn)


@dataclass
class ETFSnapshot:
    """ETF/ETN 현재가 (호출 시점 값)"""
    code: str
    price: int          # 현재가 (stck_prpr)
    nav: float          # NAV (nav, 없으면 prdy_last_nav)
    net_assets: int     # 순자산총액 원 단위 (etf_ntas_ttam, 단위 정규화)
    listed_shares: int  # 상장주수 (lstn_stcn)
    dividend_cycle: Optional[int] = None  # 분배 주기 개월 수 (etf_dvdn_cycl: 1=월, 3=분기), 미제공 None

    @property
    def market_cap(self) -> int:
        return self.price * self.listed_shares


class TokenCache(Protocol):
    def load(self, key: str) -> Optional[tuple[str, datetime]]: ...
    def save(self, key: str, token: str, expires_at: datetime) -> None: ...


class PostgresTokenCache:
    """kis_tokens 테이블 기반 토큰 캐시 (여러 태스크/프로세스가 공유)"""

    def __init__(self, conn_factory: Callable):
        self._conn_factory = conn_factory

    def load(self, key: str) -> Optional[tuple[str, datetime]]:
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token, expires_at FROM kis_tokens WHERE app_key_hash = %s",
                    (key,),
                )
                row = cur.fetchone()
                return (row[0], row[1]) if row else None
        finally:
            conn.close()

    def save(self, key: str, token: str, expires_at: datetime) -> None:
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kis_tokens (app_key_hash, access_token, expires_at, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (app_key_hash) DO UPDATE
                    SET access_token = EXCLUDED.access_token,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (key, token, expires_at),
                )
            conn.commit()
        finally:
            conn.close()


class KISApiError(Exception):
    def __init__(self, msg_cd: str, msg: str):
        super().__init__(f"[{msg_cd}] {msg}")
        self.msg_cd = msg_cd


class KISApiClient:
    """KIS Open API 클라이언트 (시세 조회 전용)"""

    TOKEN_MARGIN = timedelta(minutes=10)   # 만료 10분 전이면 재발급
    MIN_INTERVAL = 0.06                    # 초당 호출 제한(실전 20건/s) 대비 최소 간격
    RATE_LIMIT_CODE = "EGW00201"           # 초당 거래건수 초과
    TOKEN_EXPIRED_CODE = "EGW00123"        # 기간이 만료된 token

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = DEFAULT_BASE_URL,
        token_cache: Optional[TokenCache] = None,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self.token_cache = token_cache
        self.session = requests.Session()
        self._cache_key = hashlib.sha256(app_key.encode()).hexdigest()
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._lock = threading.Lock()
        self._last_call = 0.0

    # ── 토큰 ──

    def _get_token(self) -> str:
        now = datetime.now()
        if self._token and self._token_expires_at and self._token_expires_at - now > self.TOKEN_MARGIN:
            return self._token

        if self.token_cache:
            cached = self.token_cache.load(self._cache_key)
            if cached and cached[1] - now > self.TOKEN_MARGIN:
                self._token, self._token_expires_at = cached
                return self._token

        self._issue_token()
        return self._token

    def _issue_token(self) -> None:
        resp = self.session.post(
            f"{self.base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expired = data.get("access_token_token_expired")  # 'YYYY-MM-DD HH:MM:SS' (KST)
        expires_at = (
            datetime.strptime(expired, "%Y-%m-%d %H:%M:%S")
            if expired
            else datetime.now() + timedelta(seconds=int(data.get("expires_in", 86400)))
        )
        self._token, self._token_expires_at = token, expires_at
        if self.token_cache:
            self.token_cache.save(self._cache_key, token, expires_at)
        log.info(f"KIS access token issued (expires {expires_at})")

    # ── 호출 ──

    def _throttle(self) -> None:
        with self._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _get(self, path: str, tr_id: str, params: dict, retries: int = 3) -> dict:
        token_refreshed = False
        for attempt in range(retries + 1):
            self._throttle()
            resp = self.session.get(
                f"{self.base_url}{path}",
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {self._get_token()}",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret,
                    "tr_id": tr_id,
                    "custtype": "P",
                },
                params=params,
                timeout=30,
            )
            try:
                data = resp.json()
            except ValueError:
                resp.raise_for_status()
                raise

            if data.get("rt_cd") == "0":
                return data

            msg_cd = data.get("msg_cd", "")
            if msg_cd == self.RATE_LIMIT_CODE and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            if msg_cd == self.TOKEN_EXPIRED_CODE and not token_refreshed:
                self._issue_token()
                token_refreshed = True
                continue
            raise KISApiError(msg_cd, data.get("msg1", resp.text[:200]))
        raise KISApiError(self.RATE_LIMIT_CODE, "rate limit retries exhausted")

    def get_etf_components(self, etf_code: str) -> list[ETFComponent]:
        """ETF 구성종목시세 조회 (호출 시점 기준)

        Args:
            etf_code: ETF 단축 종목코드 (예: '069500')

        Returns:
            ETFComponent 리스트 (API 응답 순서)
        """
        data = self._get(
            "/uapi/etfetn/v1/quotations/inquire-component-stock-price",
            tr_id="FHKST121600C0",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": etf_code,
                "FID_COND_SCR_DIV_CODE": "11216",
            },
        )
        components = []
        for item in data.get("output2") or []:
            code = (item.get("stck_shrn_iscd") or "").strip()
            if not code:
                continue
            components.append(ETFComponent(
                stock_code=code,
                stock_name=(item.get("hts_kor_isnm") or "").strip(),
                weight=self._parse_float(item.get("etf_cnfg_issu_rlim")),
                value=self._parse_int(item.get("etf_vltn_amt")),
                price=self._parse_int(item.get("stck_prpr")),
            ))
        return components

    def get_daily_bars(self, code: str, start: str, end: str) -> list[DailyBar]:
        """기간별 일봉 조회 (수정주가). start~end(YYYYMMDD) 전체를 100건씩 나눠 조회.

        Returns:
            날짜 오름차순 DailyBar 리스트
        """
        bars: dict[str, DailyBar] = {}
        cursor_end = end
        while cursor_end >= start:
            data = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                tr_id="FHKST03010100",
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": start,
                    "FID_INPUT_DATE_2": cursor_end,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "0",
                },
            )
            rows = [r for r in (data.get("output2") or []) if r.get("stck_bsop_date")]
            if not rows:
                break
            for r in rows:
                bar = self._parse_bar(r)
                if start <= bar.date <= end:
                    bars[bar.date] = bar
            oldest = min(r["stck_bsop_date"] for r in rows)
            if len(rows) < 100 or oldest <= start:
                break
            cursor_end = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        return [bars[d] for d in sorted(bars)]

    def _parse_bar(self, r: dict) -> DailyBar:
        close = self._parse_int(r.get("stck_clpr"))
        diff = self._parse_int(r.get("prdy_vrss"))
        # 부호 코드 4(하한)/5(하락)인데 값이 양수로 오면 음수로 보정
        if r.get("prdy_vrss_sign") in ("4", "5") and diff > 0:
            diff = -diff
        prev = close - diff
        return DailyBar(
            date=r["stck_bsop_date"],
            open=self._parse_int(r.get("stck_oprc")),
            high=self._parse_int(r.get("stck_hgpr")),
            low=self._parse_int(r.get("stck_lwpr")),
            close=close,
            volume=self._parse_int(r.get("acml_vol")),
            change_rate=round(diff / prev * 100, 2) if prev > 0 else 0.0,
            trade_value=self._parse_int(r.get("acml_tr_pbmn")),
        )

    # 순자산총액이 이 값보다 작으면 억원 단위로 간주 (1억원 미만 ETF는 없음)
    NET_ASSETS_EOK_THRESHOLD = 100_000_000

    def get_etf_snapshot(self, code: str) -> ETFSnapshot:
        """ETF/ETN 현재가 조회 — NAV/순자산/상장주수 (호출 시점)."""
        data = self._get(
            "/uapi/etfetn/v1/quotations/inquire-price",
            tr_id="FHPST02400000",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        out = data.get("output") or {}
        net_assets = self._parse_int(out.get("etf_ntas_ttam"))
        if 0 < net_assets < self.NET_ASSETS_EOK_THRESHOLD:
            net_assets *= 100_000_000  # 억원 → 원
        nav = self._parse_float(out.get("nav")) or self._parse_float(out.get("prdy_last_nav"))
        return ETFSnapshot(
            code=code,
            price=self._parse_int(out.get("stck_prpr")),
            nav=nav,
            net_assets=net_assets,
            listed_shares=self._parse_int(out.get("lstn_stcn")),
            dividend_cycle=self._parse_int(out.get("etf_dvdn_cycl")) or None,
        )

    def is_market_open(self, date: str) -> Optional[bool]:
        """국내휴장일조회로 date(YYYYMMDD)의 개장일 여부 반환. 응답에 해당 날짜가 없으면 None.

        KIS 요청에 따라 호출 측에서 하루 1회로 캐시해 사용할 것.
        """
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/chk-holiday",
            tr_id="CTCA0903R",
            params={"BASS_DT": date, "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        )
        for item in data.get("output") or []:
            if item.get("bass_dt") == date:
                return item.get("opnd_yn") == "Y"
        return None

    @staticmethod
    def _parse_int(value) -> int:
        if value is None or value == "" or value == "-":
            return 0
        try:
            return int(float(str(value).replace(",", "")))
        except ValueError:
            return 0

    @staticmethod
    def _parse_float(value) -> float:
        if value is None or value == "" or value == "-":
            return 0.0
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return 0.0


if __name__ == "__main__":
    # 스모크 테스트: KIS_APP_KEY=... KIS_APP_SECRET=... python kis_api_client.py 069500
    import os
    import sys

    logging.basicConfig(level=logging.INFO)
    client = KISApiClient(
        os.environ["KIS_APP_KEY"],
        os.environ["KIS_APP_SECRET"],
        os.environ.get("KIS_BASE_URL", DEFAULT_BASE_URL),
    )
    for c in client.get_etf_components(sys.argv[1] if len(sys.argv) > 1 else "069500")[:15]:
        print(f"{c.stock_code} {c.stock_name:<20} weight={c.weight:6.2f}% value={c.value:>15,} "
              f"price={c.price:>10,} shares~{c.shares:,}")
