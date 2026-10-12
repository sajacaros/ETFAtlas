"""레이아웃 에이전트: 질문을 보고 화면을 슬롯으로 나눈다. 출력 스키마와 스킬 설명은 레지스트리에서 만든다.

LLM에게는 재귀 트리 대신 '줄(row) 목록, 줄마다 슬롯 1~3개'라는 평평한 구조를 받는다 (작은 모델도 안정적으로 채운다).
프런트로 보내는 레이아웃은 column/row/slot 트리로 바꾼다.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, create_model, model_validator
from pydantic_ai import Agent

from ..ai_config import AIConfig
from ..chat_memory import ConversationContext
from .llm import NO_THINKING, build_model
from .refs import refs_in
from .schemas import slot_type
from .skills import FALLBACK_SKILL, REGISTRY
from .skills.base import Skill

logger = logging.getLogger(__name__)

MAX_ROWS = 6
MAX_SLOTS_PER_ROW = 3
MAX_SLOTS = 8

PLANNER_PROMPT = """당신은 ETF Atlas 챗봇의 화면 설계 담당입니다. 한국 ETF에 관한 사용자의 질문에 답할 화면을 영역(슬롯)으로 나눕니다.
각 슬롯은 아래 '스킬' 중 하나가 채웁니다. 데이터는 스킬이 DB에서 직접 가져오므로 숫자를 직접 쓰지 마세요.

규칙:
1. rows는 위에서 아래로 쌓이는 줄입니다. 한 줄에 슬롯 1~3개가 가로로 놓입니다. 전체 슬롯은 6개 이하로.
2. 질문에 필요한 슬롯만 만드세요. 단순한 질문은 슬롯 1~2개면 충분합니다. 같은 데이터를 표시 방식만 바꿔 두 번 넣지 마세요.
3. ETF·종목은 사용자가 말한 이름을 그대로 적거나 6자리 코드를 적으세요. 다른 대상으로 바꾸거나 추측하지 마세요.
   ETF 하나가 필요한데(구성종목·추이·수익률 등) '원익IPS가 들어간 ETF', '반도체 ETF'처럼 조건·테마만 있어 여러 ETF가 해당하면,
   ETF를 골라 넣거나 agent로 넘기지 말고 etf_choice 슬롯 하나로 되물으세요. ETF 목록 자체를 묻는 질문은 여기에 해당하지 않습니다.
   ETF(KODEX·TIGER 등 상품)와 개별 주식 종목(삼성전자 등)은 다른 스킬을 씁니다.
4. 데이터 슬롯을 만들었으면 마지막 줄에 narrative 슬롯 하나로 핵심을 해설하세요.
5. 스킬로 표현할 수 없는 질문은 agent 슬롯 하나만 쓰세요(이때 narrative는 붙이지 않습니다). 범위 밖 질문도 agent로 넘기세요.
6. display(표시 방식)는 반드시 적으세요. 사용자가 차트 종류(봉차트, 도넛, 트리맵 등)를 말했으면 그것을 쓰고,
   아니면 그 스킬이 지원하는 것 중에서 고르세요:
   추세는 line, 일별 가격 움직임(봉)은 candlestick, 기간·항목별 비교는 bar, 종목이 많은 구성은 treemap,
   몇 개 항목의 비중은 donut, 여러 지표의 종합 비교는 radar, 정확한 수치 확인은 table.
7. title은 영역 위에 표시할 짧은 제목입니다 (예: "3개월 수익률 추이").
8. 한 슬롯의 결과(예: 순위 1위 ETF)를 다른 슬롯의 대상으로 써야 하면, 결과를 내보내는 슬롯에 name(짧은 영문)을 붙이고
   다른 슬롯의 인자에 '@name.1'(1위), '@name.1-3'(1~3위, 목록 인자에서만)을 적으세요.
   예: 삼성전자를 가장 많이 담은 ETF와 그 구성종목 → stock_holders(name="rank") + holdings(etf="@rank.1").
   아직 모르는 대상을 '삼성전자 비중 1위 ETF' 같은 설명 문구로 적지 마세요. 내보내는 결과가 있는 스킬만 참조할 수 있습니다.
