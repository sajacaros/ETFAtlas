"""etf_tagging: 대상 고르기, 규칙 분류, LLM 결과 거르기."""
import json

import etf_tagging
from etf_tagging import ETFTagBatchResult


def _vertex(props):
    return json.dumps({"id": 1, "label": "ETF", "properties": props}, ensure_ascii=False) + "::vertex"


def test_split_targets_takes_new_and_manual_etfs():
    rows = [_vertex({"code": "A", "name": "새 ETF"}),
            _vertex({"code": "B", "name": "태깅됨", "tagged_at": "2026-10-01"}),
            _vertex({"code": "C", "name": "수동", "manual_tags": ["우량주"]}),
            _vertex({"name": "코드 없음"}), None, "not json"]
    assert etf_tagging.split_targets(rows, full_rebuild=False) == ({"A": "새 ETF"}, {"C": ["우량주"]}, 1)
    targets, _, skipped = etf_tagging.split_targets(rows, full_rebuild=True)
    assert targets == {"A": "새 ETF", "B": "태깅됨"} and skipped == 0


def test_classify_by_rules_index_then_keywords_then_llm():
    index, keyword, llm = etf_tagging.classify_by_rules({
        "1": "KODEX 200", "2": "TIGER 반도체TOP10", "3": "KODEX K-POP엔터 배당", "4": "TIMEFOLIO 이노베이션액티브"})
    assert index == {"1": "코스피"}
    assert keyword == {"2": ["반도체"], "3": ["엔터", "고배당"]}
    assert llm == {"4": "TIMEFOLIO 이노베이션액티브"}


def test_llm_batch_text_lists_top_holdings():
    text = etf_tagging.llm_batch_text([("A", "에이"), ("B", "비")], {"A": [f"S{i}" for i in range(15)]})
    assert text.splitlines()[0] == "- [A] 에이: " + ", ".join(f"S{i}" for i in range(10))
    assert text.splitlines()[1] == "- [B] 비: 보유종목 정보 없음"


def test_accepted_tags_drop_made_up_codes_and_empty_results():
    result = ETFTagBatchResult.model_validate({"results": [
        {"code": "A", "tags": ["반도체", "AI"]}, {"code": "B", "tags": []}, {"code": "Z", "tags": ["IT"]}]})
    assert etf_tagging.accepted_tags(result, {"A", "B"}) == {"A": ["반도체", "AI"]}


def test_prompt_lists_every_allowed_tag():
    assert all(t in etf_tagging.TAG_SYSTEM_PROMPT for t in etf_tagging.ALLOWED_TAGS)
