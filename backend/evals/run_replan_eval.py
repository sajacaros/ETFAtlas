"""다시 설계 평가: 일부러 틀린 첫 계획을 주고 서비스 흐름(실행 → 다시 설계 → 다시 실행 → 해설)으로 돌려 채점한다.

첫 계획만 정해 두고 다시 설계는 실제 플래너(LLM)가 한다. 백엔드 컨테이너 안에서 돌린다:
  docker cp backend/evals etf-atlas-backend:/tmp/evals
  docker exec -w /app -e PYTHONPATH=/app etf-atlas-backend python /tmp/evals/run_replan_eval.py --reps 3
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List

from app.database import SessionLocal
from app.services.ai_config import load_ai_config
from app.services.chat_memory import ConversationContext
from app.services.answer import planner as planner_mod
from app.services.answer.orchestrator import AnswerService
from app.services.answer.planner import Planner, build_plan_model, to_rows
from app.services.answer.skills import REGISTRY


class _NullStore:
    def create(self, *args):
        pass

    def replace(self, *args):
        pass

    def save(self, *args):
        pass


class GivenPlan:
    """첫 계획은 주어진 것으로, 다시 설계는 실제 플래너로."""

    def __init__(self, rows, real: Planner):
        self.rows, self.real, self.replanned = rows, real, None

    async def plan(self, question, context):
        self.real.last_examples = await self.real._examples(question)  # 다시 설계 프롬프트에 서비스처럼 예시가 들어가게
        return self.rows

    async def replan(self, question, context, rows, results):
        self.replanned = await self.real.replan(question, context, rows, results)
        return self.replanned


async def run_one(item: Dict, config, sem: asyncio.Semaphore) -> Dict:
    async with sem:
        plan = build_plan_model(REGISTRY).model_validate({"rows": [{"slots": row} for row in item["plan"]]})
        given = GivenPlan(to_rows(plan), Planner(config, **planner_mod.data_lookups(SessionLocal)))
        db = SessionLocal()
        try:
            service = AnswerService(db, planner=given)
            service._store = _NullStore()
            events = [e async for e in service.stream(item["q"], ConversationContext(), 0, asyncio.Event())]
        finally:
            db.close()
        status: Dict[str, Dict] = {}
        for e in events:
            if e["type"] == "slot":
                status[e["data"]["id"]] = e["data"]
        replanned = any(e["type"] == "status" and e["data"]["stage"] == "replanning" for e in events)
        final = [s for row in (given.replanned or given.rows) for s in row]
        answer = next((e["data"]["answer"] for e in events if e["type"] == "answer"), "")
        problems = []
        if "replan" in item and replanned != item["replan"]:
            problems.append(f"다시 설계 {'함' if replanned else '안 함'} (기대: {'함' if item['replan'] else '안 함'})")
        for group in item.get("complete", []):
            if not any(s.skill in group.split("|") and status.get(s.id, {}).get("status") == "complete" for s in final):
                problems.append(f"{group} 완료 없음")
        if item.get("message"):
            texts = [d.get("message") or "" for d in status.values()] + [answer]
            if not any(item["message"] in t for t in texts):
                problems.append(f"'{item['message']}' 문구 없음")
        return {
            "q": item["q"], "ok": not problems or item.get("observe"), "observe": item.get("observe", False),
            "problems": problems, "replanned": replanned,
            "slots": [(s.id, s.skill, s.args.model_dump(), status.get(s.id, {}).get("status"), status.get(s.id, {}).get("message"))
                      for s in final],
        }


async def evaluate(items: List[Dict], reps: int, concurrency: int) -> List[Dict]:
    db = SessionLocal()
    config = load_ai_config(db)
    db.close()
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(run_one(item, config, sem) for item in items for _ in range(reps)))


def report(results: List[Dict]) -> None:
    by_q: Dict[str, List[Dict]] = {}
    for r in results:
        by_q.setdefault(r["q"], []).append(r)
    for q, runs in by_q.items():
        ok = sum(r["ok"] for r in runs)
        mark = "관찰" if runs[0]["observe"] else ("OK " if ok == len(runs) else "-- ")
        print(f"{mark} [{ok}/{len(runs)}] {q}")
        for r in runs:
            if r["observe"] or not r["ok"]:
                slots = [(s[1], s[2], s[3], (s[4] or "")[:40]) for s in r["slots"]]
                print(f"      다시 설계 {'O' if r['replanned'] else 'X'} | {'; '.join(r['problems'])} | {slots}"[:400])
    graded = [r for r in results if not r["observe"]]
    print(f"\n== 요약\n  통과 {sum(r['ok'] for r in graded)}/{len(graded)}, 다시 설계한 실행 {sum(r['replanned'] for r in graded)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default=str(Path(__file__).with_name("replan_eval.json")))
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only")
    args = parser.parse_args()
    items = json.loads(Path(args.set).read_text())["items"]
    if args.only:
        items = [i for i in items if args.only in i["q"]]
    report(asyncio.run(evaluate(items, args.reps, args.concurrency)))


if __name__ == "__main__":
    sys.exit(main())
