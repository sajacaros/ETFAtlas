"""레이아웃 에이전트: 질문을 보고 화면을 슬롯으로 나눈다. 출력 스키마와 스킬 설명은 레지스트리에서 만든다.

LLM에게는 재귀 트리 대신 '줄(row) 목록, 줄마다 슬롯 1~3개'라는 평평한 구조를 받는다 (작은 모델도 안정적으로 채운다).
프런트로 보내는 레이아웃은 column/row/slot 트리로 바꾼다.
"""
import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Set, Union

from annotated_types import MinLen
from pydantic import BaseModel, Field, ValidationError, create_model, model_validator
from pydantic_ai import Agent, ModelRetry, NativeOutput, RunContext
from sqlalchemy.orm import Session

from ..ai_config import AIConfig
from ..chat_memory import ConversationContext
from ..content import slot_type
from ..embedding_service import EmbeddingService
from ..entities import is_etf_name
from ..llm import NO_THINKING, build_model
from .refs import REF_RE, RefError, expanded, rank_gaps, refs_in, split_hint
from .skills import FALLBACK_SKILL, REGISTRY
from .skills.base import KIND_LABEL, Skill

logger = logging.getLogger(__name__)

MAX_ROWS = 6
MAX_SLOTS_PER_ROW = 3
MAX_SLOTS = 8

# 규칙은 스킬·종목 이름에 기대지 않고 원리만 적는다. 질문 유형별 구체적인 설계는 레이아웃 예시(layout_examples)가 맡는다 —
# 여기에 특정 사례를 넣으면 모든 질문이 그 사례 쪽으로 끌려간다. 스킬별 용도는 스킬 설명(skill_catalog)에 있다.
PLANNER_PROMPT = f"""당신은 ETF Atlas 챗봇의 화면 설계 담당입니다. 한국 ETF와 그 ETF들이 담은 개별 종목(기업)에 관한 사용자의 질문에 답할 화면을 영역(슬롯)으로 나눕니다.
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
   스킬 설명에 narrative 대신 해설 자리를 맡는다고 적힌 스킬을 쓸 때는 narrative 없이 그 스킬 하나를 마지막 줄에 둡니다.
5. 스킬로 표현할 수 없는 질문은 agent 슬롯 하나만 쓰세요(이때 narrative는 붙이지 않습니다). 범위 밖 질문도 agent로 넘기세요.
6. display(표시 방식)는 반드시 적으세요. 사용자가 차트 종류(봉차트, 도넛, 트리맵 등)를 말했으면 그것을 쓰고,
   아니면 그 스킬이 지원하는 것 중에서 고르세요:
   추세는 line, 일별 가격 움직임(봉)은 candlestick, 기간·항목별 비교는 bar, 종목이 많은 구성은 treemap,
   몇 개 항목의 비중은 donut, 여러 지표의 종합 비교는 radar, 정확한 수치 확인은 table.
7. title은 영역 위에 표시할 짧은 제목입니다.
8. 한 슬롯의 결과(순위가 있는 ETF·종목 목록)를 다른 슬롯의 대상으로 써야 하면, 결과를 내보내는 슬롯에 name(짧은 영문)을 붙이고
   다른 슬롯의 인자에 '@name.1'(1위), '@name.1-3'(1~3위, 목록 인자에서만)을 적으세요.
   아직 모르는 대상을 설명 문구('…1위 ETF')로 적지 마세요. 스킬 목록에 '내보내는 결과'가 있는 스킬만 참조할 수 있습니다.
   참조한 결과의 종류(ETF·종목)는 받는 인자의 종류('참조로 받는 인자')와 같아야 합니다.
9. '참고 화면 설계 예시'가 주어지면, 질문 유형이 같을 때 그 슬롯 구성(스킬·인자 모양·name·참조)과 설명을 따르세요.
   꺾쇠로 감싼 자리표시자(<…>)만 현재 질문의 값으로 바꾸고, 개수·기간 같은 값은 현재 질문에 맞추세요
   (질문에 기간이 없으면 예시의 기간을 옮기지 말고 인자 설명의 기본값을 쓰세요).
   name과 '@이름.순위' 참조는 자리표시자가 아닙니다 — 실제 이름으로 바꾸지 말고 그대로 쓰세요. 유형이 다르면 예시를 무시하세요.
"""

