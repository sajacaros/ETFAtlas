import asyncio

from pydantic import BaseModel, Field

from .base import Skill, SkillContext, SkillResult, text_result


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
        from ...chat_service import FALLBACK_ANSWER, ChatService  # chat_service가 이 패키지를 가져오지 않도록 늦게 가져온다

        db = ctx.session_factory()
        try:
            service = await asyncio.to_thread(ChatService, db)
            answer = None
            async for event in service.chat_stream(args.question, ctx.conversation, stop=ctx.stop, refine=False):
                if event["type"] == "answer":
                    answer = event["data"]["answer"]
                elif event["type"] in ("step_start", "step", "matched_examples"):
                    yield event
            # 에이전트는 실패해도 안내 문구를 답으로 돌려주므로 그 경우를 실패로 본다
            yield (text_result(answer, kind="markdown") if answer and answer != FALLBACK_ANSWER
                   else SkillResult(status="failed", message="답변을 만들지 못했습니다")).event()
        finally:
            db.close()
