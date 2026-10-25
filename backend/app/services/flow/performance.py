"""흐름 채점: 기록된 날마다 고른 종목을 똑같은 금액으로 샀다면 N거래일 뒤 KODEX 200보다 나았는지.

- 진입: 기록한 날 **다음 거래일 종가**. 장중에 돌렸거나 그날 종가를 보고 골랐더라도 미래 값을 쓰지 않는다.
- 청산: 진입일에서 N거래일 뒤 종가. 거래일 달력은 기준 지수(KODEX 200)의 일봉 날짜를 쓴다.
- 그날 종가가 없는 종목(거래정지·시세 없음)은 그 기간 계산에서 뺀다.
- 수익률·초과수익은 단순 평균(동일 비중), 적중률은 기준 지수보다 많이 오른 종목 비율.
- 이긴·진 종목의 평균 초과수익을 따로 내서, 적중률이 낮아도 크게 이기는지(손익비)를 본다.
- 매일 기록하면 기간이 겹치므로 기록 수만큼 독립적인 표본은 아니다.
"""
from bisect import bisect_right
from typing import Any, Dict, List, Optional

from .market_data import MarketData

BENCHMARK = {"code": "069500", "name": "KODEX 200"}
HORIZONS = (5, 20, 60)
MAX_RUNS = 120  # 최근 기록만 채점한다 (시세가 1년치)


def _closes(bars: List[Dict[str, Any]]) -> Dict[str, float]:
    return {b["date"]: b["close"] for b in bars}


def score_run(picks: List[Dict[str, str]], run_date: str, calendar: List[str],
              bench: Dict[str, float], closes: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    """기록 하나의 채점. horizons[N]은 아직 N거래일이 지나지 않았으면 None, so_far는 지금까지."""
    start = bisect_right(calendar, run_date)  # 기록한 날 다음 거래일
    out: Dict[str, Any] = {"entry_date": calendar[start] if start < len(calendar) else None, "horizons": {}, "so_far": None}
    if start >= len(calendar):
        return out

    def measure(end: int) -> Optional[Dict[str, Any]]:
        entry_day, exit_day = calendar[start], calendar[end]
        b0, b1 = bench.get(entry_day), bench.get(exit_day)
        if not b0 or not b1:
            return None
        bench_ret = (b1 / b0 - 1) * 100
        rets = []
        for p in picks:
            c = closes.get(p["code"], {})
            if c.get(entry_day) and c.get(exit_day):
                rets.append((c[exit_day] / c[entry_day] - 1) * 100)
        if not rets:
            return None
        avg = sum(rets) / len(rets)
        won = [r - bench_ret for r in rets if r > bench_ret]
        lost = [r - bench_ret for r in rets if r <= bench_ret]
        return {
            "exit_date": exit_day,
            "ret": round(avg, 2),
            "bench": round(bench_ret, 2),
            "excess": round(avg - bench_ret, 2),
            "hit": round(len(won) / len(rets) * 100, 1),
            "n": len(rets),
            "won": round(sum(won) / len(won), 2) if won else None,  # 이긴 종목의 평균 초과수익
            "lost": round(sum(lost) / len(lost), 2) if lost else None,  # 진 종목의 평균 초과수익 (0 이하)
        }

    for h in HORIZONS:
        out["horizons"][h] = measure(start + h) if start + h < len(calendar) else None
    if len(calendar) - 1 > start:
        out["so_far"] = measure(len(calendar) - 1)
    return out


def summarize(scored: List[Dict[str, Any]]) -> Dict[int, Optional[Dict[str, Any]]]:
    """기간별로 다 채점된 기록만 평균한다."""
    summary: Dict[int, Optional[Dict[str, Any]]] = {}
    for h in HORIZONS:
        done = [s["horizons"][h] for s in scored if s["horizons"].get(h)]
        if not done:
            summary[h] = None
            continue
        mean = lambda key: round(sum(d[key] for d in done) / len(done), 2)  # noqa: E731
        won = [d["won"] for d in done if d.get("won") is not None]
        lost = [d["lost"] for d in done if d.get("lost") is not None]
        won_avg = round(sum(won) / len(won), 2) if won else None
        lost_avg = round(sum(lost) / len(lost), 2) if lost else None
        summary[h] = {
            "runs": len(done),
            "ret": mean("ret"),
            "excess": mean("excess"),
            "hit": mean("hit"),
            "beat_runs": round(sum(d["excess"] > 0 for d in done) / len(done) * 100, 1),  # 지수를 이긴 기록 비율
            "won": won_avg,
            "lost": lost_avg,
            "payoff": round(won_avg / -lost_avg, 2) if won_avg is not None and lost_avg else None,  # 손익비
            "worst": min(d["excess"] for d in done),  # 가장 나빴던 기록의 초과수익
        }
    return summary


def evaluate(runs: List[Dict[str, Any]], market: MarketData) -> Dict[str, Any]:
    """runs: [{run_date: 'YYYY-MM-DD', trigger, picks}] 최신순."""
    runs = runs[:MAX_RUNS]
    codes = {p["code"] for r in runs for p in r["picks"]}
    bars = market.bars([BENCHMARK["code"], *sorted(codes)])
    bench = _closes(bars.get(BENCHMARK["code"], []))
    calendar = sorted(bench)
    closes = {c: _closes(b) for c, b in bars.items()}
    scored = []
    for r in runs:
        s = score_run(r["picks"], r["run_date"], calendar, bench, closes) if calendar else {"entry_date": None, "horizons": {}, "so_far": None}
        scored.append({"run_date": r["run_date"], "trigger": r["trigger"], "count": len(r["picks"]), **s})
    return {
        "benchmark": BENCHMARK,
        "horizons": list(HORIZONS),
        "as_of": calendar[-1] if calendar else None,
        "summary": summarize(scored),
        "runs": scored,
    }
