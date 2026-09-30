"""
한국투자증권(KIS) Open API Client

ETF 구성종목시세[국내주식-073] API로 ETF의 현재 구성종목(PDF)을 조회합니다.
Endpoint: GET /uapi/etfetn/v1/quotations/inquire-component-stock-price (tr_id FHKST121600C0)

- 날짜 지정 파라미터가 없어 "호출 시점"의 구성종목만 조회 가능 (과거 백필 불가)
- 접근 토큰은 24시간 유효, 발급은 1분 1회 제한 → 토큰 캐시(kis_tokens 테이블) 사용
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"  # 실전투자


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
