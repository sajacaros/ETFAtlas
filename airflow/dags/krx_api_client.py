"""
KRX Open API Client

ETF 일별매매정보 API를 통해 가격, NAV, 시가총액 등의 데이터를 조회합니다.
Endpoint: https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd
"""

import logging
import requests
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ETFDailyData:
    """ETF 일별 매매정보 데이터 클래스"""
    date: str              # 기준일자 (BAS_DD)
    code: str              # 종목코드 (ISU_CD)
    name: str              # 종목명 (ISU_NM)
    close_price: int       # 종가 (TDD_CLSPRC)
    open_price: int        # 시가 (TDD_OPNPRC)
    high_price: int        # 고가 (TDD_HGPRC)
    low_price: int         # 저가 (TDD_LWPRC)
    volume: int            # 거래량 (ACC_TRDVOL)
    trade_value: int       # 거래대금 (ACC_TRDVAL)
    nav: float             # 순자산가치 (NAV)
    market_cap: int        # 시가총액 (MKTCAP)
    net_assets: int        # 순자산총액 (INVSTASST_NETASST_TOTAMT)


class KRXApiClient:
    """KRX Open API 클라이언트"""

    BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"

    def __init__(self, auth_key: str):
        """
        Args:
            auth_key: KRX API 인증 키 (AUTH_KEY)
        """
        self.auth_key = auth_key
        self.session = requests.Session()
        self.session.headers.update({"AUTH_KEY": auth_key})

    def get_etf_daily_trading(self, date: str) -> list[ETFDailyData]:
        """
        ETF 일별매매정보 조회

        Args:
            date: 기준일자 (YYYYMMDD 형식)

        Returns:
            ETFDailyData 리스트

        Raises:
            requests.RequestException: API 호출 실패
            ValueError: 응답 파싱 실패
        """
        url = f"{self.BASE_URL}/etp/etf_bydd_trd"
        params = {"basDd": date}

        try:
            response = self.session.get(url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            if "OutBlock_1" not in data:
                log.warning(f"KRX API response has no OutBlock_1: {data}")
                return []

            results = []
            for item in data["OutBlock_1"]:
                try:
                    etf_data = self._parse_item(item)
                    if etf_data:
                        results.append(etf_data)
                except Exception as e:
                    log.warning(f"Failed to parse item {item.get('ISU_CD', 'unknown')}: {e}")
                    continue

            log.info(f"Retrieved {len(results)} ETF daily trading data from KRX API")
            return results

        except requests.RequestException as e:
            log.error(f"KRX API request failed: {e}")
            raise
        except Exception as e:
            log.error(f"Failed to process KRX API response: {e}")
            raise ValueError(f"Failed to process KRX API response: {e}")

    def _parse_item(self, item: dict) -> Optional[ETFDailyData]:
        """API 응답 아이템을 ETFDailyData로 변환"""
        code = item.get("ISU_CD", "")

        # 6자리 숫자 코드만 처리 (일부 ETF는 영문자 포함)
        if len(code) >= 6:
            ticker = code[:6]
            if not ticker.isdigit():
                return None
        else:
            return None

        return ETFDailyData(
            date=item.get("BAS_DD", ""),
            code=ticker,
            name=item.get("ISU_NM", ""),
            close_price=self._parse_int(item.get("TDD_CLSPRC")),
            open_price=self._parse_int(item.get("TDD_OPNPRC")),
            high_price=self._parse_int(item.get("TDD_HGPRC")),
            low_price=self._parse_int(item.get("TDD_LWPRC")),
            volume=self._parse_int(item.get("ACC_TRDVOL")),
            trade_value=self._parse_int(item.get("ACC_TRDVAL")),
            nav=self._parse_float(item.get("NAV")),
            market_cap=self._parse_int(item.get("MKTCAP")),
            net_assets=self._parse_int(item.get("INVSTASST_NETASST_TOTAMT")),
        )

    @staticmethod
    def _parse_int(value) -> int:
        """문자열을 정수로 변환 (쉼표, 하이픈 처리)"""
        if value is None or value == "" or value == "-":
            return 0
        try:
            return int(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_float(value) -> float:
        """문자열을 실수로 변환 (쉼표, 하이픈 처리)"""
        if value is None or value == "" or value == "-":
            return 0.0
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return 0.0