"""


@dataclass
class PlannedSlot:
    id: str
    skill: str
    title: str
    display: str
    args: BaseModel
    name: Optional[str] = None  # 다른 슬롯이 '@name.순위'로 참조할 때 쓰는 이름
    # 이 슬롯이 끝나야 실행할 수 있는 슬롯 id (참조한 슬롯). after_others 스킬의 '다른 슬롯 전부'는 오케스트레이터가 더한다
    depends_on: List[str] = field(default_factory=list)


def _step_model(skill: Skill) -> type[BaseModel]:
    return create_model(
        f"Slot_{skill.name}",
        skill=(Literal[skill.name], ...),
        name=(Optional[str], Field(None, description="다른 슬롯이 이 결과를 '@name.1'로 참조할 때만 붙이는 짧은 영문 이름")),
        title=(str, Field(description="영역 제목 (짧게)")),
        # 기본값을 두면 모델이 빠뜨린 채 넘어가 요청과 다른 차트가 나온다 — 반드시 고르게 한다
        display=(Literal[skill.displays], Field(description="표시 방식")),
        args=(skill.Args, ...),
    )


def build_plan_model(registry: Dict[str, Skill]) -> type[BaseModel]:
    steps = tuple(_step_model(s) for s in registry.values())
    Step = Annotated[Union[steps], Field(discriminator="skill")]
    Row = create_model("Row", slots=(List[Step], Field(min_length=1, max_length=MAX_SLOTS_PER_ROW)))

    def check_refs(plan):
        """참조 오류는 여기서 막는다 — 메시지가 플래너에게 그대로 돌아가 다시 쓰게 한다."""
        steps = [step for row in plan.rows for step in row.slots]
        named = {}
        for step in steps:
            if step.name:
                if step.name in named:
                    raise ValueError(f"슬롯 이름 '{step.name}'이 두 번 쓰였습니다")
                named[step.name] = step
        graph = {}
        for step in steps:
            refs = refs_in(step.args.model_dump())
            for ref in refs:
                target = named.get(ref)
                if target is None:
                    raise ValueError(f"'@{ref}' 참조: name이 '{ref}'인 슬롯이 없습니다")
                if target is step:
                    raise ValueError(f"슬롯 '{ref}'가 자기 자신을 참조합니다")
                if not registry[target.skill].exports:
                    raise ValueError(f"'@{ref}' 참조: {target.skill} 스킬은 참조할 결과를 내보내지 않습니다")
            graph[id(step)] = [id(named[r]) for r in refs]
        _check_cycles(graph)
        return plan

    return create_model(
        "LayoutPlan", rows=(List[Row], Field(min_length=1, max_length=MAX_ROWS)),
        __validators__={"check_refs": model_validator(mode="after")(check_refs)},
    )


def _check_cycles(graph: Dict[int, List[int]]) -> None:
    state: Dict[int, int] = {}  # 1: 방문 중, 2: 끝남

    def visit(node: int) -> None:
        if state.get(node) == 1:
            raise ValueError("슬롯들이 서로를 참조해 순환합니다")
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in graph.get(node, []):
            visit(nxt)
        state[node] = 2

    for node in graph:
        visit(node)


def skill_catalog(registry: Dict[str, Skill]) -> str:
    lines = ["## 스킬"]
    for s in registry.values():
        args = {k: v.get("description", v.get("type", "")) for k, v in s.Args.model_json_schema()["properties"].items()}
        lines.append(
            f"- {s.name}: {s.description}\n"
            f"  display: {', '.join(s.displays)} / args: {json.dumps(args, ensure_ascii=False)}"
            + (f"\n  내보내는 결과(참조 가능): {s.exports}" if s.exports else "")
        )
    return "\n".join(lines)


def to_rows(plan: BaseModel) -> List[List[PlannedSlot]]:
    """LLM 출력 → 슬롯 id를 붙인 줄 목록. 개수 상한을 넘는 슬롯은 버린다.
    참조('@name')는 그 슬롯의 id로 바꿔 depends_on에 담는다 (버려진 슬롯을 참조하면 그 id는 실행 때 결과가 없다)."""
    rows: List[List[PlannedSlot]] = []
    ids = {}
    count = 0
    for row in plan.rows:
        for step in row.slots:
            count += 1
            if step.name:
                ids[step.name] = f"s{count}"
    count = 0
    for row in plan.rows:
        slots = []
        for step in row.slots:
            if count >= MAX_SLOTS:
                break
            count += 1
            slots.append(PlannedSlot(
                id=f"s{count}", skill=step.skill, title=step.title, display=step.display, args=step.args,
                name=step.name, depends_on=sorted(ids[r] for r in refs_in(step.args.model_dump())),
            ))
        if slots:
            rows.append(slots)
    return rows


def fallback_rows(question: str) -> List[List[PlannedSlot]]:
    skill = REGISTRY[FALLBACK_SKILL]
    return [[PlannedSlot(id="s1", skill=skill.name, title="", display=skill.displays[0],
                         args=skill.Args(question=question))]]


def layout_tree(rows: List[List[PlannedSlot]]) -> Dict[str, Any]:
    def slot_node(s: PlannedSlot) -> Dict[str, Any]:
        return {"type": "slot", "id": s.id, "slot": slot_type(s.display), "display": s.display, "title": s.title}

    children = [slot_node(r[0]) if len(r) == 1 else {"type": "row", "children": [slot_node(s) for s in r]}
                for r in rows]
    return {"type": "column", "children": children}


class Planner:
    def __init__(self, config: AIConfig, registry: Dict[str, Skill] = REGISTRY):
        self._agent = Agent(
            build_model(config),
            output_type=build_plan_model(registry),
            instructions=f"{PLANNER_PROMPT}\n{skill_catalog(registry)}",
            model_settings=NO_THINKING,
            retries=2,
        )

    async def plan(self, question: str, context: ConversationContext) -> List[List[PlannedSlot]]:
        prompt = f"## 질문\n{question}"
        if not context.is_empty():
            prompt = f"## 이전 대화 (참고용)\n{context.render()}\n\n{prompt}"
        try:
            result = await self._agent.run(prompt)
            rows = to_rows(result.output)
        except Exception:
            logger.exception("Layout planning failed; falling back to the agent skill")
            return fallback_rows(question)
        return rows or fallback_rows(question)
