"""ai_config: 관리자 페이지 값이 우선, 비면 환경변수(대문자 이름), 그것도 없으면 기본값."""
import ai_config
from fakes import FakeConn, FakeCursor


def test_env_names_and_defaults_are_kept():
    config = ai_config.env_ai_config({'LLM_MODEL': 'env-model', 'EMBEDDING_API_KEY': 'ek'})
    assert config == {
        'llm_api_base': 'http://localhost:4000', 'llm_api_key': '', 'llm_model': 'env-model',
        'embedding_api_base': 'http://localhost:4000', 'embedding_api_key': 'ek',
        'embedding_model': 'embedding-gemma-300m'}


def test_stored_values_win_and_blank_ones_fall_back(monkeypatch):
    monkeypatch.setenv('LLM_API_BASE', 'http://env/v1')
    monkeypatch.setenv('LLM_MODEL', 'env-model')
    row = ('', None, 'db-model', 'http://emb/v1', None, '')
    config = ai_config.load_ai_config(FakeConn(FakeCursor({"FROM ai_settings": [row]})))
    assert config['llm_api_base'] == 'http://env/v1' and config['llm_model'] == 'db-model'
    assert config['embedding_api_base'] == 'http://emb/v1' and config['embedding_model'] == 'embedding-gemma-300m'
    assert ai_config.load_ai_config(FakeConn(FakeCursor()))['llm_model'] == 'env-model'
