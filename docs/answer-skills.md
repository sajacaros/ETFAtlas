# 챗봇 답변 화면: 레이아웃과 스킬

답변을 마크다운 한 덩어리가 아니라 **여러 영역(슬롯)으로 나뉜 화면**으로 보여준다.
레이아웃 에이전트가 먼저 화면을 나눠 보내고, 각 영역은 스킬이 채우는 대로 하나씩 표시된다.

```
질문 → 질문 재작성(맥락이 있을 때) → 레이아웃 설계(LLM 1회)
     → SSE layout: 프런트가 빈 영역(스켈레톤)을 그린다
     → 슬롯 실행: 독립 슬롯은 동시에, narrative 같은 after_others 슬롯은 그 뒤에
     → SSE slot {id, status: complete}: 프런트가 GET으로 그 영역 내용을 가져와 채운다
     → SSE answer: 화면 전체를 텍스트로 옮긴 것 (대화 기억·관리자 검수용)
```

확장 지점은 둘이고 서로 모른다.

| 확장 지점 | 위치 | 역할 |
|---|---|---|
| 스킬 | `backend/app/services/answer/skills/` | 무엇을 가져올지 (데이터 → dataset) |
| 차트 빌더 | `frontend/src/components/answer/charts.ts` | 어떻게 그릴지 (view.kind → ECharts 옵션) |

오케스트레이터·SSE 프로토콜·저장 구조·레이아웃 렌더러는 특정 스킬이나 차트를 모른다.

## SSE 이벤트 (`POST /api/chat/message/stream`)

| 이벤트 | data | 비고 |
|---|---|---|
| `session` | `{session_id, title}` | |
| `status` | `{stage: refining \| planning \| searching_examples \| thinking}` | 뒤의 둘은 agent 슬롯 |
| `refined_question` | `{question}` | |
| `layout` | `{chat_log_id, layout}` | 슬롯 이벤트보다 항상 먼저 |
| `slot` | `{id, status, message?}` | `running` → `complete \| empty \| failed \| stopped` |
| `slot_delta` | `{id, text}` | 텍스트 슬롯의 조각 |
| `step_start` / `step` / `matched_examples` | 기존 형식 + `slot_id` | agent 슬롯의 실행 과정 |
| `answer` | `{answer}` | 화면의 텍스트 요약 |
| `chat_log_id`, `[DONE]` | | 기존과 같다 |

레이아웃은 `column / row / slot` 트리다.

```json
{"type": "column", "children": [
  {"type": "row", "children": [
    {"type": "slot", "id": "s1", "slot": "chart", "display": "line", "title": "1개월 수익률 추이"},
    {"type": "slot", "id": "s2", "slot": "chart", "display": "treemap", "title": "구성종목"}
  ]},
  {"type": "slot", "id": "s3", "slot": "text", "display": "text", "title": "해설"}
]}
```

## 슬롯 조회

`GET /api/chat/logs/{chat_log_id}/slots/{slot_id}` → `{id, status, content, message}`

지난 대화(`GET /api/chat/sessions/{id}`)의 메시지에는 `layout`과 `slots`(id → 상태)가 들어 있고,
프런트는 완료된 영역을 같은 API로 가져온다. 실시간 화면과 기록 화면이 같은 경로를 쓴다.

## 슬롯 내용 형식 (`services/answer/schemas.py`)

- 텍스트: `{"type": "text" | "markdown", "text": "..."}`
- 데이터: `{"type": "data", "dataset": {...}, "view": {...}, "sources": [...], "notes": [...]}`
  - `dataset.fields`: `{key, label, format}` — format은 `text | number | percent | krw | price | date`. 값은 원시값이고, 사람이 읽는 형태로 바꾸는 건 프런트가 한다.
  - `dataset.rows`의 행 메타: `_format`(행 서식, 열보다 우선), `_better`(`high | low`, 비교표 강조), `_raw`(점수화한 값의 원값)
  - `view.kind`: `table | line | bar | donut | treemap | radar | candlestick`. view가 가리키는 필드가 dataset에 없으면 백엔드에서 거부된다.
  - 같은 dataset을 표로도 그릴 수 있어서, 프런트는 모르는 차트를 표로 대신 보여주고 차트마다 "표로 보기"를 제공한다.

