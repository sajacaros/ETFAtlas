"""DART 정기보고서 원문(document.xml) → 목차 트리 (PageIndex 방식의 색인).

정기보고서는 목차가 서식으로 정해져 있고, 원문 XML이 장·절을 SECTION-1/2/3으로 감싸고 제목에 ATOC="Y"를 단다.
그래서 트리는 LLM 없이 원문 구조로 만든다. 노드마다 본문을 블록(소제목·문단·표)으로 나눠 두고,
읽을 때 마크다운으로 바꿔 LLM에 넘긴다 — 저장은 구조, 읽기는 그때그때 렌더링.
  - 표는 병합 셀(ROWSPAN·COLSPAN)을 풀어 열마다 머리말을 붙인다. 표 위의 작은 표('[연구개발비용]', '(단위 : 백만원)')는
    캡션·단위로 다음 표에 붙인다.
  - 8천 자가 넘는 절은 '가.', '나.' 소제목에서 하위 노드로 나눈다 (목차에서 더 깊이 고를 수 있게).
  - 목차 색인(노드 요약)은 등록된 LLM이 Airflow(dart_report_index)에서 붙인다. 이 모듈은 stdlib만 쓴다 —
    Airflow와 백엔드가 같이 import한다.
"""
import hashlib
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PARSER_VERSION = 1

SPLIT_CHARS = 8000  # 이보다 긴 절은 '가.' 소제목에서 하위 노드로 나눈다
SUMMARY_MIN_CHARS = 100  # 이보다 짧은 절은 빈 서식("해당사항 없음")이라 요약하지 않는다
SUMMARY_INPUT_CHARS = 8000  # 노드 요약 입력 상한 (소제목·표 제목 목록 + 본문 앞부분)
SUMMARY_HEADINGS_CHARS = 4000
TABLE_ROWS = 40  # 읽을 때 큰 표는 이만큼만 (질문 키워드에 맞는 행은 따로 고른다)

# 제목만으로 충분해 요약하지 않는 절: 재무제표 본표(2-1. 연결 재무상태표 …), XII 상세표
NO_SUMMARY = re.compile(r"^III\. [^>]+> \d\. (연결)?재무제표 > |^XII\. ")
# '1. 대주주와의 영업거래', '가. 등기임원', '(1) 매출실적', '1) 연구개발비용', '[연구개발비용]', '<주요 계약>', '① …'
HEADING = re.compile(r"^(\d{1,2}\.\s|\[[^\]]{2,40}\]|<[^>]{2,40}>|[가-하]\.\s|\(\d{1,2}\)\s?|\d{1,2}\)\s|[①-⑳]|【)")
SPLIT_HEADING = re.compile(r"^[가-하]\.\s")
HEADING_CHARS = 60

_TOKEN = re.compile(r'<(/?)SECTION-(\d)\b[^>]*>|<(TITLE|COVER-TITLE)\b([^>]*)>(.*?)</\3>', re.S)
_TABLE_TAG = re.compile(r"<(/?)TABLE\b[^>]*>")
_ROW = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.S)
_CELL = re.compile(r"<(TD|TH|TE|TU)\b([^>]*)>(.*?)</\1>", re.S)
_THEAD = re.compile(r"<THEAD\b[^>]*>(.*?)</THEAD>", re.S)
_UNIT = re.compile(r"단위\s*[:：]\s*([^)\]]+)")
_NUMERIC = re.compile(r"^[△\-(]?[\d,.]+\)?%?$")
_TOTAL_ROW = re.compile(r"^(합\s*계|총\s*계|소\s*계|계|total)", re.I)

