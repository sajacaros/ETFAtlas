import asyncio

from pydantic import BaseModel, Field

from ....models.chat import ChatLogResult
from ...chat_service import ChatService
from ..tools import skill_tools
from .base import PROCESS_EVENTS, Skill, SkillContext, SkillResult, text_result


class AgentArgs(BaseModel):
    question: str = Field(description="에이전트에게 넘길 질문 (맥락 없이 읽히는 완전한 문장)")


class AgentSkill(Skill):
    """기존 tool-calling 에이전트(그래프 쿼리 포함)를 마크다운 슬롯 하나로 쓴다. 다른 스킬로 표현할 수 없는 질문을 받는다."""
    name = "agent"
    description = (
        "그래프 DB를 직접 조회하는 범용 에이전트(마크다운 답변). 다른 스킬로 표현할 수 없는 질문에: "
        "태그·테마·운용사별 ETF 목록, 유사 ETF, 보유종목 비중 변화, ETF 검색, 조건이 복잡한 그래프 질문, 범위 밖 질문"
    )
    Args = AgentArgs
    displays = ("markdown",)
    uses_llm = True

    async def run(self, args: AgentArgs, display: str, ctx: SkillContext):
        db = ctx.session_factory()
        try:
            # 이 답변의 스킬 중 tool인 것을 에이전트의 도구로 (화면 슬롯과 같은 계산)
            tools = skill_tools(ctx.registry, ctx.session_factory)
            service = await asyncio.to_thread(ChatService, db, ctx.ai_config, tools)
            answer, result = None, ChatLogResult.FAILED.value
            async for event in service.chat_stream(args.question, ctx.conversation, stop=ctx.stop):
                if event["type"] == "answer":
                    answer, result = event["data"]["answer"], event["data"]["result"]
                elif event["type"] in PROCESS_EVENTS:
                    yield event
            # 실패는 에이전트가 낸 결과 값으로 본다 (실패해도 안내 문구가 답으로 온다)
            yield (SkillResult(status="failed", message="답변을 만들지 못했습니다")
                   if result == ChatLogResult.FAILED.value or not answer
                   else text_result(answer, kind="markdown")).event()
        finally:
            db.close()
