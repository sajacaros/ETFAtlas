"""레이아웃 플래너 평가: 평가 세트의 질문마다 예시 검색 → 플래너 → 계획 채점.

실제 LLM·임베딩·DB를 쓰므로 단위 테스트가 아니다. 백엔드 컨테이너 안에서 돌린다:
  docker cp backend/evals etf-atlas-backend:/tmp/evals
  docker exec -w /app -e PYTHONPATH=/app etf-atlas-backend python /tmp/evals/run_layout_eval.py --reps 2
  ... --distances      예시 검색 기준값을 맞출 때 쓰는 질문 × 예시 거리표만 출력

채점은 계획만 본다 (슬롯을 실행하지 않는다). 기준은 layout_eval.json의 _comment 참고.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import RetryPromptPart
from sqlalchemy import text

from app.database import SessionLocal
from app.services.ai_config import load_ai_config
from app.services.chat_memory import ConversationContext
from app.services.embedding_service import EmbeddingService
from app.services.answer import planner as planner_mod
from app.services.answer.orchestrator import AnswerService
from app.services.answer.planner import Planner

REF_RE = re.compile(r"^@\w+\.(\d+)(?:-(\d+))?$")


def strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def ranks(args: Dict[str, Any]) -> Set[int]:
    out: Set[int] = set()
    for s in strings(args):
        m = REF_RE.match(s.strip())
        if m:
            out |= set(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    return out


def allowed_skills(item: Dict) -> Set[str]:
    skills = {s for group in item["must"] for s in group.split("|")}
    return skills | set(item.get("allowed", [])) | {"narrative"}


def judge(item: Dict, slots: List[Dict]) -> List[str]:
    """틀린 점 목록 (비면 통과)."""
    problems = []
    used = [s["skill"] for s in slots]
    for group in item["must"]:
        if not any(s in used for s in group.split("|")):
            problems.append(f"{group} 없음")
    extra = sorted(set(used) - allowed_skills(item))
    if extra:
        problems.append(f"허용 밖 스킬 {extra}")
    for group, n in item.get("cover", {}).items():
        got = set().union(*[ranks(s["args"]) for s in slots if s["skill"] in group.split("|")] or [set()])
        missing = sorted(set(range(1, n + 1)) - got)
        if missing:
            problems.append(f"{group} 순위 누락 {missing}")
    text_args = " ".join(strings([s["args"] for s in slots])).lower()
    for name in item.get("names", []):
        if name.lower() not in text_args:
            problems.append(f"'{name}' 없음")
    if item.get("together"):
        want = {n.lower() for n in item["together"]}
        if not any(want <= {x.lower() for x in s["args"].get("stocks", [])} for s in slots if s["skill"] == "stock_holders"):
            problems.append(f"{item['together']}가 한 stock_holders에 없음")
    for skill, display in item.get("display", {}).items():
        if not any(s["skill"] == skill and s["display"] == display for s in slots):
            problems.append(f"{skill} display≠{display}")
    return problems


def seed_skills(db) -> Dict[int, Set[str]]:
    rows = db.execute(text("SELECT id, plan FROM layout_examples WHERE status = 'embedded'")).fetchall()
    return {r.id: {s["skill"] for row in json.loads(r.plan)["rows"] for s in row["slots"]} - {"narrative"} for r in rows}


class _NullStore:
    def create(self, *args):
        pass

    def save(self, *args):
        pass


async def execute(question: str, rows) -> List[str]:
    """계획대로 슬롯을 실행해 영역마다 문구·요약·주석을 모은다."""
    db = SessionLocal()
    try:
        service = AnswerService(db)
        service._store = _NullStore()
        slots = [s for r in rows for s in r]
        results: Dict[str, Dict] = {}
        async for _ in service._run_slots(slots, question, ConversationContext(), 0, asyncio.Event(), results):
            pass
    finally:
        db.close()
    texts = []
    for r in results.values():
        texts += [r.get("message") or "", r.get("summary") or ""]
        texts += (r.get("content") or {}).get("notes") or []
    return [t for t in texts if t]


async def run_one(item: Dict, config, seeds: Dict[int, Set[str]], sem: asyncio.Semaphore) -> Dict:
    async with sem:
        found: List[Dict] = []
        lookups = planner_mod.data_lookups(SessionLocal)  # 서비스와 같은 연결, 예시 검색만 기록하게 감싼다

        def find(question: str) -> List[Dict]:
            found.extend(lookups["find_examples"](question))
            return found

        planner = Planner(config, **{**lookups, "find_examples": find})
        with capture_run_messages() as messages:
            rows = await planner.plan(item["q"], ConversationContext())
        slots = [{"skill": s.skill, "name": s.name, "title": s.title, "display": s.display, "args": s.args.model_dump()}
                 for r in rows for s in r]
        retries = sum(isinstance(p, RetryPromptPart) for m in messages for p in getattr(m, "parts", []))
        # 설계 실패 시 fallback_rows는 제목 없는 agent 슬롯 하나에 질문을 그대로 넘긴다
        fallback = len(slots) == 1 and slots[0]["skill"] == "agent" and not slots[0]["title"]
        problems = judge(item, slots)
        if item.get("expect_message"):  # 계획만으로는 알 수 없는 안내 문구는 슬롯을 실행해 본다
            texts = await execute(item["q"], rows)
            if not any(item["expect_message"] in t for t in texts):
                problems.append(f"'{item['expect_message']}' 안내 없음: {[t[:80] for t in texts]}")
        allowed = allowed_skills(item)
        relevant_seeds = [i for i, sk in seeds.items() if sk and sk <= allowed]
        return {
            "q": item["q"], "ok": not problems, "problems": problems, "retries": retries,
            "fallback": fallback,
            "examples": [(e["id"], e["distance"], seeds.get(e["id"], set()) <= allowed) for e in found],
            "relevant_seeds": relevant_seeds,
            "slots": [(s["skill"], s["display"], s["name"], s["args"]) for s in slots if s["skill"] != "narrative"],
        }


async def evaluate(items: List[Dict], reps: int, concurrency: int) -> List[Dict]:
    db = SessionLocal()
    config = load_ai_config(db)
    seeds = seed_skills(db)
    db.close()
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(run_one(item, config, seeds, sem) for item in items for _ in range(reps)))


def report(results: List[Dict]) -> None:
    by_q: Dict[str, List[Dict]] = {}
    for r in results:
        by_q.setdefault(r["q"], []).append(r)
    for q, runs in by_q.items():
        ok = sum(r["ok"] for r in runs)
        mark = "OK " if ok == len(runs) else "-- "
        print(f"{mark}[{ok}/{len(runs)}] {q}")
        for r in runs:
            ex = ", ".join(f"#{i}({d:.2f}{'' if rel else ' 무관'})" for i, d, rel in r["examples"]) or "-"
            line = f"      예시 {ex} | 재시도 {r['retries']}"
            if not r["ok"]:
                line += f" | {'; '.join(r['problems'])} | {[(s[0], s[3]) for s in r['slots']]}"
            print(line[:400])
    n = len(results)
    injected = [e for r in results for e in r["examples"]]
    print("\n== 요약")
    print(f"  통과 {sum(r['ok'] for r in results)}/{n} ({sum(r['ok'] for r in results) / n:.0%}), "
          f"질문 단위 전부 통과 {sum(all(r['ok'] for r in runs) for runs in by_q.values())}/{len(by_q)}")
    print(f"  재시도 평균 {sum(r['retries'] for r in results) / n:.2f}, agent 폴백 {sum(r['fallback'] for r in results)}")
    print(f"  넣은 예시 {len(injected)}개 중 유형 맞음 {sum(e[2] for e in injected)}, 무관 {sum(not e[2] for e in injected)}; "
          f"맞는 시드가 있는데 못 넣은 실행 {sum(1 for r in results if r['relevant_seeds'] and not any(e[2] for e in r['examples']))}")


def distances(items: List[Dict]) -> None:
    """질문(일반화) × 모든 예시 거리와, 그 예시가 질문 유형에 맞는지 — 검색 기준값을 맞출 때 쓴다."""
    db = SessionLocal()
    service = EmbeddingService(db)
    seeds = seed_skills(db)
    out = []
    for item in items:
        g = service.generalize_question(item["q"])
        rows = service.find_similar_layout_examples(g, top_k=50, max_distance=2.0, similarity_gap=0)
        allowed = allowed_skills(item)
        out.append({"q": item["q"], "generalized": g,
                    "examples": [{"id": r["id"], "distance": r["distance"], "relevant": seeds[r["id"]] <= allowed} for r in rows]})
    print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default=str(Path(__file__).with_name("layout_eval.json")))
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--only", help="질문에 이 문자열이 든 항목만")
    parser.add_argument("--distances", action="store_true")
    parser.add_argument("--json", help="실행 결과를 이 파일에 저장")
    parser.add_argument("--top-k", type=int, help="예시 검색 기준을 바꿔 본다 (planner.EXAMPLES_*)")
    parser.add_argument("--max-distance", type=float)
    parser.add_argument("--gap", type=float)
    args = parser.parse_args()
    for attr, value in (("EXAMPLES_TOP_K", args.top_k), ("EXAMPLES_MAX_DISTANCE", args.max_distance),
                        ("EXAMPLES_SIMILARITY_GAP", args.gap)):
        if value is not None:
            setattr(planner_mod, attr, value)
    items = json.loads(Path(args.set).read_text())["items"]
    if args.only:
        items = [i for i in items if args.only in i["q"]]
    if args.distances:
        distances(items)
        return
    results = asyncio.run(evaluate(items, args.reps, args.concurrency))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, default=list))
    report(results)


if __name__ == "__main__":
    sys.exit(main())
