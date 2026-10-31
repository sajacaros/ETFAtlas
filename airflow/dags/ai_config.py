"""
ai_config — LLM/임베딩 접속 설정 (관리자 페이지 ai_settings가 우선, 비어 있으면 환경변수)

해석 규칙(키 복호화 포함)은 backend의 app.utils.ai_settings를 쓴다. 환경변수 이름은 항목 이름의 대문자(LLM_API_BASE 등).
"""

import os
from typing import Mapping

from app.utils.ai_settings import AI_CONFIG_FIELDS, AI_DEFAULTS, resolve_ai_config


def env_ai_config(env: Mapping[str, str] = os.environ) -> dict:
    """환경변수(대문자 이름)에서 읽은 값, 없으면 기본값."""
    return {name: env.get(name.upper(), AI_DEFAULTS[name]) for name in AI_CONFIG_FIELDS}


def load_ai_config(conn) -> dict:
    """LLM/임베딩 접속 설정. 웹(관리자 페이지)에서 저장한 ai_settings가 우선,
    저장 전이거나 비어 있는 항목은 환경변수를 쓴다. API 키는 암호문이라 복호화한다."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(AI_CONFIG_FIELDS)} FROM ai_settings WHERE id = 1")
        row = cur.fetchone()
    return resolve_ai_config(dict(zip(AI_CONFIG_FIELDS, row)) if row else None, env_ai_config())
