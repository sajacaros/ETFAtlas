"""스킬을 agent의 도구로: tool = True인 데이터 스킬은 agent(ChatService)도 같은 인자로 부른다.

새 스킬을 만들고 tool을 켜면 레이아웃 플래너와 agent 양쪽에서 쓰인다 — 같은 기능을 도구로 따로 만들지 않는다.
도구 결과는 슬롯과 같은 요약(summary)과 주석이라, 화면 슬롯과 agent 답이 같은 숫자를 읽는다.
도구마다 DB 세션을 따로 열므로 서로 병렬로 돈다 (공유 세션을 쓰는 기존 도구는 순차로 돈다).
"""
import json
from typing import Callable, Dict, List

from pydantic import ValidationError
from pydantic_ai import ModelRetry, Tool as AgentTool
from sqlalchemy.orm import Session

from ..entities import EntityResolver
from .skills.base import DataSkill, Skill, SkillResult

# 슬롯 인자 설명에는 앞 슬롯 결과의 참조('@이름.1')가 나오지만 도구에는 앞 슬롯이 없다
TOOL_NOTE = " (도구로 부를 때는 '@이름.순위' 참조를 쓸 수 없다 — 종목·ETF는 이름이나 6자리 코드로 적는다)"


def result_text(result: SkillResult) -> str:
    if result.status != "complete":
        return result.message or result.summary or "결과가 없습니다"
    notes = (result.content or {}).get("notes") or []
    return result.summary + ("\n주석: " + " / ".join(notes) if notes else "")


def skill_tool(skill: DataSkill, session_factory: Callable[[], Session], resolver: EntityResolver) -> AgentTool:
    def run(**kwargs) -> str:
        try:
            args = skill.Args.model_validate({k: v for k, v in kwargs.items() if v is not None})
        except ValidationError as e:  # 모델에게 돌려줘 인자를 고쳐 다시 부르게 한다
            raise ModelRetry(json.dumps(e.errors(include_url=False, include_context=False), ensure_ascii=False, default=str))
        return result_text(skill.execute(args, skill.displays[0], session_factory, resolver))

    return AgentTool.from_schema(
        run, name=skill.name, description=skill.description + TOOL_NOTE,
        json_schema=skill.Args.model_json_schema(), sequential=False,
    )


def skill_tools(registry: Dict[str, Skill], session_factory: Callable[[], Session]) -> List[AgentTool]:
    resolver = EntityResolver()  # 한 agent 실행 안에서 같은 이름을 같은 대상으로 읽는다
    return [skill_tool(s, session_factory, resolver) for s in registry.values() if s.tool and isinstance(s, DataSkill)]
