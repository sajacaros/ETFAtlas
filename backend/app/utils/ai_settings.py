"""LLM/임베딩 접속 설정의 해석 규칙. backend와 airflow가 함께 쓰므로 DB·설정 모듈에 기대지 않는다."""
import logging
from typing import Any, Mapping, Optional

from .encryption import decrypt_value

logger = logging.getLogger(__name__)

# 환경변수(대문자 이름)도 없을 때의 값
AI_DEFAULTS = {
    "llm_api_base": "http://localhost:4000",
    "llm_api_key": "",
    "llm_model": "qwen38-27b",
    "embedding_api_base": "http://localhost:4000",
    "embedding_api_key": "",
    "embedding_model": "embedding-gemma-300m",  # 768차원
}
AI_CONFIG_FIELDS = tuple(AI_DEFAULTS)
SECRET_FIELDS = ("llm_api_key", "embedding_api_key")


def stored_value(row: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    """ai_settings 행에 저장된 값(키는 복호화). 없거나 복호화에 실패하면 None — 환경변수로 돌아간다."""
    value = row.get(name) if row else None
    if not value or name not in SECRET_FIELDS:
        return value or None
    try:
        return decrypt_value(value)
    except Exception:
        # ENCRYPTION_KEY가 바뀌었을 때 — 키 값은 남기지 않는다
        logger.warning("Failed to decrypt ai_settings.%s; falling back to environment", name)
        return None


def resolve_ai_config(row: Optional[Mapping[str, Any]], fallback: Mapping[str, str]) -> dict:
    """관리자 페이지에서 저장한 값이 우선, 비어 있는 항목은 fallback(환경변수에서 읽은 값)."""
    return {name: stored_value(row, name) or fallback[name] for name in AI_CONFIG_FIELDS}
