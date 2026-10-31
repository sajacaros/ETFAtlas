"""LLM 접속을 한곳에서: 모델·클라이언트 생성, 추론 끄기, 타임아웃, 흘려받은 텍스트 모으기.

모델과 클라이언트는 접속 설정(AIConfig)을 키로 캐시한다. 관리자 페이지에서 설정을 바꾸면
요청마다 읽는 설정값이 달라져 새 키로 만들어지므로, 다음 요청부터 반영되는 동작은 그대로다.
"""
import asyncio
from functools import lru_cache
from typing import AsyncIterator, Optional

from openai import OpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from .ai_config import AIConfig

# 요청 하나의 한도(초). 흘려받을 때는 조각 사이의 간격에 걸린다. 관리자 연결 확인(admin)은 따로 20초로 짧게 본다
LLM_TIMEOUT = 120
CACHED_CONFIGS = 8  # 설정이 바뀌어도 예전 설정의 모델이 쌓이지 않게

# 채팅마다 부르는 보조 단계(레이아웃 설계·요약·질문 재작성·일반화 등)는 추론 없이 빠르게
NO_THINKING_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
NO_THINKING = ModelSettings(extra_body=NO_THINKING_BODY)


@lru_cache(maxsize=CACHED_CONFIGS)
def build_model(config: AIConfig) -> OpenAIChatModel:
    return OpenAIChatModel(
        config.llm_model,
        provider=OpenAIProvider(base_url=config.llm_api_base, api_key=config.llm_api_key),
        settings=ModelSettings(timeout=LLM_TIMEOUT),
    )


@lru_cache(maxsize=CACHED_CONFIGS)
def openai_client(base_url: str, api_key: str) -> OpenAI:
    """동기 OpenAI 호환 클라이언트 (스레드에서 부르는 질문 재작성·일반화·임베딩)."""
    return OpenAI(base_url=base_url, api_key=api_key, timeout=LLM_TIMEOUT)


def complete(client: OpenAI, model: str, system: str, user: str, max_tokens: int) -> str:
    """추론 없이 한 번 묻고 답 텍스트만 (앞뒤 공백 제거, 비었으면 '')."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
        max_tokens=max_tokens,
        extra_body=NO_THINKING_BODY,
    )
    return (resp.choices[0].message.content or "").strip()


async def stream_text(model, instructions: str, prompt: str,
                      stop: Optional[asyncio.Event] = None) -> AsyncIterator[str]:
    """LLM 답을 조각으로 흘려보낸다 (추론 없이). stop이 켜지면 그 조각까지만 보내고 멈춘다."""
    agent = Agent(model, instructions=instructions, model_settings=NO_THINKING)
    async with agent.run_stream(prompt) as result:
        async for delta in result.stream_text(delta=True):
            yield delta
            if stop is not None and stop.is_set():
                break