# 레이아웃 예시 검색 기준. code_examples와 따로 둔다 — evals/run_layout_eval.py로 정밀도·재현율과 계획 통과율을 보고 정한다
EXAMPLES_TOP_K = 3
EXAMPLES_MAX_DISTANCE = 0.35
EXAMPLES_SIMILARITY_GAP = 0.05
# 예시 선택기: 임베딩은 표현이 비슷한 예시를 넓게 후보로 뽑고(유형이 달라도), LLM이 질문 유형이 같은 것만 고른다
EXAMPLE_SELECTOR = True
EXAMPLE_CANDIDATES = 8
EXAMPLE_CANDIDATE_MAX_DISTANCE = 0.45

SELECTOR_PROMPT = """한국 ETF·종목 분석 챗봇의 화면 설계 예시 중에서, 사용자 질문과 같은 유형의 예시를 고릅니다.
유형이 같다는 것은 같은 스킬 조합과 같은 방식(순위 결과를 넘기는 참조, 슬롯 나누기, 되묻기 등)으로 화면을 짜야 한다는 뜻입니다.
종목·ETF 이름이나 숫자(상위 몇 개, 기간)가 달라도 유형은 같을 수 있고, 단어가 비슷해도 화면 구성이 다르면 다른 유형입니다.
같은 유형이 없으면 빈 목록을 내세요. 최대 {top_k}개, 가장 잘 맞는 것부터."""

