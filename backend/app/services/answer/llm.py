from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from ..ai_config import AIConfig

# 레이아웃 설계·요약은 추론 없이 빠르게 (ChatMemory의 보조 호출과 같은 설정)
NO_THINKING = ModelSettings(extra_body={"chat_template_kwargs": {"enable_thinking": False}})


def build_model(config: AIConfig) -> OpenAIChatModel:
    return OpenAIChatModel(
        config.llm_model,
        provider=OpenAIProvider(base_url=config.llm_api_base, api_key=config.llm_api_key),
    )
