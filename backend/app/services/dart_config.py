"""DART OpenAPI 키: 관리자 페이지에서 저장한 dart_settings가 우선, 비어 있으면 환경변수 DART_API_KEY."""
import logging

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.dart import DartSetting
from ..utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

DART_API_BASE = "https://opendart.fss.or.kr/api"
# 키 확인용으로 조회하는 회사 (삼성전자 고유번호)
TEST_CORP_CODE = "00126380"


def stored_key(setting: DartSetting | None) -> str | None:
    """DB에 저장된 키(복호화). 없거나 복호화에 실패하면 None — 환경변수로 돌아간다."""
    if setting is None or not setting.api_key:
        return None
    try:
        return decrypt_value(setting.api_key)
    except Exception:
        # ENCRYPTION_KEY가 바뀌었을 때 — 키 값은 남기지 않는다
        logger.warning("Failed to decrypt dart_settings.api_key; falling back to environment")
        return None


def load_dart_key(db: Session) -> str:
    return stored_key(db.get(DartSetting, 1)) or get_settings().dart_api_key


def check_dart_key(api_key: str) -> dict:
    """회사 개황 한 건을 실제로 조회한다. DART는 오류도 HTTP 200에 status 코드로 알린다."""
    if not api_key:
        return {"ok": False, "error": "DART API 키가 없습니다"}
    try:
        res = httpx.get(
            f"{DART_API_BASE}/company.json",
            params={"crtfc_key": api_key, "corp_code": TEST_CORP_CODE},
            timeout=15,
        )
        res.raise_for_status()
        body = res.json()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    if body.get("status") != "000":
        return {"ok": False, "error": f"{body.get('status')}: {body.get('message')}"}
    return {"ok": True, "error": None}