# "반기보고서 (2026.06)", "[기재정정]사업보고서 (2025.12)" — 정정이 나오면 정정본이 완전한 최신 보고서다
PERIODIC = re.compile(r"^(?:\[([^\]]*)\]\s*)?(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)")
REPORT_LABEL = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
REPORT_MONTH = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
# 공시 제목은 1·3분기를 모두 '분기보고서'라 쓴다. 보고서 코드가 없으면 기간 끝 달로 가린다 (12월 결산 기준)
QUARTER_BY_MONTH = {"03": "1분기보고서", "09": "3분기보고서"}
# 첨부(감사보고서 등)만 고치거나 더한 공시. 본문은 원래 보고서 그대로라 원래 보고서를 색인한다
# (DART가 이런 접수번호에는 원문을 주지 않기도 한다 — 상태 014 '파일이 존재하지 않습니다')
ATTACHMENT_ONLY = ("첨부정정", "첨부추가")
# 보고서는 기간이 끝나고 길어야 3개월 안에 낸다. 기간이 그보다 오래됐으면 뒤늦게 낸 정정본이라도 색인하지 않는다
PERIOD_GRACE_DAYS = 92


# --- 보고서 이름 ---

def report_name(title: Optional[str], bsns_year: Optional[int] = None, reprt_code: Optional[str] = None) -> str:
    """'2026년 반기보고서', '2026년 1분기보고서', '2025년 사업보고서 (기재정정)'. 보고서 종류는 주요계정의 보고서 코드를 먼저 믿는다."""
    m = PERIODIC.match(title) if title else None
    if bsns_year and reprt_code in REPORT_LABEL:
        name = f"{bsns_year}년 {REPORT_LABEL[reprt_code]}"
    elif m:
        kind = f"{m.group(2)}보고서" if m.group(2) != "분기" else QUARTER_BY_MONTH.get(m.group(4), "분기보고서")
        name = f"{m.group(3)}년 {kind}"
    else:
        name = "정기보고서"
    return f"{name} ({m.group(1)})" if m and m.group(1) else name


def report_period(title: Optional[str], bsns_year: Optional[int] = None, reprt_code: Optional[str] = None) -> Optional[str]:
    """보고서 기간 'YYYY.MM'. 정정보고서는 원래 보고서와 기간이 같다 — 같은 기간의 옛 접수번호를 정리하는 기준."""
    m = PERIODIC.match(title) if title else None
    if m:
        return f"{m.group(3)}.{m.group(4)}"
    if bsns_year and reprt_code in REPORT_MONTH:
        return f"{bsns_year}.{REPORT_MONTH[reprt_code]}"
    return None


def filed_date(rcept_no: str) -> date:
    return date(int(rcept_no[:4]), int(rcept_no[4:6]), int(rcept_no[6:8]))


def period_end(period: str) -> date:
    """'2026.06' → 2026-06-30"""
    year, month = int(period[:4]), int(period[5:7])
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def stale_period(period: Optional[str], since: date) -> bool:
    """색인 범위(since 이후 접수)에 들 수 없는 오래된 기간인가 — 접수일은 최근이어도 옛 기간을 정정한 보고서."""
    return bool(period) and period_end(period) < since - timedelta(days=PERIOD_GRACE_DAYS)


def attachment_only(name: Optional[str]) -> bool:
    """공시 제목('[첨부정정]반기보고서 …')이나 보고서 이름('… (첨부정정)')이 첨부만 바꾼 공시인가."""
    return bool(name) and any(f"[{kind}]" in name or f"({kind})" in name for kind in ATTACHMENT_ONLY)


def latest_reports(financials: Iterable[tuple], disclosures: Iterable[tuple], since: date,
                   exclude: Iterable[str] = ()) -> List[tuple]:
    """색인할 보고서 (접수번호, 종목코드, 보고서 이름, 기간): since 이후 접수, 같은 종목·기간이면 가장 최근 접수(정정본)만.
    financials: (종목, 접수번호, 사업연도, 보고서 코드) — 주요계정, disclosures: (종목, 접수번호, 공시 제목) — 공시 목록.
    첨부만 바꾼 공시, 옛 기간의 정정본, exclude(원문이 없던 접수번호)는 빼서 같은 기간의 그 전 접수가 남게 한다."""
    skip = set(exclude)
    found: Dict[str, Dict[str, Any]] = {}
    for stock_code, rcept_no, bsns_year, reprt_code in financials:
        found.setdefault(rcept_no, {"stock_code": stock_code}).update(bsns_year=bsns_year, reprt_code=reprt_code)
    for stock_code, rcept_no, title in disclosures:
        if attachment_only(title):
            skip.add(rcept_no)
        elif PERIODIC.match(title):
            found.setdefault(rcept_no, {"stock_code": stock_code})["title"] = title
    latest: Dict[tuple, tuple] = {}
    for rcept_no, r in found.items():
        if rcept_no in skip or filed_date(rcept_no) < since:
            continue
        args = (r.get("title"), r.get("bsns_year"), r.get("reprt_code"))
        period = report_period(*args)
        if stale_period(period, since):
            continue
        key = (r["stock_code"], period or rcept_no)
        if key not in latest or latest[key][0] < rcept_no:
            latest[key] = (rcept_no, r["stock_code"], report_name(*args), period)
    return sorted(latest.values())


