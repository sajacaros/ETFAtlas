"""레이아웃 에이전트: 질문을 보고 화면을 슬롯으로 나눈다. 출력 스키마와 스킬 설명은 레지스트리에서 만든다.

LLM에게는 재귀 트리 대신 '줄(row) 목록, 줄마다 슬롯 1~3개'라는 평평한 구조를 받는다 (작은 모델도 안정적으로 채운다).
프런트로 보내는 레이아웃은 column/row/slot 트리로 바꾼다.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError, create_model, model_validator
from pydantic_ai import Agent, ModelRetry
from sqlalchemy.orm import Session

from ..ai_config import AIConfig
from ..chat_memory import ConversationContext
from ..embedding_service import EmbeddingService
from .llm import NO_THINKING, build_model
from .resolver import is_etf_name
from .refs import RefError, expanded, rank_gaps, refs_in, split_hint
from .schemas import slot_type
from .skills import FALLBACK_SKILL, REGISTRY
from .skills.base import Skill

logger = logging.getLogger(__name__)

MAX_ROWS = 6
MAX_SLOTS_PER_ROW = 3
MAX_SLOTS = 8

# 규칙은 스킬·종목 이름에 기대지 않고 원리만 적는다. 질문 유형별 구체적인 설계는 레이아웃 예시(layout_examples)가 맡는다 —
# 여기에 특정 사례를 넣으면 모든 질문이 그 사례 쪽으로 끌려간다. 스킬별 용도는 스킬 설명(skill_catalog)에 있다.
PLANNER_PROMPT = f"""당신은 ETF Atlas 챗봇의 화면 설계 담당입니다. 한국 ETF에 관한 사용자의 질문에 답할 화면을 영역(슬롯)으로 나눕니다.
각 슬롯은 아래 '스킬' 중 하나가 채웁니다. 데이터는 스킬이 DB에서 직접 가져오므로 숫자를 직접 쓰지 마세요.

규칙:
1. rows는 위에서 아래로 쌓이는 줄입니다. 한 줄에 슬롯 1~{MAX_SLOTS_PER_ROW}개가 가로로 놓입니다. 전체 슬롯은 {MAX_SLOTS}개 이하로.
2. 질문에 필요한 슬롯만 만드세요. 단순한 질문은 슬롯 1~2개면 충분합니다. 같은 데이터를 표시 방식만 바꿔 두 번 넣지 마세요.
3. ETF·종목은 사용자가 말한 이름을 그대로 적거나 6자리 코드를 적으세요. 다른 대상으로 바꾸거나 추측하지 마세요.
   ETF(운용사 브랜드가 붙은 상품)와 개별 주식 종목은 다른 스킬을 씁니다.
   상품 이름이 주어졌으면 대소문자·띄어쓰기가 달라도 그 이름을 그대로 데이터 스킬에 적으세요 —
   이름이 여러 ETF에 걸리면 데이터 스킬이 알아서 되묻습니다.
   대상 하나가 필요한데 이름 없이 조건·테마로만 주어져 여럿이 해당하면, 하나를 골라 넣지 말고 되묻는 스킬을 쓰세요.
4. 데이터 슬롯을 만들었으면 마지막 줄에 narrative 슬롯 하나로 핵심을 해설하세요.
5. 스킬로 표현할 수 없는 질문은 agent 슬롯 하나만 쓰세요(이때 narrative는 붙이지 않습니다). 범위 밖 질문도 agent로 넘기세요.
6. display(표시 방식)는 반드시 적으세요. 사용자가 차트 종류(봉차트, 도넛, 트리맵 등)를 말했으면 그것을 쓰고,
   아니면 그 스킬이 지원하는 것 중에서 고르세요:
   추세는 line, 일별 가격 움직임(봉)은 candlestick, 기간·항목별 비교는 bar, 종목이 많은 구성은 treemap,
   몇 개 항목의 비중은 donut, 여러 지표의 종합 비교는 radar, 정확한 수치 확인은 table.
7. title은 영역 위에 표시할 짧은 제목입니다.
8. 한 슬롯의 결과(순위가 있는 ETF·종목 목록)를 다른 슬롯의 대상으로 써야 하면, 결과를 내보내는 슬롯에 name(짧은 영문)을 붙이고
   다른 슬롯의 인자에 '@name.1'(1위), '@name.1-3'(1~3위, 목록 인자에서만)을 적으세요.
   아직 모르는 대상을 설명 문구('…1위 ETF')로 적지 마세요. 스킬 목록에 '내보내는 결과'가 있는 스킬만 참조할 수 있습니다.
9. '참고 화면 설계 예시'가 주어지면, 질문 유형이 같을 때 그 슬롯 구성(스킬·인자 모양·name·참조)과 설명을 따르세요.
   꺾쇠로 감싼 자리표시자(<…>)만 현재 질문의 값으로 바꾸고, 개수·기간 같은 값은 현재 질문에 맞추세요.
   name과 '@이름.순위' 참조는 자리표시자가 아닙니다 — 실제 이름으로 바꾸지 말고 그대로 쓰세요. 유형이 다르면 예시를 무시하세요.
