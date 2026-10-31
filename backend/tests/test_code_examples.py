"""해결 절차 예시 시드(docker/db/seed/code_examples.py)가 지금 에이전트의 도구 이름·인자로 적혀 있는지."""
import ast
import importlib.util
from pathlib import Path

import pytest

from app.services import chat_service as cs
from app.services.answer.skills import REGISTRY
from app.services.answer.tools import skill_tools

SEED = Path(__file__).resolve().parents[2] / "docker" / "db" / "seed" / "code_examples.py"


@pytest.fixture(scope="module")
def examples():
    if not SEED.exists():  # 백엔드 이미지에는 docker/가 없다
        pytest.skip("시드 파일이 없습니다")
    spec = importlib.util.spec_from_file_location("seed_code_examples", SEED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EXAMPLES


def _agent_tools():
    svc = cs.ChatService.__new__(cs.ChatService)
    svc.db = None
    custom = svc._create_tools()
    skills = {s.name: (s.tool_args or s.Args) for s in REGISTRY.values()
              if s.name in {t.name for t in skill_tools(REGISTRY, lambda: None)}}
    return custom, skills


def _calls(code):
    for line in code.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            call = ast.parse(line.strip(), mode="eval").body
            yield line, call.func.id, {k.arg: ast.literal_eval(k.value) for k in call.keywords}


def test_seed_examples_all_pass_the_tool_filter(examples):
    custom, skills = _agent_tools()
    names = [*custom, *skills]
    assert cs.usable_examples(examples, names) == examples


def test_seed_example_arguments_match_the_tool_schemas(examples):
    custom, skills = _agent_tools()
    for ex in examples:
        for line, name, args in _calls(ex["code"]):
            if name in skills:  # 스킬 도구: 도구가 노출하는 인자 모델로 그대로 검사한다
                skills[name].model_validate(args)
            else:
                inputs = custom[name].inputs
                assert set(args) <= set(inputs), line
                assert {k for k, v in inputs.items() if not v.get("nullable")} <= set(args), line
