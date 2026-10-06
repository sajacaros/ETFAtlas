"""LLM/임베딩 접속 설정: 관리자 페이지에서 저장한 ai_settings가 우선, 비어 있는 항목은 환경변수."""
import logging
from dataclasses import dataclass, fields

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.ai_setting import AISetting
from ..utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

SECRET_FIELDS = ("llm_api_key", "embedding_api_key")


@dataclass(frozen=True)
class AIConfig:
    llm_api_base: str
    llm_api_key: str
    llm_model: str
    embedding_api_base: str
    embedding_api_key: str
    embedding_model: str


AI_CONFIG_FIELDS = tuple(f.name for f in fields(AIConfig))


def stored_value(setting: AISetting | None, name: str) -> str | None:
    """DB에 저장된 값(키는 복호화). 없거나 복호화에 실패하면 None — 환경변수로 돌아간다."""
    value = getattr(setting, name, None) if setting is not None else None
    if not value or name not in SECRET_FIELDS:
        return value or None
    try:
        return decrypt_value(value)
    except Exception:
        # ENCRYPTION_KEY가 바뀌었을 때 — 키 값은 남기지 않는다
        logger.warning("Failed to decrypt ai_settings.%s; falling back to environment", name)
        return None


def load_ai_config(db: Session) -> AIConfig:
    """요청마다 읽으므로 관리자 페이지에서 바꾸면 다음 요청부터 반영된다."""
    env = get_settings()
    setting = db.get(AISetting, 1)
    return AIConfig(**{name: stored_value(setting, name) or getattr(env, name) for name in AI_CONFIG_FIELDS})
