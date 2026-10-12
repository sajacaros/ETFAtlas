# 챗봇 답변 화면: 레이아웃과 스킬

답변을 마크다운 한 덩어리가 아니라 **여러 영역(슬롯)으로 나뉜 화면**으로 보여준다.
레이아웃 에이전트가 먼저 화면을 나눠 보내고, 각 영역은 스킬이 채우는 대로 하나씩 표시된다.

```
질문 → 질문 재작성(맥락이 있을 때) → 레이아웃 설계(LLM 1회)
     → SSE layout: 프런트가 빈 영역(스켈레톤)을 그린다
     → 슬롯 실행: 의존하는 슬롯이 끝나면 돈다. 서로 의존하지 않는 슬롯은 동시에
       (의존 = '@이름.순위'로 참조한 슬롯, narrative 같은 after_others 슬롯은 나머지 슬롯 전부)
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
- 결과에 순위가 있는 ETF·종목 목록이 있으면 `exports`(무엇을 내보내는지 설명)를 적고 `data_result(..., exports=[{code, name}, ...])`로 순위 순으로 담는다. 그러면 다른 슬롯이 참조할 수 있다.

## 등록된 스킬

| 스킬 | 표시 | 내용 |
|---|---|---|
| `price_trend` | line, candlestick, table | 가격 추이. 여러 ETF는 시작일 대비 누적 수익률 |
| `period_returns` | bar, table | 1일~1년 기간별 수익률 |
| `etf_compare` | table | 기본 정보 비교표 (행마다 서식·우열 강조) |
| `etf_profile` | radar, table | 전체 ETF 대비 백분위 점수: 저보수, 규모, 1주 수익률, 1주 시총 증감, 분산도 |
| `holdings` | treemap, donut, bar, table | 구성종목 비중 (도넛은 상위 7개 + 기타) |
| `portfolio_lookthrough` | treemap, bar, donut, table | 포트폴리오(ETF·종목과 비중)의 종목별 합산 비중. ETF는 구성종목으로 풀어 비중을 곱해 더하고(`domain/composition.py`와 같은 계산), 직접 담은 종목은 그대로 더한다. 구성종목 데이터가 없는 ETF(해외 ETF 등)는 ETF 한 행으로, ETF 안의 30위 밖·현금은 기타로 둔다 |
| `stock_trend` | line, candlestick, table | 개별 종목 가격 추이 (`price_trend`와 같은 베이스) |
| `stock_holders` | bar, table | 종목을 많이 담은 ETF 순위 |
| `etf_choice` | markdown | ETF 하나가 필요한데 조건만 있어 여러 ETF가 해당할 때 후보를 보여 주고 되묻는다. `by=stock`(원익IPS가 들어간 ETF, 그 종목 비중 순) 또는 `by=theme`(반도체 ETF, 같은 이름의 태그가 있으면 그 태그, 없으면 이름에 그 단어가 든 ETF를 순자산 순으로) |
| `narrative` | text | 앞 슬롯 요약을 바탕으로 한 해설 (토큰 스트리밍) |
| `agent` | markdown | 기존 tool-calling 에이전트. 다른 스킬로 안 되는 질문과 레이아웃 설계 실패 시 폴백 |

## 슬롯 간 참조

한 슬롯의 결과를 다른 슬롯의 대상으로 쓸 수 있다. 예: "삼성전자를 가장 많이 보유한 ETF와 그 구성종목".

```json
{"skill": "stock_holders", "name": "rank", "args": {"stock": "삼성전자"}}
{"skill": "holdings", "args": {"etf": "@rank.1"}}
```

- 플래너는 결과를 내보내는 슬롯에 `name`을 붙이고, 다른 슬롯의 인자에 `@name.1`(1위)이나 `@name.1-3`(1~3위, 목록 인자에서만)을 적는다. 스킬의 인자 타입은 그대로이고, 어느 문자열 인자에든 쓸 수 있다.
- 오케스트레이터는 참조한 슬롯이 끝난 뒤, 참조를 그 슬롯이 내보낸 대상의 코드로 바꿔 실행한다 (`refs.py`). 무엇을 받았는지는 영역의 notes에 남긴다 ("'삼성전자 비중 상위 ETF' 1위: WON 200(448100)").
- 참조한 슬롯이 결과를 못 냈거나 되묻는 중이면, 참조하는 슬롯은 돌지 않고 그 이유를 표시한다.
- 없는 이름, 결과를 내보내지 않는 스킬, 순환 참조는 플래너 출력 검증에서 거부되어 플래너가 다시 쓴다.
- 내보내는 스킬: `stock_holders`(ETF, 그 종목 비중 순), `holdings`(종목, ETF 내 비중 순), `portfolio_lookthrough`(종목, 합산 비중 순).

## 대상을 정하지 못할 때: 되묻기

ETF를 하나로 정할 수 없으면 고르지 않고 사용자에게 묻는다.

- 이름이 애매할 때: 리졸버는 이름이 정확히 같은 ETF가 없고 후보가 둘 이상이면 `AmbiguousETF`를 낸다. `DataSkill.run()`이 이를 받아 후보를 순자산 순으로 번호 붙인 표와 질문으로 바꾸므로 모든 데이터 스킬에 똑같이 적용된다 (`K반도체TOP2+`, `코스닥150`).
- 조건만 있을 때: 플래너가 `etf_choice` 슬롯 하나로 되묻는다 (`원익IPS가 들어간 ETF의 구성종목`, `반도체 ETF 3개월 수익률 추이`). ETF 목록 자체를 묻는 질문은 해당하지 않는다.
- 되묻는 결과는 `SkillResult(clarify=True)`다. 이때 오케스트레이터는 `narrative` 같은 `after_others` 슬롯을 돌리지 않는다.
- 후보 표가 답변 텍스트에 그대로 들어가므로, 다음 턴의 `두 번째 거`나 ETF 이름은 질문 재작성이 그 ETF로 풀어 준다.

## 차트 추가하기

1. 백엔드 `schemas.py`에 view 모델을 추가하고 `View` 유니온과 `CHART_DISPLAYS`에 올린다.
2. 프런트 `types/api.ts`의 `DataView`에 같은 모양을 추가한다.
3. `charts.ts`에 빌더를 만들어 `BUILDERS`에 올린다. 필요하면 `ChartView.tsx`의 `echarts.use([...])`에 차트 모듈을 등록한다.

ECharts 런타임은 `ChartView.tsx`에만 있고 지연 로딩된다(차트를 처음 그릴 때 받는다).
