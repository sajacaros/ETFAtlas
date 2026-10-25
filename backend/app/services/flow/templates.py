"""추천 조합: 팔레트에서 골라 캔버스에 바로 불러오는 흐름. 그래프 형식은 저장된 흐름과 같다."""
from typing import Any, Dict, List, Tuple


def _graph(nodes: List[Tuple[str, str, Dict[str, Any], int, int]], edges: List[Tuple[str, str]]) -> Dict[str, Any]:
    return {
        "nodes": [{"id": i, "type": t, "params": p, "position": {"x": x, "y": y}} for i, t, p, x, y in nodes],
        "edges": [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in edges],
    }


TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "basic",
        "name": "기본 스크리닝",
        "description": "전체 종목 → 정배열·고가 근처 → AI 근거 → 결과",
        "graph": _graph(
            [
                ("src", "source", {"mode": "all"}, 0, 120),
                ("chart", "chart_filter", {"ma_aligned": True, "near_high_pct": 10}, 280, 120),
                ("ai", "ai_analysis", {"max_stocks": 10}, 560, 120),
                ("out", "result", {"sort_by": "ret"}, 840, 120),
            ],
            [("src", "chart"), ("chart", "ai"), ("ai", "out")],
        ),
    },
    {
        "key": "double_check",
        "name": "이중 확인 교집합",
        "description": "추세(정배열)와 거래량(1.5배, 20일 수익률 ≥ 0) 조건을 따로 걸러 둘 다 통과한 종목만",
        "graph": _graph(
            [
                ("src", "source", {"mode": "all"}, 0, 160),
                ("trend", "chart_filter", {"ma_aligned": True}, 280, 40),
                ("volume", "chart_filter", {"volume_ratio_min": 1.5, "return_min": 0}, 280, 280),
                ("both", "combine", {"op": "intersection"}, 560, 160),
                ("out", "result", {"sort_by": "vol_ratio"}, 840, 160),
            ],
            [("src", "trend"), ("src", "volume"), ("trend", "both"), ("volume", "both"), ("both", "out")],
        ),
    },
    {
        "key": "vcp",
        "name": "변동성 수축",
        "description": "간이 VCP 종목을 찾아 AI로 근거 정리",
        "graph": _graph(
            [
                ("src", "source", {"mode": "all"}, 0, 120),
                ("chart", "chart_filter", {"vcp": True}, 280, 120),
                ("ai", "ai_analysis", {"max_stocks": 10, "focus": "trend"}, 560, 120),
                ("out", "result", {"sort_by": "from_high"}, 840, 120),
            ],
            [("src", "chart"), ("chart", "ai"), ("ai", "out")],
        ),
    },
    {
        "key": "pullback",
        "name": "상승 추세 속 눌림목",
        "description": "60일 이평 위에 있으면서 스토캐스틱이 과매도(20 이하)에서 3거래일 안에 골든크로스한 종목 → AI 근거",
        "graph": _graph(
            [
                ("src", "source", {"mode": "all"}, 0, 120),
                ("chart", "chart_filter", {"above_ma": 60, "stoch_cross_days": 3, "stoch_cross_below": 20}, 280, 120),
                ("ai", "ai_analysis", {"max_stocks": 10, "focus": "trend"}, 560, 120),
                ("out", "result", {"sort_by": "stoch_cross", "descending": False}, 840, 120),
            ],
            [("src", "chart"), ("chart", "ai"), ("ai", "out")],
        ),
    },
    {
        "key": "portfolio_risk",
        "name": "내 포트폴리오 과열 점검",
        "description": "내 포트폴리오가 담은 종목 중 RSI 70 이상을 위험 관점으로",
        "graph": _graph(
            [
                ("src", "source", {"mode": "portfolio"}, 0, 120),
                ("chart", "chart_filter", {"rsi_min": 70}, 280, 120),
                ("ai", "ai_analysis", {"max_stocks": 10, "focus": "risk"}, 560, 120),
                ("out", "result", {"sort_by": "rsi"}, 840, 120),
            ],
            [("src", "chart"), ("chart", "ai"), ("ai", "out")],
        ),
    },
    {
        "key": "active_buy",
        "name": "액티브 ETF 매수 종목",
        "description": "최근 5개 공시일에 액티브 ETF 2개 이상이 새로 담거나 비중을 늘린 종목 중 20일 이평 위 → AI 근거",
        "graph": _graph(
            [
                ("src", "source", {"mode": "all"}, 0, 120),
                ("signal", "etf_signal", {"active": "buy", "days": 5, "min_change": 0.5, "min_active_etfs": 2}, 280, 120),
                ("chart", "chart_filter", {"above_ma": 20}, 560, 120),
                ("ai", "ai_analysis", {"max_stocks": 10}, 840, 120),
                ("out", "result", {"sort_by": "active_change"}, 1120, 120),
            ],
            [("src", "signal"), ("signal", "chart"), ("chart", "ai"), ("ai", "out")],
        ),
    },
]