# --- 원문 ---

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


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# --- 블록 ---

@dataclass
class Block:
    kind: str  # heading | para | table
    text: str = ""
    table: Optional[Dict[str, Any]] = None  # {caption, unit, header: [열 머리말], rows: [[셀]]}

    def to_json(self) -> Dict[str, Any]:
        return {"kind": self.kind, "text": self.text} if self.table is None else {"kind": self.kind, "table": self.table}

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "Block":
        return Block(d["kind"], d.get("text", ""), d.get("table"))


def _span(attrs: str, name: str) -> int:
    m = re.search(rf'{name}="(\d+)"', attrs)
    return max(int(m.group(1)), 1) if m else 1


def _grid(rows_xml: Iterable[str], fill_colspan: bool) -> List[List[str]]:
    """TR 목록 → 병합을 푼 격자. ROWSPAN은 아래 행에 같은 값을 채운다 (행만 떼어 읽어도 뜻이 통하게).
    COLSPAN은 머리말이면 같은 값을, 본문이면 빈 칸을 채운다."""
    grid: List[List[Optional[str]]] = []
    pending: Dict[Tuple[int, int], str] = {}  # (행, 열) → 위에서 내려온 값
    for r, tr in enumerate(rows_xml):
        row: List[Optional[str]] = []
        col = 0

        def fill_pending():
            nonlocal col
            while (r, col) in pending:
                row.append(pending.pop((r, col)))
                col += 1

        for m in _CELL.finditer(tr):
            fill_pending()
            text = _clean(m.group(3))
            rowspan, colspan = _span(m.group(2), "ROWSPAN"), _span(m.group(2), "COLSPAN")
            for k in range(colspan):
                value = text if (k == 0 or fill_colspan) else ""
                row.append(value)
                for down in range(1, rowspan):
                    pending[(r + down, col)] = value
                col += 1
        fill_pending()
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    return [[c or "" for c in r] + [""] * (width - len(r)) for r in grid]


def _header_labels(header_rows: List[List[str]], width: int) -> List[str]:
    """여러 줄 머리말 → 열마다 한 줄. 같은 말이 겹치면 한 번만, 아래 세 단계만 남긴다 ('보고부문 / DX 부문 / 3개월').
    두 단계만 남기면 '내부거래 조정 등 / 부문 합계 / 3개월'의 '내부거래 조정 등'이 빠져 조정 열이 합계로 읽힌다."""
    labels = []
    for c in range(width):
        parts: List[str] = []
        for row in header_rows:
            cell = row[c] if c < len(row) else ""
            if cell and (not parts or parts[-1] != cell):
                parts.append(cell)
        labels.append(" / ".join(parts[-3:]))
    return labels


def _is_caption_table(grid: List[List[str]]) -> bool:
    """표 위의 '[연구개발비용] | (단위 : 백만원)' 같은 작은 표 — 숫자 칸 없이 두 줄 이하."""
    cells = [c for row in grid for c in row if c]
    return 0 < len(grid) <= 2 and 0 < len(cells) <= 4 and sum(map(len, cells)) <= 120 \
        and not any(_NUMERIC.match(c) for c in cells)