"""

# 레이아웃 예시 검색 기준. code_examples와 따로 둔다 — evals/run_layout_eval.py로 정밀도·재현율과 계획 통과율을 보고 정한다
EXAMPLES_TOP_K = 3
EXAMPLES_MAX_DISTANCE = 0.35
EXAMPLES_SIMILARITY_GAP = 0.05


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
        """참조 오류는 여기서 막는다 — 메시지가 플래너에게 그대로 돌아가 다시 쓰게 한다.
        재시도 횟수가 적어 오류를 하나씩 알려 주면 다 고치기 전에 바닥난다 — 찾은 오류를 모두 모아 한 번에 보낸다."""
        steps = [step for row in plan.rows for step in row.slots]
        errors: List[str] = []
        named = {}
        for step in steps:
            if step.name:
                if step.name in named:
                    errors.append(f"슬롯 이름 '{step.name}'이 두 번 쓰였습니다")
                else:
                    named[step.name] = step
        graph = {}
        for step in steps:
            refs = refs_in(step.args.model_dump())
            ok = []
            for ref in refs:
                target = named.get(ref)
                if target is None:
                    errors.append(f"{_label(step)}의 '@{ref}' 참조: name이 '{ref}'인 슬롯이 없습니다. "
                                  f"참조할 슬롯에 name=\"{ref}\"를 붙이세요")
                elif target is step:
                    errors.append(f"{_label(step)}이 자기 자신('{ref}')을 참조합니다")
                elif not registry[target.skill].exports:
                    errors.append(f"{_label(step)}의 '@{ref}' 참조: {target.skill} 스킬은 참조할 결과를 내보내지 않습니다")
                else:
                    ok.append(ref)
            if refs:  # 펼친 모양은 참조 문법만으로 정해진다 — 대상 슬롯이 틀려도 함께 알려 준다
                error = _expanded_error(step, steps)
                if error:
                    errors.append(error)
            graph[id(step)] = [id(named[r]) for r in ok]
        # name은 결과를 넘기려고 붙인다 — 받는 슬롯이 없으면 그 슬롯을 빠뜨린 것이다
        referenced = {r for step in steps for r in refs_in(step.args.model_dump())}
        for name, step in named.items():
            if name not in referenced:
                errors.append(f"{_label(step)}에 name '{name}'을 붙였지만 '@{name}.순위'로 받는 슬롯이 없습니다. "
                              "그 결과를 받아야 할 슬롯을 만들거나, 넘길 필요가 없으면 name을 지우세요")
        errors += _gap_errors(steps)
        if _has_cycle(graph):
            errors.append("슬롯들이 서로를 참조해 순환합니다")
        if len(errors) == 1:
            raise ValueError(errors[0])
        if errors:
            raise ValueError(f"오류 {len(errors)}개를 모두 고치세요:\n" + "\n".join(f"{i}. {e}" for i, e in enumerate(errors, 1)))
        return plan

    return create_model(
        "LayoutPlan", rows=(List[Row], Field(min_length=1, max_length=MAX_ROWS)),
        __validators__={"check_refs": model_validator(mode="after")(check_refs)},
    )


def _label(step: BaseModel) -> str:
    return f"{step.skill} 슬롯 '{step.title}'"


def _expanded_error(step: BaseModel, steps: List[BaseModel]) -> Optional[str]:
    """참조를 펼친 뒤에도 인자가 맞는지 (예: 최대 5개인 목록에 '@rank.1-10'을 넣으면 10개가 된다). 맞으면 None."""
    try:
        type(step.args).model_validate(expanded(step.args.model_dump()))
    except RefError as e:
        return f"{_label(step)}: {e}"
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(p) for p in err["loc"])
        hint = "'@이름.1-N'은 N개 항목이 됩니다. 범위를 줄이거나 같은 스킬 슬롯을 여럿으로 나눠 담으세요"
        if err["type"] == "too_long":  # 이 질문에 맞는 분할을 계산해 준다 (이름으로 적은 항목이 자리를 차지한다)
            # 이 슬롯만 보고 나누면 넘친 순위가 옆 슬롯으로 밀려 또 넘친다 — 같은 스킬 슬롯들의 순위와
            # 이름으로 적은 항목을 모두 합쳐 다시 나눈다. 어느 슬롯이 넘쳐도 같은 안내가 나와야 재시도가 수렴한다
            siblings = [v for other in steps if other.skill == step.skill
                        for v in _at(other.args.model_dump(), err["loc"]) or []]
            hint = split_hint(siblings, err["ctx"]["max_length"])
        return f"{_label(step)}의 참조를 펼치면 '{field}' 인자가 맞지 않습니다: {err['msg']}. {hint}"
    return None


def _gap_errors(steps: List[BaseModel]) -> List[str]:
    """같은 스킬 슬롯들이 범위 참조로 나눠 담은 순위에 빈 곳이 있으면 (예: '@rank.1-4' + '@rank.6-10'은 5위가 빠진다)."""
    errors = []
    by_skill: Dict[str, List[Any]] = {}
    for step in steps:
        by_skill.setdefault(step.skill, []).extend(_strings(step.args.model_dump()))
    for skill, values in by_skill.items():
        for name, missing in rank_gaps(values).items():
            listed = ", ".join(f"{r}위" for r in missing)
            errors.append(f"{skill} 슬롯들이 '@{name}' 순위를 나눠 담으면서 {listed}를 빠뜨렸습니다. 빠짐없이 이어지게 나누세요")
    return errors


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _at(value: Any, loc: tuple) -> Any:
    for key in loc:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError):
            return None
    return value


def _has_cycle(graph: Dict[int, List[int]]) -> bool:
    state: Dict[int, int] = {}  # 1: 방문 중, 2: 끝남

    def visit(node: int) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        if any(visit(nxt) for nxt in graph.get(node, [])):
            return True
        state[node] = 2
        return False

    return any(visit(node) for node in graph)


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


def data_lookups(session_factory: Callable[[], Session]) -> Dict[str, Callable]:
    """플래너가 DB를 보는 함수들 — Planner(**data_lookups(...))로 넘긴다. 부를 때마다 세션을 따로 연다 (스레드에서 돈다)."""
    def with_session(fn):
        def call(*args):
            db = session_factory()
            try:
                return fn(db, *args)
            finally:
                db.close()
        return call

    return {"find_examples": with_session(find_layout_examples), "is_etf_name": with_session(is_etf_name)}


def data_errors(plan: BaseModel, is_etf_name: Callable[[str], bool]) -> List[str]:
    """스키마로는 알 수 없고 데이터를 봐야 아는 계획 오류."""
    errors = []
    for step in (step for row in plan.rows for step in row.slots):
        # 테마로 되묻는데 그 '테마'가 상장 ETF의 정확한 이름이면, 대상이 이미 정해진 것이다
        if step.skill == "etf_choice" and step.args.by == "theme" and is_etf_name(step.args.condition):
            errors.append(f"{_label(step)}: '{step.args.condition}'은(는) 테마가 아니라 ETF 상품 이름입니다. "
                          "되묻지 말고 그 이름을 데이터 스킬의 인자에 그대로 적으세요")
    return errors


def find_layout_examples(db: Session, question: str) -> List[Dict[str, Any]]:
    """질문과 유형이 비슷한 화면 설계 예시. 예시는 고유명사를 뺀 일반화 질문으로 임베딩되어 있어 검색 질의도 일반화한다."""
    service = EmbeddingService(db)
    return service.find_similar_layout_examples(
        service.generalize_question(question), top_k=EXAMPLES_TOP_K,
        max_distance=EXAMPLES_MAX_DISTANCE, similarity_gap=EXAMPLES_SIMILARITY_GAP,
    )


def examples_prompt(examples: List[Dict[str, Any]]) -> str:
    parts = ["## 참고 화면 설계 예시"]
    for ex in examples:
        try:  # 프롬프트 길이를 줄이려 한 줄로 다시 쓴다
            plan = json.dumps(json.loads(ex["plan"]), ensure_ascii=False)
        except (TypeError, ValueError):
            plan = ex["plan"]
        why = f"\n설명: {ex['description']}" if ex.get("description") else ""
        parts.append(f"Q: {ex.get('question_generalized') or ex['question']}{why}\n{plan}")
    return "\n\n".join(parts)


class Planner:
    def __init__(
        self, config: AIConfig, registry: Dict[str, Skill] = REGISTRY,
        find_examples: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        is_etf_name: Optional[Callable[[str], bool]] = None,
    ):
        self._find_examples = find_examples
        self._agent = Agent(
            build_model(config),
            output_type=build_plan_model(registry),
            instructions=f"{PLANNER_PROMPT}\n{skill_catalog(registry)}",
            model_settings=NO_THINKING,
            retries=2,
        )
        if is_etf_name is not None:
            @self._agent.output_validator
            async def check_data(output):
                errors = await asyncio.to_thread(data_errors, output, is_etf_name)
                if errors:  # 스키마 검증 오류와 같이, 이유를 플래너에게 돌려줘 다시 쓰게 한다
                    raise ModelRetry("\n".join(errors))
                return output

    async def plan(self, question: str, context: ConversationContext) -> List[List[PlannedSlot]]:
        parts = []
        examples = await self._examples(question)
        if examples:
            parts.append(examples_prompt(examples))
        if not context.is_empty():
            parts.append(f"## 이전 대화 (참고용)\n{context.render()}")
        parts.append(f"## 질문\n{question}")
        prompt = "\n\n".join(parts)
        try:
            result = await self._agent.run(prompt)
            rows = to_rows(result.output)
        except Exception:
            logger.exception("Layout planning failed; falling back to the agent skill")
            return fallback_rows(question)
        return rows or fallback_rows(question)

    async def _examples(self, question: str) -> List[Dict[str, Any]]:
        if self._find_examples is None:
            return []
        try:
            examples = await asyncio.to_thread(self._find_examples, question)
        except Exception:  # 예시 없이도 설계할 수 있다
            logger.exception("Layout example search failed; planning without examples")
            return []
        if examples:
            logger.info("Layout examples for %r: %s", question, [ex["id"] for ex in examples])
        return examples
