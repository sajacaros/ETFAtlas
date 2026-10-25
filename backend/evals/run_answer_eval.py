"""답변 전체 평가: 질문마다 재작성 없이 설계 → 슬롯 실행 → (다시 설계) → 해설까지 실제로 돌려 화면 결과를 모은다.

채점은 사람이 한다 — 체이닝·병합처럼 계획 모양만으로는 맞는지 알 수 없는 질문을 실제 결과로 본다.
실제 LLM·임베딩·DB를 쓴다. 백엔드 컨테이너 안에서 돌린다:
  docker cp backend/evals etf-atlas-backend:/tmp/evals
  docker exec -w /app -e PYTHONPATH=/app etf-atlas-backend python /tmp/evals/run_answer_eval.py --json /tmp/answer.json
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from app.database import SessionLocal
from app.services.chat_memory import ConversationContext
from app.services.ai_config import load_ai_config
from app.services.answer.orchestrator import AnswerService
from app.services.answer.planner import Planner, data_lookups


class _NullStore:
    def create(self, *args):
        pass

    def replace(self, *args):
        pass

    def save(self, *args):
        pass

    def split(self, *args):  # 스킬이 영역을 나눌 때 (company_report의 매출 구성 차트 등)
        pass


class RecordingPlanner(Planner):
    """세운 계획(처음·다시 설계)을 모두 남긴다 — 화면 레이아웃 이벤트에는 스킬·인자가 없다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plans: List[List[Dict]] = []

    def _record(self, rows):
        if rows:
            self.plans.append([{"id": s.id, "skill": s.skill, "title": s.title, "display": s.display,
                                "args": s.args.model_dump()} for row in rows for s in row])
        return rows

    async def plan(self, question, context):
        return self._record(await super().plan(question, context))

    async def replan(self, question, context, rows, results):
        return self._record(await super().replan(question, context, rows, results))


async def run_one(item: Dict, sem: asyncio.Semaphore) -> Dict:
    async with sem:
        db = SessionLocal()
        started = time.monotonic()
        slots, answer, result, stages = {}, "", "", []
        planner = RecordingPlanner(load_ai_config(db), **data_lookups(SessionLocal))
        try:
            service = AnswerService(db, planner=planner)
            service._store = _NullStore()
            async for event in service.stream(item["q"], ConversationContext(), 0, asyncio.Event(), refine=False):
                kind, data = event["type"], event["data"]
                if kind == "status":
                    stages.append(data["stage"])
                elif kind == "slot" and data["status"] != "running":
                    slots[data["id"]] = {"status": data["status"], "message": data.get("message")}
                elif kind == "answer":
                    answer, result = data["answer"], data["result"]
        except Exception as e:  # 하네스가 멈추지 않게 실패로 남긴다
            answer, result = f"{type(e).__name__}: {e}", "error"
        finally:
            db.close()
        return {"id": item["id"], "group": item["group"], "q": item["q"], "seconds": round(time.monotonic() - started, 1),
                "stages": stages, "plans": planner.plans, "slots": slots, "result": result, "answer": answer}


async def evaluate(items: List[Dict], reps: int, concurrency: int) -> List[Dict]:
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(run_one(item, sem) for item in items for _ in range(reps)))


def report(results: List[Dict]) -> None:
    for r in results:
        print(f"\n===== [{r['id']}] {r['q']}  ({r['result']}, {r['seconds']}s, {' → '.join(r['stages'])})")
        for i, plan in enumerate(r["plans"]):
            print(f"  plan{i}:")
            for s in plan:
                outcome = r["slots"].get(s["id"], {})
                msg = f" — {outcome['message']}" if outcome.get("message") else ""
                print(f"    {s['id']} {s['skill']}/{s['display']} {json.dumps(s['args'], ensure_ascii=False)}"
                      f" → {outcome.get('status', '-')}{msg}")
        print("  answer: " + r["answer"].replace("\n", "\n          ")[:1500])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default=str(Path(__file__).with_name("answer_eval.json")))
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only", help="쉼표로 구분한 항목 id만")
    parser.add_argument("--json", help="실행 결과를 이 파일에 저장")
    args = parser.parse_args()
    items = json.loads(Path(args.set).read_text())["items"]
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]
    results = asyncio.run(evaluate(items, args.reps, args.concurrency))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1))
    report(results)


if __name__ == "__main__":
    sys.exit(main())