def parse_table(table_xml: str) -> Optional[Dict[str, Any]]:
    head = _THEAD.search(table_xml)
    head_rows = _ROW.findall(head.group(1)) if head else []
    body_xml = table_xml[:head.start()] + table_xml[head.end():] if head else table_xml
    body_rows = _ROW.findall(body_xml)
    if not head_rows and body_rows and all(m.group(1) == "TH" for m in _CELL.finditer(body_rows[0])):
        head_rows, body_rows = body_rows[:1], body_rows[1:]  # THEAD 없이 TH로만 된 첫 줄
    header_grid = _grid(head_rows, fill_colspan=True)
    rows = [r for r in _grid(body_rows, fill_colspan=False) if any(r)]
    width = max([len(r) for r in rows] + [len(r) for r in header_grid] + [0])
    if not width:
        return None
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = _header_labels(header_grid, width) if header_grid else []
    # 머리말이 왼쪽 열과 같고 본문이 모두 빈 열은 COLSPAN의 흔적이다
    keep = [c for c in range(width)
            if not (c > 0 and header and header[c] == header[c - 1] and all(not r[c] for r in rows))]
    return {"caption": None, "unit": None, "header": [header[c] for c in keep] if header else [],
            "rows": [[r[c] for c in keep] for r in rows]}


def _text_blocks(fragment: str) -> List[Block]:
    # 표를 담은 틀의 칸(</TD> 등)도 줄을 나눈다
    fragment = re.sub(r"</P>|<BR\s*/?>|<P\b[^>]*>|</(TD|TH|TE|TU|TR)>", "\n", fragment)
    blocks: List[Block] = []
    para: List[str] = []
    for line in (_clean(x) for x in fragment.split("\n")):
        if not line:
            continue
        if len(line) <= HEADING_CHARS and " | " not in line and HEADING.match(line):
            if para:
                blocks.append(Block("para", "\n".join(para)))
                para = []
            blocks.append(Block("heading", line))
        else:
            para.append(line)
    if para:
        blocks.append(Block("para", "\n".join(para)))
    return blocks


def _top_tables(fragment: str) -> List[Tuple[int, int, bool]]:
    """가장 바깥 표의 (시작, 끝, 안에 표가 있는지). 주석은 표 안에 표를 넣는다 (XBRL 서식)."""
    spans, depth, start, nested = [], 0, 0, False
    for m in _TABLE_TAG.finditer(fragment):
        if m.group(1):
            depth -= 1
            if depth == 0:
                spans.append((start, m.end(), nested))
            depth = max(depth, 0)
        else:
            if depth == 0:
                start, nested = m.start(), False
            else:
                nested = True
            depth += 1
    return spans


def parse_blocks(fragment: str) -> List[Block]:
    """노드 본문 XML → 블록. 캡션 표는 다음 표의 caption·unit이 된다."""
    blocks: List[Block] = []
    caption: List[str] = []
    pos = 0
    for start, end, nested in _top_tables(fragment):
        text = _text_blocks(fragment[pos:start])
        if text:
            caption = []  # 캡션 표와 본 표 사이에 문장이 있으면 캡션이 아니다
        blocks += text
        pos = end
        table_xml = fragment[start:end]
        if nested:  # 표를 담은 틀 — 틀의 칸은 문단으로, 안의 표는 표로
            inner = table_xml[table_xml.index(">") + 1:table_xml.rindex("<")]
            blocks += parse_blocks(inner)
            caption = []
            continue
        grid = _grid(_ROW.findall(table_xml), fill_colspan=False)
        if _is_caption_table(grid):
            caption += [c for row in grid for c in row if c]
            continue
        table = parse_table(table_xml)
        if table is None:
            continue
        if len(table["header"]) <= 1 and all(len(r) == 1 for r in table["rows"]):  # 한 칸짜리 표는 문단이다
            blocks += [Block("para", "\n".join(x for x in [*table["header"], *(r[0] for r in table["rows"])] if x))]
            caption = []
            continue
        if caption:
            words = " ".join(caption)
            unit = _UNIT.search(words)
            table["unit"] = unit.group(1).strip() if unit else None
            table["caption"] = words
            caption = []
        blocks.append(Block("table", table=table))
    if caption:
        blocks.append(Block("para", " ".join(caption)))
    blocks += _text_blocks(fragment[pos:])
    return blocks


