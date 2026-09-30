from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/etf_atlas"

    # JWT
    jwt_secret: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Encryption
    encryption_key: str = ""  # 32-byte hex key for AES-256-GCM

    # AI (LiteLLM 프록시, OpenAI 호환)
    llm_api_base: str = "http://localhost:4000"
    llm_api_key: str = ""
    llm_model: str = "qwen38-27b"
    embedding_model: str = "embedding-gemma-300m"  # 768차원

    # Frontend
    frontend_url: str = "http://localhost:9600"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
