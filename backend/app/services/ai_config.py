"""LLM/임베딩 접속 설정: 관리자 페이지에서 저장한 ai_settings가 우선, 비어 있는 항목은 환경변수."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.ai_setting import AISetting
from ..utils.ai_settings import AI_CONFIG_FIELDS, SECRET_FIELDS, resolve_ai_config
from ..utils.ai_settings import stored_value as _stored_value

__all__ = ["AIConfig", "AI_CONFIG_FIELDS", "SECRET_FIELDS", "load_ai_config", "stored_value"]


@dataclass(frozen=True)
class AIConfig:
    llm_api_base: str
    llm_api_key: str
    llm_model: str
    embedding_api_base: str
    embedding_api_key: str
    embedding_model: str


def _row(setting: AISetting | None) -> dict | None:
    return None if setting is None else {name: getattr(setting, name, None) for name in AI_CONFIG_FIELDS}


def stored_value(setting: AISetting | None, name: str) -> str | None:
    """DB에 저장된 값(키는 복호화). 없거나 복호화에 실패하면 None — 환경변수로 돌아간다."""
    return _stored_value(_row(setting), name)


def load_ai_config(db: Session) -> AIConfig:
    """요청마다 읽으므로 관리자 페이지에서 바꾸면 다음 요청부터 반영된다."""
    env = get_settings()
    return AIConfig(**resolve_ai_config(_row(db.get(AISetting, 1)), {name: getattr(env, name) for name in AI_CONFIG_FIELDS}))