# --- 렌더링 ---

def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def _table_rows(table: Dict[str, Any], keywords: Sequence[str], max_rows: int) -> Tuple[List[List[str]], Optional[str]]:
    rows = table["rows"]
    if len(rows) <= max_rows:
        return rows, None
    if keywords:  # 큰 표는 질문 키워드가 든 행과 합계 행, 맨 앞 몇 행만
        picked = [i for i, r in enumerate(rows)
                  if i < 3 or _TOTAL_ROW.match(r[0] if r else "") or any(k in " ".join(r) for k in keywords)]
        if len(picked) > max_rows:
            picked = picked[:max_rows]
        return [rows[i] for i in picked], f"(표 {len(rows):,}행 중 {len(picked)}행: 앞부분·합계·질문 관련 행만)"
    return rows[:max_rows], f"(… 표 {len(rows):,}행 중 {len(rows) - max_rows:,}행 생략)"


def render_table(table: Dict[str, Any], keywords: Sequence[str] = (), max_rows: int = TABLE_ROWS) -> str:
    lines = [table["caption"]] if table.get("caption") else []
    rows, note = _table_rows(table, keywords, max_rows)
    header = table["header"]
    width = max([len(header)] + [len(r) for r in rows] + [1])
    if header:
        lines.append("| " + " | ".join(_cell(h) for h in header) + " |")
        lines.append("|" + "---|" * width)
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    if note:
        lines.append(note)
    return "\n".join(lines)


