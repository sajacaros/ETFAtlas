"""주간 매수 의견: 순위, 메시지, 차례 날짜, 회사 소개 정리."""
from datetime import date

from app.domain.opinion import BUY
from app.services import weekly_opinion as wo


def _row(code, verdict=BUY, score=1.0, financials="긍정", market_cap=None, **extra):
    return {"stock_code": code, "name": f"종목{code}", "verdict": verdict, "score": score,
            "chart_rating": "중립", "financials_rating": financials, "report_rating": "다소 긍정",
            "company_type": "지속 성장주", "market_cap": market_cap,
            "reasons": {"chart": ["차트 근거"], "financials": ["재무 근거"], "report": ["보고서 근거"], "check": []},
            **extra}


def test_ranked_keeps_only_buys_by_score_then_financials_then_market_cap():
    rows = [
        _row("000001", score=1.0, financials="다소 긍정", market_cap=900),
        _row("000002", score=1.67),
        _row("000003", score=1.0, financials="긍정", market_cap=100),
        _row("000004", score=1.0, financials="긍정", market_cap=500),
        _row("000005", verdict="지켜본다", score=2.0),
    ]
    assert [r["stock_code"] for r in wo.ranked(rows)] == ["000002", "000004", "000003", "000001"]
    assert len(wo.ranked([_row(f"{i:06d}") for i in range(15)])) == wo.TOP


def test_best_reason_takes_the_best_rated_perspective():
    row = _row("000001", financials="중립", report_rating="긍정")
    assert wo.best_reason(row) == "보고서 근거"
    assert wo.best_reason({**row, "reasons": {}}) is None


def test_format_report_marks_new_entries_and_counts_verdicts():
    rows = [_row("000001", score=1.33), _row("000002", score=1.0), _row("000003", verdict="지켜본다", score=0.3)]
    picks = wo.ranked(rows)
    text = "\n\n".join(wo.format_report(date(2026, 10, 31), rows, picks, {"000001": "메모리 반도체 기업"}, {"000002"}))
    assert "ETF가 담은 주식 3종목" in text and "사 볼 만하다 2 · 지켜본다 1" in text
    assert "**1. 종목000001** `000001` +1.3점 🆕\n메모리 반도체 기업\n차트 중립 · 재무 긍정 · 보고서 다소 긍정 | 지속 성장주" in text
    assert "**2. 종목000002** `000002` +1.0점\n" in text
    first_run = "\n\n".join(wo.format_report(date(2026, 10, 31), rows, picks, {}, None))
    assert "🆕" not in first_run


def test_format_report_without_buys_says_so():
    rows = [_row("000001", verdict="지켜본다", score=0.0)]
    text = "\n\n".join(wo.format_report(date(2026, 10, 31), rows, [], {}, None))
    assert "'사 볼 만하다' 종목이 없습니다" in text


def test_chunk_keeps_blocks_whole_under_the_limit():
    messages = wo.chunk(["a" * 60, "b" * 60, "c" * 60, "d" * 300], limit=130)
    assert messages == ["a" * 60 + "\n\n" + "b" * 60, "c" * 60, "d" * 129 + "…"]


def test_tagline_comes_from_the_business_section_and_fits_50_chars():
    overview = "#### 사업 구조\n- 메모리 반도체를 만든다\n\n#### 이번 기간 영업 상황\n- 매출 증가"
    assert wo.business_section(overview) == "- 메모리 반도체를 만든다"
    assert wo.clean_tagline('"메모리 반도체 기업"\n덧붙인 말') == "메모리 반도체 기업"
    long = wo.clean_tagline("가" * 80)
    assert len(long) == wo.TAGLINE_CHARS and long.endswith("…")