# 실행 결과를 보고 한 번 다시 설계할 때 덧붙이는 규칙
REPLAN_RULES = """
## 다시 설계
이전 계획을 실행했더니 일부 슬롯이 비었습니다. 슬롯마다 실행 결과가 적혀 있습니다.
- '고칠 수 있음'으로 표시된 슬롯만 고치세요. 실패 이유를 보고 대상의 종류(ETF인지 개별 종목인지), 스킬, 인자가 맞았는지 다시 보세요.
  스킬·인자·표시 방식·제목을 바꿀 수 있습니다.
- 나머지 슬롯은 그대로 두세요. 줄과 슬롯의 배치(순서, 개수)도 바꾸지 마세요 — 이미 화면에 그려져 있습니다.
- 사용자가 말한 이름을 다른 대상으로 바꾸거나 추측하지 마세요. 고칠 방법이 없으면 그 슬롯을 agent 슬롯으로 바꾸세요.
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


def plan_args(args: type[BaseModel]) -> type[BaseModel]:
    """계획 단계의 인자 모델: 목록의 최소 개수를 1로 낮춘다. 참조('@rank.1-3') 하나가 펼치면 여러 항목이 되므로
    펼치기 전에 원래 최소 개수로 막으면 맞는 계획도 거절된다. 원래 제한은 참조를 펼친 뒤에 원래 Args로 검사한다."""
    relaxed = {}
    for key, info in args.model_fields.items():
        if any(isinstance(m, MinLen) and m.min_length > 1 for m in info.metadata):
            field = copy.copy(info)
            field.metadata = [MinLen(1) if isinstance(m, MinLen) else m for m in info.metadata]
            relaxed[key] = (info.annotation, field)
    return create_model(f"{args.__name__}Plan", __base__=args, **relaxed) if relaxed else args


def _step_model(skill: Skill) -> type[BaseModel]:
    return create_model(
        f"Slot_{skill.name}",
        skill=(Literal[skill.name], ...),
        name=(Optional[str], Field(None, description="다른 슬롯이 이 결과를 '@name.1'로 참조할 때만 붙이는 짧은 영문 이름")),
        title=(str, Field(description="영역 제목 (짧게)")),
        # 기본값을 두면 모델이 빠뜨린 채 넘어가 요청과 다른 차트가 나온다 — 반드시 고르게 한다
        display=(Literal[skill.displays], Field(description="표시 방식")),
        args=(plan_args(skill.Args), ...),
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
            # 펼친 모양은 참조 문법만으로 정해진다 — 대상 슬롯이 틀려도 함께 알려 준다.
            # 참조가 없어도 검사한다 (계획 인자 모델은 목록 최소 개수를 낮춘 것이다)
            error = _expanded_error(step, steps, registry[step.skill].Args)
            if error:
                errors.append(error)
            errors += _kind_errors(step, named, registry)
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


def _expanded_error(step: BaseModel, steps: List[BaseModel], args_model: type[BaseModel]) -> Optional[str]:
    """참조를 펼친 뒤에도 인자가 원래 Args에 맞는지 (예: 최대 5개인 목록에 '@rank.1-10'을 넣으면 10개가 된다). 맞으면 None."""
    dumped = step.args.model_dump()
    try:
        args_model.model_validate(expanded(dumped))
    except RefError as e:
        return f"{_label(step)}: {e}"
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(p) for p in err["loc"])
        if not refs_in(dumped):
            return f"{_label(step)}의 '{field}' 인자가 맞지 않습니다: {err['msg']}"
        hint = "'@이름.1-N'은 N개 항목이 됩니다. 범위를 줄이거나 같은 스킬 슬롯을 여럿으로 나눠 담으세요"
        if err["type"] == "too_long":  # 이 질문에 맞는 분할을 계산해 준다 (이름으로 적은 항목이 자리를 차지한다)
            # 이 슬롯만 보고 나누면 넘친 순위가 옆 슬롯으로 밀려 또 넘친다 — 같은 스킬 슬롯들의 순위와
            # 이름으로 적은 항목을 모두 합쳐 다시 나눈다. 어느 슬롯이 넘쳐도 같은 안내가 나와야 재시도가 수렴한다
            siblings = [v for other in steps if other.skill == step.skill
                        for v in _at(other.args.model_dump(), err["loc"]) or []]
            hint = split_hint(siblings, err["ctx"]["max_length"])
        return f"{_label(step)}의 참조를 펼치면 '{field}' 인자가 맞지 않습니다: {err['msg']}. {hint}"
    return None


KIND_OBJECT = {"etf": "ETF를", "stock": "종목을"}
KIND_TO = {"etf": "ETF로", "stock": "종목으로"}


def bridges(registry: Dict[str, Skill], source: str, target: str) -> List[str]:
    """source 종류를 받아 target 종류를 내보내는 스킬 (예: ETF → 종목은 holdings)."""
    return [s.name for s in registry.values() if s.exports_kind == target and source in s.entity_args.values()]


def _kind_errors(step: BaseModel, named: Dict[str, BaseModel], registry: Dict[str, Skill]) -> List[str]:
    """참조한 결과의 종류(ETF·종목)가 그 인자가 받는 종류와 다르면 (예: ETF 목록을 종목 차트 분석에 넣는다)."""
    errors = []
    dumped = step.args.model_dump()
    for field, need in registry[step.skill].arg_kinds(dumped).items():
        for value in _strings(dumped.get(field)):
            m = REF_RE.match(value.strip())
            target = named.get(m.group(1)) if m else None
            if target is None or not registry[target.skill].exports:  # 없는 이름·내보내지 않는 스킬은 따로 알린다
                continue
            got = registry[target.skill].export_kind(target.args.model_dump())
            if got is None or got == need:
                continue
            via = bridges(registry, got, need)
            hint = (f" {KIND_LABEL[got]}에서 {KIND_TO[need]} 이으려면 그 사이에 {' 또는 '.join(via)} 슬롯을 두고 "
                    "그 결과를 참조하세요") if via else ""
            errors.append(f"{_label(step)}의 '{field}' 인자는 {KIND_OBJECT[need]} 받는데 '@{m.group(1)}'({target.skill})은 "
                          f"{KIND_LABEL[got]} 목록을 내보냅니다.{hint}")
    return errors


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


SUBJECT_TITLE = {"etf": "ETF", "stock": "개별 종목(기업)", "portfolio": "포트폴리오", "any": "공통"}


def skill_catalog(registry: Dict[str, Skill]) -> str:
    lines = ["## 스킬"]
    for subject, title in SUBJECT_TITLE.items():
        skills = [s for s in registry.values() if s.subject == subject]
        if not skills:
            continue
        lines.append(f"### {title}")
        for s in skills:
            args = {k: v.get("description", v.get("type", "")) for k, v in s.Args.model_json_schema()["properties"].items()}
            kind = f", {KIND_LABEL[s.exports_kind]}" if s.exports_kind else ""
            takes = ", ".join(f"{k}={KIND_LABEL[v]}" for k, v in s.entity_args.items())
            lines.append(
                f"- {s.name}: {s.description}\n"
                f"  display: {', '.join(s.displays)} / args: {json.dumps(args, ensure_ascii=False)}"
                + (f"\n  내보내는 결과(참조 가능{kind}): {s.exports}" if s.exports else "")
                + (f"\n  참조로 받는 인자: {takes}" if takes else "")
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


def layout_tree(rows: List[List[PlannedSlot]], splits: Optional[Dict[str, List[PlannedSlot]]] = None) -> Dict[str, Any]:
    """splits: 스킬이 실행하며 나눈 슬롯 id → 나눈 영역. 그 자리에 차트는 한 줄로 나란히, 텍스트는 그 아래로 놓는다."""
    def leaf(s: PlannedSlot) -> Dict[str, Any]:
        return {"type": "slot", "id": s.id, "slot": slot_type(s.display), "display": s.display, "title": s.title}

    def slot_node(s: PlannedSlot) -> Dict[str, Any]:
        parts = (splits or {}).get(s.id)
        if not parts:
            return leaf(s)
        charts = [leaf(p) for p in parts if slot_type(p.display) not in ("text", "markdown")]
        texts = [leaf(p) for p in parts if slot_type(p.display) in ("text", "markdown")]
        top = [charts[0]] if len(charts) == 1 else [{"type": "row", "children": charts}] if charts else []
        return {"type": "column", "children": top + texts}

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
    if EXAMPLE_SELECTOR:  # 선택기가 고를 후보: 넓게, 1위와의 거리 차이로 자르지 않는다
        params = {"top_k": EXAMPLE_CANDIDATES, "max_distance": EXAMPLE_CANDIDATE_MAX_DISTANCE, "similarity_gap": 0}
    else:
        params = {"top_k": EXAMPLES_TOP_K, "max_distance": EXAMPLES_MAX_DISTANCE, "similarity_gap": EXAMPLES_SIMILARITY_GAP}
    return service.find_similar_layout_examples(service.generalize_question(question), **params)


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


@dataclass
class ReplanDeps:
    previous: List[List[Dict[str, Any]]]  # 이전 계획 (줄 → 슬롯 step)
    editable: Set[str]  # 바꿔도 되는 슬롯 id: 고칠 수 있는 실패, 그 결과를 받는 슬롯, 해설


class ExampleChoice(BaseModel):
    ids: List[int] = Field(default_factory=list, description="고른 예시 번호 (잘 맞는 순, 없으면 빈 목록)")


def _step_dict(slot: PlannedSlot) -> Dict[str, Any]:
    step = {"skill": slot.skill, "title": slot.title, "display": slot.display, "args": slot.args.model_dump()}
    return {**({"name": slot.name} if slot.name else {}), **step}


def _same_step(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """그대로 둬야 하는 슬롯이 바뀌지 않았는지 — 제목만 다듬은 것은 봐준다."""
    return all(a.get(k) == b.get(k) for k in ("skill", "name", "display", "args"))


def replan_errors(plan: BaseModel, deps: ReplanDeps) -> List[str]:
    """다시 설계한 계획이 화면 배치와 고치면 안 되는 슬롯을 지켰는지."""
    rows = [[s.model_dump() for s in row.slots] for row in plan.rows]
    if [len(r) for r in rows] != [len(r) for r in deps.previous]:
        return ["줄과 슬롯의 배치(순서, 개수)를 이전 계획과 같게 두세요. 고칠 수 있는 슬롯 자리에서만 바꾸세요"]
    errors, n = [], 0
    for new_row, old_row in zip(rows, deps.previous):
        for new, old in zip(new_row, old_row):
            n += 1
            if f"s{n}" not in deps.editable and not _same_step(new, old):
                errors.append(f"s{n} 슬롯 '{old['title']}'은(는) 결과가 이미 화면에 있습니다. 이전 계획 그대로 두세요")
    return errors


def editable_slots(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]], registry: Dict[str, Skill]) -> Set[str]:
    """다시 설계에서 바꿔도 되는 슬롯: 고칠 수 있는 실패, 그 결과를 (참조로 이어서) 받는 슬롯, 해설 같은 after_others."""
    editable = {s.id for s in slots if results.get(s.id, {}).get("retryable")}
    changed = True
    while changed:
        changed = False
        for s in slots:
            if s.id not in editable and set(s.depends_on) & editable:
                editable.add(s.id)
                changed = True
    return editable | {s.id for s in slots if registry[s.skill].after_others}


def results_prompt(slots: List[PlannedSlot], results: Dict[str, Dict[str, Any]], editable: Set[str]) -> str:
    lines = ["## 이전 계획과 실행 결과"]
    for s in slots:
        r = results.get(s.id)
        if r is None:
            outcome = "아직 실행 전"
        elif r.get("retryable"):
            outcome = f"고칠 수 있음 — {r.get('message')}"
        elif r.get("status") == "complete":
            outcome = "완료"
        else:
            outcome = f"비었음 — {r.get('message')}" + (" (앞 슬롯을 고치면 다시 실행됨)" if s.id in editable else "")
        lines.append(f"- {s.id} {json.dumps(_step_dict(s), ensure_ascii=False)}\n  → {outcome}")
    lines.append("\n위 계획에서 '고칠 수 있음' 슬롯만 고친 전체 계획을 내세요.")
    return "\n".join(lines)


def _example_line(i: int, ex: Dict[str, Any]) -> str:
    try:
        plan = json.loads(ex["plan"])
        steps = [s for row in plan["rows"] for s in row["slots"]]
        shape = " + ".join(s["skill"] for s in steps if s["skill"] != "narrative")
        uses_refs = any(refs_in(s.get("args", {})) for s in steps)
    except (TypeError, ValueError, KeyError):
        shape, uses_refs = "?", False
    why = f" / {ex['description']}" if ex.get("description") else ""
    return f"[{i}] {ex.get('question_generalized') or ex['question']}{why} / 스킬: {shape}{' (참조)' if uses_refs else ''}"


class Planner:
    def __init__(
        self, config: AIConfig, registry: Dict[str, Skill] = REGISTRY,
        find_examples: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        is_etf_name: Optional[Callable[[str], bool]] = None,
    ):
        self._registry = registry
        self._find_examples = find_examples
        self.last_examples: List[Dict[str, Any]] = []  # 마지막 설계에 넣은 예시 (다시 설계와 평가에서 쓴다)
        plan_model = build_plan_model(registry)
        instructions = f"{PLANNER_PROMPT}\n{skill_catalog(registry)}"
        # 설계는 스키마를 생성 단계에서 강제한다(NativeOutput). 도구 호출 방식보다 빠르고, 재시도는 내용 검사에만 쓰여
        # 다시 설계가 한도를 넘겨 실패하지 않는다 (evals --output으로 비교). 선택기는 native면 예시를 덜 골라 그대로 둔다
        self._agent = Agent(build_model(config), output_type=NativeOutput(plan_model), instructions=instructions,
                            model_settings=NO_THINKING, retries=2)
        self._replanner = Agent(build_model(config), output_type=NativeOutput(plan_model), deps_type=ReplanDeps,
                                instructions=instructions + REPLAN_RULES, model_settings=NO_THINKING, retries=2)
        self._selector = Agent(build_model(config), output_type=ExampleChoice,
                               instructions=SELECTOR_PROMPT.format(top_k=EXAMPLES_TOP_K), model_settings=NO_THINKING, retries=1)

        async def check_data(output):
            if is_etf_name is not None:
                errors = await asyncio.to_thread(data_errors, output, is_etf_name)
                if errors:  # 스키마 검증 오류와 같이, 이유를 플래너에게 돌려줘 다시 쓰게 한다
                    raise ModelRetry("\n".join(errors))
            return output

        async def check_replan(ctx: RunContext[ReplanDeps], output):
            errors = replan_errors(output, ctx.deps)
            if errors:
                raise ModelRetry("\n".join(errors))
            return await check_data(output)

        self._agent.output_validator(check_data)
        self._replanner.output_validator(check_replan)

    async def plan(self, question: str, context: ConversationContext) -> List[List[PlannedSlot]]:
        self.last_examples = await self._examples(question)
        try:
            result = await self._agent.run(self._prompt(question, context))
            rows = to_rows(result.output)
        except Exception:
            logger.exception("Layout planning failed; falling back to the agent skill")
            return fallback_rows(question)
        return rows or fallback_rows(question)

    async def replan(
        self, question: str, context: ConversationContext, rows: List[List[PlannedSlot]], results: Dict[str, Dict[str, Any]],
    ) -> Optional[List[List[PlannedSlot]]]:
        """실행 결과를 보고 고칠 수 있는 슬롯만 다시 설계한다. 배치는 그대로라 슬롯 id가 유지된다. 실패하면 None."""
        slots = [s for row in rows for s in row]
        editable = editable_slots(slots, results, self._registry)
        deps = ReplanDeps(previous=[[_step_dict(s) for s in row] for row in rows], editable=editable)
        prompt = self._prompt(question, context, extra=results_prompt(slots, results, editable))
        try:
            result = await self._replanner.run(prompt, deps=deps)
            return to_rows(result.output) or None
        except Exception:
            logger.exception("Replanning failed; keeping the first plan")
            return None

    def _prompt(self, question: str, context: ConversationContext, extra: str = "") -> str:
        parts = []
        if self.last_examples:
            parts.append(examples_prompt(self.last_examples))
        if not context.is_empty():
            parts.append(f"## 이전 대화 (참고용)\n{context.render()}")
        parts.append(f"## 질문\n{question}")
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    async def _examples(self, question: str) -> List[Dict[str, Any]]:
        if self._find_examples is None:
            return []
        try:
            candidates = await asyncio.to_thread(self._find_examples, question)
        except Exception:  # 예시 없이도 설계할 수 있다
            logger.exception("Layout example search failed; planning without examples")
            return []
        examples = await self._select(question, candidates) if EXAMPLE_SELECTOR else candidates
        if examples:
            logger.info("Layout examples for %r: %s", question, [ex["id"] for ex in examples])
        return examples

    async def _select(self, question: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """후보 중 질문 유형이 같은 예시만. 고르지 못하면 거리 기준으로만 거른다."""
        if not candidates:
            return []
        listing = "\n".join(_example_line(i, ex) for i, ex in enumerate(candidates, 1))
        try:
            result = await self._selector.run(f"## 질문\n{question}\n\n## 예시 후보\n{listing}")
            picked = [candidates[i - 1] for i in dict.fromkeys(result.output.ids) if 1 <= i <= len(candidates)]
            return picked[:EXAMPLES_TOP_K]
        except Exception:
            logger.exception("Example selection failed; using the nearest examples")
            near = [ex for ex in candidates if ex["distance"] < EXAMPLES_MAX_DISTANCE]
            return [ex for ex in near if ex["distance"] - near[0]["distance"] <= EXAMPLES_SIMILARITY_GAP][:EXAMPLES_TOP_K]
