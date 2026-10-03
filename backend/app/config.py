from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/etf_atlas"

    # 로그인 세션 (HttpOnly 쿠키)
    session_expire_minutes: int = 60 * 24 * 7  # 7 days
    cookie_secure: bool = False  # https로 서비스하면 true

    # Encryption
    encryption_key: str = ""  # 32-byte hex key for AES-256-GCM

    # AI (LiteLLM 프록시, OpenAI 호환)
    llm_api_base: str = "http://localhost:4000"
    llm_api_key: str = ""
    llm_model: str = "qwen38-27b"
    # 챗봇 세션: 최근 N턴은 원문으로, 그 이전은 요약으로 기억
    chat_history_window: int = 5
    embedding_api_base: str = "http://localhost:4000"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-gemma-300m"  # 768차원

    # Frontend
    frontend_url: str = "http://localhost:9600"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
