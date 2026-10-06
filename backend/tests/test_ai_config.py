import asyncio

import pytest

from app.models.ai_setting import AISetting
from app.routers import admin
from app.schemas.chat import AISettingsUpdate
from app.services import ai_config
from app.utils import encryption


class FakeDB:
    def __init__(self, setting=None):
        self.setting = setting

    def get(self, model, id):
        return self.setting

    def add(self, obj):
        self.setting = obj

    def commit(self):
        pass


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setattr(encryption, "_aesgcm_instance", None)
    yield
    encryption._aesgcm_instance = None


@pytest.fixture
def env(monkeypatch):
    class Env:
        llm_api_base = "http://env-llm"
        llm_api_key = "env-key"
        llm_model = "env-model"
        embedding_api_base = "http://env-embed"
        embedding_api_key = "env-embed-key"
        embedding_model = "env-embed-model"
    monkeypatch.setattr(ai_config, "get_settings", lambda: Env)


def test_load_falls_back_to_env_without_row(env):
    config = ai_config.load_ai_config(FakeDB())
    assert config.llm_api_base == "http://env-llm" and config.embedding_api_key == "env-embed-key"


def test_load_prefers_stored_values_and_decrypts_keys(env):
    setting = AISetting(id=1, llm_api_base="http://db-llm", llm_api_key=encryption.encrypt_value("db-key"))
    config = ai_config.load_ai_config(FakeDB(setting))
    assert config.llm_api_base == "http://db-llm"
    assert config.llm_api_key == "db-key"
    assert config.llm_model == "env-model"  # 저장 안 한 항목은 환경변수


def test_load_ignores_undecryptable_key(env):
    setting = AISetting(id=1, llm_api_key="not-a-ciphertext")
    assert ai_config.load_ai_config(FakeDB(setting)).llm_api_key == "env-key"


def test_update_encrypts_keys_and_clears_with_empty_string(env):
    db = FakeDB(AISetting(id=1, llm_model="old-model"))
    body = AISettingsUpdate(llm_api_base=" https://new/llm/ ", llm_api_key="secret-1234", llm_model="")
    response = asyncio.run(admin.update_ai_settings(body, db=db, admin_id=1))

    assert db.setting.llm_api_base == "https://new/llm"
    assert db.setting.llm_api_key != "secret-1234"  # 평문으로 저장하지 않는다
    assert db.setting.llm_model is None  # "" → 환경변수로 되돌림
    assert response["llm_api_key"] == {"value": "…1234", "source": "db"}
    assert response["llm_model"] == {"value": "env-model", "source": "env"}
    assert response["embedding_api_key"] == {"value": "…-key", "source": "env"}


def test_update_rejects_non_http_base():
    with pytest.raises(ValueError):
        AISettingsUpdate(llm_api_base="ftp://x")