def render(blocks: Sequence[Block], keywords: Sequence[str] = (), limit: Optional[int] = None,
           max_rows: int = TABLE_ROWS) -> str:
    """블록 → LLM에 넘길 마크다운. limit을 넘으면 줄 경계에서 자른다."""
    parts = []
    for b in blocks:
        if b.kind == "table":
            parts.append(render_table(b.table, keywords, max_rows))
        elif b.kind == "heading":
            parts.append(f"**{b.text}**")
        else:
            parts.append(b.text)
    text = "\n\n".join(parts)
    return clip(text, limit) if limit else text


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[:cut if cut > limit // 2 else limit] + "\n(…이하 생략)"


# --- 트리 ---

@dataclass
class Node:
    node_id: str
    parent_id: Optional[str]
    seq: int
    level: int
    title: str
    path: str
    blocks: List[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return render(self.blocks, max_rows=10 ** 6)

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def content_hash(self) -> str:
        """제목과 본문이 같으면 같은 값 — 파서를 바꿔 트리를 다시 만들어도 내용이 같은 노드는 요약을 다시 받지 않는다."""
        return hashlib.sha1((self.path + "\n" + self.text).encode()).hexdigest()

    def blocks_json(self) -> str:
        return json.dumps([b.to_json() for b in self.blocks], ensure_ascii=False)


def _split_long(node: Node) -> List[Node]:
    """긴 절을 '가.' 소제목마다 하위 노드로. 소제목 앞의 블록은 절 자신에 남는다."""
    starts = [i for i, b in enumerate(node.blocks) if b.kind == "heading" and SPLIT_HEADING.match(b.text)]
    if node.chars <= SPLIT_CHARS or len(starts) < 2:
        return []
    children = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(node.blocks)
        title = node.blocks[start].text
        children.append(Node(f"{node.node_id}-{k + 1}", node.node_id, 0, node.level + 1, title,
                             f"{node.path} > {title}", node.blocks[start + 1:end]))
    node.blocks = node.blocks[:starts[0]]
    return children


def build_tree(xml: str) -> List[Node]:
    """원문 XML → 노드 목록 (문서 순서). 노드 본문은 다음 제목 전까지이고 하위 노드 본문은 들어가지 않는다."""
    nodes: List[Node] = []
    stack: List[Optional[Node]] = []  # 열린 SECTION마다 그 SECTION의 노드 (첫 제목이 나오기 전엔 None)
    marks: List[Tuple[Node, int, int]] = []  # (노드, 본문 시작, 제목 시작)
    used = set()
    for m in _TOKEN.finditer(xml):
        if m.group(2):
            if m.group(1):
                if stack:
                    stack.pop()
            else:
                stack.append(None)
            continue
        if 'ATOC="Y"' not in m.group(4):
            continue
        title = _clean(m.group(5))
        toc = re.search(r'ATOCID="(\d+)"', m.group(4))
        node_id = toc.group(1) if toc and toc.group(1) not in used else f"n{len(nodes) + 1}"
        used.add(node_id)
        opened = [n for n in stack if n is not None]
        first = bool(stack) and stack[-1] is None
        # SECTION의 첫 제목은 그 SECTION 노드, 같은 SECTION 안의 다음 제목(주석 항목 등)은 그 SECTION 노드의 자식
        parent = (opened[-1] if opened else None) if first else (stack[-1] if stack else None)
        node = Node(node_id, parent.node_id if parent else None, len(nodes), parent.level + 1 if parent else 1,
                    title, f"{parent.path} > {title}" if parent else title)
        if first:
            stack[-1] = node
        nodes.append(node)
        marks.append((node, m.end(), m.start()))
    for i, (node, start, _) in enumerate(marks):
        end = marks[i + 1][2] if i + 1 < len(marks) else len(xml)
        node.blocks = parse_blocks(xml[start:end])

    out: List[Node] = []
    for node in nodes:
        children = _split_long(node)
        out.append(node)
        out += children
    for i, node in enumerate(out):
        node.seq = i
    return out


# --- 색인 ---

def needs_summary(node: Node) -> bool:
    return node.chars >= SUMMARY_MIN_CHARS and not NO_SUMMARY.match(node.path)


def headings(blocks: Sequence[Block], limit: int = SUMMARY_HEADINGS_CHARS) -> str:
    """노드 전체의 소제목·표 캡션 (중복 제거, 문서 순서). 앞부분만 읽으면 뒤쪽 항목이 색인에서 빠진다."""
    seen, out, total = set(), [], 0
    for b in blocks:
        line = b.text if b.kind == "heading" else (b.table or {}).get("caption") or ""
        if not line or line in seen:
            continue
        if total + len(line) > limit:
            break
        seen.add(line)
        out.append(line)
        total += len(line) + 1
    return "\n".join(out)


def summary_input(node: Node, limit: int = SUMMARY_INPUT_CHARS) -> str:
    """노드 요약 입력: 짧은 노드는 본문 그대로, 긴 노드는 소제목·표 제목 목록을 먼저, 남은 자리만큼 본문 앞부분."""
    text = render(node.blocks, max_rows=TABLE_ROWS)
    if len(text) <= limit:
        return text
    outline = headings(node.blocks)
    if not outline:
        return clip(text, limit)
    return f"## 이 절 전체의 소제목·표 제목\n{outline}\n\n## 본문 앞부분\n{clip(text, limit - len(outline))}"


SUMMARY_PROMPT = """당신은 DART 정기보고서의 한 절을 읽고 목차에 붙일 짧은 색인을 씁니다.
이 색인은 나중에 '어느 절에 답이 있는지' 고를 때만 씁니다. 답을 쓰는 게 아닙니다.
- 이 절에 들어 있는 항목·표·수치의 종류를 한 줄(80자 이내)로, 쉼표로 나열하세요. 예: '연구개발비용 총계, 매출액 대비 연구개발비 비율, 주요 계약 현황'
- 제목만으로 알 수 없는 항목을 우선 적으세요. 수치 값 자체는 적지 마세요.
- 머리말 없이 그 한 줄만 답하세요."""


def summary_prompt(node: Node) -> str:
    return f"## 절\n{node.path}\n\n## 본문\n{summary_input(node)}"


def clean_summary(text: str) -> str:
    lines = [line.strip(" -*•'\"") for line in (text or "").strip().splitlines() if line.strip()]
    return lines[0][:200] if lines else ""
