"""DART 정기보고서 원문(document.xml) → 해설에 쓸 서술형 장(章)만 뽑은 텍스트.

정기보고서는 목차가 서식으로 정해져 있다 (I. 회사의 개요 … XII. 상세표). 오픈소스 DART 분석 에이전트들이
공통으로 읽는 장을 따른다 — 숫자는 주요계정 API가 정확히 주므로 재무제표 본문은 읽지 않는다.
  II. 사업의 내용            사업 구조·제품별 매출 비중·위험관리·연구개발 (모든 보고서)
  IV. 이사의 경영진단 및 분석의견   경영진의 실적 설명 (사업보고서만. 분·반기는 "기재하지 않음")
  XI. 그 밖에 투자자 보호     공시 진행사항·우발부채·제재·작성기준일 이후 주요사항
  주석의 영업부문            부문별 매출·이익 (연결이 있으면 연결)
"""
import html
import io
import re
import zipfile
from dataclasses import dataclass
from typing import List, Optional

import httpx

DART_API_BASE = "https://opendart.fss.or.kr/api"

CHAPTERS = ("II.", "IV.", "XI.")
SEGMENT_NOTE = "영업부문"
MIN_SECTION = 100  # 이보다 짧은 장은 빈 서식("해당사항 없음", "기재하지 않습니다")이다
# 모델 입력 상한. 대형주의 사업의 내용은 3~4만 자, '기타 참고사항'은 혼자 2만 자 가까이 된다
SECTION_CHARS = 6000
TOTAL_CHARS = 36000

_TITLE = re.compile(r'<(TITLE|COVER-TITLE)\b[^>]*ATOC="Y"[^>]*>(.*?)</\1>', re.S)
_CHAPTER = re.compile(r"^[IVX]+\.")
_CELL = re.compile(r"<(TD|TH|TE|TU)\b[^>]*>(.*?)</\1>", re.S)


@dataclass
class Section:
    path: str  # "II. 사업의 내용 > 4. 매출 및 수주상황"
    text: str


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _table_to_text(table: str) -> str:
    """표 한 행 → '셀 | 셀 | 셀' 한 줄. 매출 비중·부문 실적이 표로만 나오는 경우가 많아 버리지 않는다."""
    rows = []
    for tr in re.findall(r"<TR\b[^>]*>(.*?)</TR>", table, re.S):
        cells = [_clean(m.group(2)) for m in _CELL.finditer(tr)]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def to_text(fragment: str) -> str:
    fragment = re.sub(r"<TABLE\b[^>]*>.*?</TABLE>", lambda m: "\n" + _table_to_text(m.group(0)) + "\n",
                      fragment, flags=re.S)
    fragment = re.sub(r"</P>|<BR\s*/?>|</TR>|<P\b[^>]*>", "\n", fragment)
    lines = (_clean(line) for line in fragment.split("\n"))
    return "\n".join(line for line in lines if line)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[:cut if cut > limit // 2 else limit] + "\n(…이하 생략)"


def extract_sections(xml: str) -> List[Section]:
    """읽을 장의 소제목별 텍스트 (문서 순서). 소제목이 없는 장(예: VII.)은 장 전체가 한 덩어리."""
    titles = list(_TITLE.finditer(xml))
    chapter = ""
    picked: List[Section] = []
    notes: List[Section] = []  # 영업부문 주석: (연결)이 있으면 그것만
    for i, m in enumerate(titles):
        title = _clean(m.group(2))
        if _CHAPTER.match(title):
            chapter = title
        end = titles[i + 1].start() if i + 1 < len(titles) else len(xml)
        text = to_text(xml[m.end():end])
        if len(text) < MIN_SECTION:
            continue
        if chapter.startswith(CHAPTERS):
            path = chapter if title == chapter else f"{chapter} > {title}"
            picked.append(Section(path, _clip(text, SECTION_CHARS)))
        elif chapter.startswith("III.") and SEGMENT_NOTE in title:
            notes.append(Section(f"재무제표 주석 > {title}", _clip(text, SECTION_CHARS)))
    consolidated = [n for n in notes if "(연결)" in n.path]
    sections = picked + (consolidated or notes)[:1]
    total, kept = 0, []
    for s in sections:
        if total + len(s.text) > TOTAL_CHARS:
            break
        kept.append(s)
        total += len(s.text)
    return kept


def parse_document(zip_bytes: bytes) -> str:
    """document.xml zip → 본문 XML. 첨부(감사보고서 등)가 같이 오면 가장 큰 파일이 본문이다."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise ValueError("원문 zip에 XML이 없습니다")
        main = max(names, key=lambda n: zf.getinfo(n).file_size)
        raw = zf.read(main)
    for encoding in ("utf-8", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_document(api_key: str, rcept_no: str) -> str:
    res = httpx.get(f"{DART_API_BASE}/document.xml", params={"crtfc_key": api_key, "rcept_no": rcept_no}, timeout=60)
    res.raise_for_status()
    if not res.content.startswith(b"PK"):  # zip 대신 오류(JSON/XML)가 왔다
        raise ValueError(f"DART 원문을 받지 못했습니다: {_error_message(res.text)}")
    return parse_document(res.content)


def _error_message(body: str) -> str:
    message: Optional[re.Match] = re.search(r"<message>(.*?)</message>", body) or re.search(r'"message"\s*:\s*"([^"]*)"', body)
    return message.group(1) if message else body[:200]