## 스킬 추가하기

1. `skills/`에 스킬 클래스를 만든다. DB에서 결정적으로 데이터를 만드는 스킬은 `DataSkill`을 상속하고 `fetch()`만 구현한다.

```python
class MySkill(DataSkill):
    name = "my_skill"
    description = "레이아웃 에이전트가 읽는 설명: 언제 쓰는지, 무엇을 보여주는지"
    Args = MyArgs                     # pydantic 모델 — 필드 description도 에이전트가 읽는다
    displays = ("bar", "table")       # 지원하는 표시 방식, 첫 번째가 기본값

    def fetch(self, args, display, db, resolver) -> SkillResult:
        etf = resolver.etf(db, args.etf)          # 이름 → 코드 (한 답변 안에서 공유, 종목은 resolver.stock)
        ...
        return data_result(dataset, view, summary, sources, notes)  # 없으면 empty("...")
```

2. `skills/__init__.py`의 `REGISTRY`에 올린다. 레이아웃 에이전트의 출력 스키마(스킬별 args·display 검증)와 프롬프트의 스킬 목록은 레지스트리에서 자동으로 만들어진다.

규칙:
- 숫자는 스킬이 DB에서 만든다. LLM에는 `summary`(단위를 붙인 짧은 텍스트)만 넘어간다.
- 도메인 규칙(여러 ETF는 누적 수익률로, 도넛은 8조각까지 등)은 스킬 안에서 처리한다.
- 스트리밍이 필요하거나 DB가 아닌 곳을 쓰는 스킬은 `Skill.run()`을 직접 구현해 `delta` / `result` 이벤트를 낸다 (`narrative.py`, `agent.py` 참고).
- 다른 슬롯의 결과가 필요하면 `after_others = True` — `ctx.related`로 앞 슬롯들의 (제목, 요약)을 받는다.

## 등록된 스킬

| 스킬 | 표시 | 내용 |
|---|---|---|
| `price_trend` | line, candlestick, table | 가격 추이. 여러 ETF는 시작일 대비 누적 수익률 |
| `period_returns` | bar, table | 1일~1년 기간별 수익률 |
| `etf_compare` | table | 기본 정보 비교표 (행마다 서식·우열 강조) |
| `etf_profile` | radar, table | 전체 ETF 대비 백분위 점수: 저보수, 규모, 1주 수익률, 1주 시총 증감, 분산도 |
| `holdings` | treemap, donut, bar, table | 구성종목 비중 (도넛은 상위 7개 + 기타) |
| `stock_trend` | line, candlestick, table | 개별 종목 가격 추이 (`price_trend`와 같은 베이스) |
| `stock_holders` | bar, table | 종목을 많이 담은 ETF 순위 |
| `narrative` | text | 앞 슬롯 요약을 바탕으로 한 해설 (토큰 스트리밍) |
| `agent` | markdown | 기존 tool-calling 에이전트. 다른 스킬로 안 되는 질문과 레이아웃 설계 실패 시 폴백 |

## 차트 추가하기

1. 백엔드 `schemas.py`에 view 모델을 추가하고 `View` 유니온과 `CHART_DISPLAYS`에 올린다.
2. 프런트 `types/api.ts`의 `DataView`에 같은 모양을 추가한다.
3. `charts.ts`에 빌더를 만들어 `BUILDERS`에 올린다. 필요하면 `ChartView.tsx`의 `echarts.use([...])`에 차트 모듈을 등록한다.

ECharts 런타임은 `ChartView.tsx`에만 있고 지연 로딩된다(차트를 처음 그릴 때 받는다).
