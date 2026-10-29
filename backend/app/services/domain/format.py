from typing import Any


def format_value(value: Any, fmt: str) -> str:
    """요약 텍스트용 서식 (LLM이 단위를 헷갈리지 않게). 화면 표시 서식은 프런트가 따로 한다."""
    if value is None:
        return "-"
    if fmt == "percent":
        return f"{value:.2f}%"
    if fmt == "krw":
        eok = int(value) // 1_0000_0000
        return f"{eok // 1_0000:,}조 {eok % 1_0000:,}억원" if eok >= 1_0000 else f"{eok:,}억원"
    if fmt == "price":
        return f"{value:,.0f}원"
    if fmt == "number" and isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)
