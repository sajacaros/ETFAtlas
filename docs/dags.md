# Airflow DAGs

Airflow 3.3.2 (Python 3.14, 커스텀 이미지 `docker/airflow/Dockerfile`) 위에서 동작한다.
DAG은 `airflow.sdk.DAG` + `airflow.providers.standard` 오퍼레이터를 사용하며 스케줄은 `schedule=` 인자로 지정한다.
AGE 수집 공용 로직은 `airflow/dags/age_utils.py`에 모여 있다.

| DAG ID | 파일 | 스케줄 | 저장소 | 역할 |
|--------|------|--------|--------|------|
| `age_sync_universe` | `sync_universe_age.py` | `50 8 * * *`, `30 16 * * *` (매일 08:50·16:30 KST) | AGE | 일일 증분 수집 |
| `age_tagging` | `age_tagging.py` | `0 3 * * 6` (토 03:00 KST) | AGE | 신규 ETF 태깅 (`full_rebuild`로 전체 재태깅) |
| `rdb_sync_metadata` | `sync_metadata_rdb.py` | `40 8 * * *` (매일 08:40 KST) | RDB | `etfs` 코드/이름 동기화 |
| `rdb_realtime_prices` | `realtime_prices_rdb.py` | `*/10 9-15 * * 1-5` | RDB | 장중 현재가 + 포트폴리오 스냅샷 |
| `embed_code_examples` | `embed_code_examples.py` | 수동 | RDB (pgvector) | 챗봇 코드·레이아웃 예제 임베딩 |
| `backfill_prices` | `backfill_prices.py` | 수동 | AGE | ETF·종목 가격 이력 백필 (기본 400일) |
| `dart_sync_rdb` | `dart_sync_rdb.py` | `20 19 * * 1-5` (평일 19:20 KST) | RDB | 챗봇 기업 분석의 DART 고유번호·공시·주요계정 |
| `dart_report_index` | `dart_report_index.py` | `0 21 * * *` (매일 21:00 KST) | RDB, LLM | 정기보고서 목차 트리 색인 (원문 → 트리 → 등록 LLM 노드 요약) |

### 데이터 소스

| 소스 | 용도 | 인증 |
|------|------|------|
| KIS 종목 마스터 파일 (`kospi_code.mst.zip`) | 전체 ETF 코드/이름 목록 (그룹코드 `EF`) | 불필요 (공개 파일) |
| 한국투자증권 KIS Open API | ETF 현재가(NAV·순자산·상장주수), ETF/주식 일봉, ETF 현재 구성종목(HOLDS/CURRENT_HOLDS)·종목명, 영업일(기준 ETF 일봉), 휴장일 | `KIS_APP_KEY`, `KIS_APP_SECRET` (`KIS_BASE_URL` 선택) |
| 네이버 증권 모바일 API (비공식) | 신규 ETF 보수율(`totalFee`) | 불필요 |
| yfinance | 포트폴리오 보유 티커 현재가 (RDB) | 불필요 |
| DART OpenAPI (opendart.fss.or.kr) | 회사 고유번호, 공시 목록, 다중회사 주요계정 | 관리자 페이지 > DART 탭의 키(`dart_settings`, 암호화). 환경변수는 쓰지 않는다 |
| LiteLLM 프록시 (OpenAI 호환) | ETF 태그 분류·질문 일반화(`LLM_MODEL`), 코드 예제 임베딩(`EMBEDDING_MODEL`) | `LLM_API_BASE`/`LLM_API_KEY`, `EMBEDDING_API_BASE`/`EMBEDDING_API_KEY` |

---

## 1. age_sync_universe (일일 증분)

마지막 수집일 이후 ~ 오늘까지 누락된 영업일의 데이터를 자동 수집한다.

- **스케줄**: `MultipleCronTriggerTimetable('50 8 * * *', '30 16 * * *')` (매일 08:50·16:30 KST). 가격은 매일 따라잡고, 구성종목은 개장일에만 받는다
  - 16:30: 그날 종가가 확정된 뒤라(`MARKET_SETTLED_TIME` 16:00) 그날 가격을 받는다. 구성종목은 아침에 이미 받았으니 빠진 ETF만 다시 받고, 끝나면 일일 리포트를 디스코드로 보낸다
  - 08:50: 새 날짜가 없으면(전날 16:30에 받음) 전날 Price의 NAV·순자산·시가총액만 지금 현재가로 다시 쓴다(`refresh_latest_snapshot_values`). 16:30 값이 확정치인지 확인하지 못해서 예전처럼 다음 날 아침 값을 남긴다. 구성종목은 그날 공시분을 받는다
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화
- **동시 실행**: 1개 (`max_active_runs=1`)

### 태스크 구조

```
start
  └─ fetch_trading_dates
       └─ sync_universe_and_prices
            ├─ sync_holdings
            │    ├─ sync_stock_prices ─────┐
            │    └─ sync_weight_changes    │
            │         ├─ record_collection (all_done) ──────┐
            │         └─ notify_discord ────────────────────┤
            ├─ sync_returns ───────────────┤                │
            │                              └─ notify_daily_report (all_done) ─┤
            └─ tag_new_etfs ────────────────────────────────┤
                                                           end
```

### 태스크 상세

#### 1. fetch_trading_dates

AGE에서 마지막 ETF Price 날짜(`get_last_collected_date`)를 조회하고, 그 다음날부터 오늘까지의 영업일 목록을 반환한다.
AGE가 비어 있으면(첫 실행) 최근 10일 중 마지막 거래일 하루만 반환한다. 과거 이력 백필은 없다(필요해지면 그때 추가). 첫 실행에는 최근 거래일 하루만 수집하고 이후 매일 쌓인다.

#### 2. sync_universe_and_prices

`collect_universe_and_prices(dates)`를 호출하고, 신규 편입 ETF(`new_etfs`)와 실제로 ETF Price가 저장된 거래일(`actual_dates`)을 XCom으로 push한다. 새 날짜가 없으면 대신 `refresh_latest_snapshot_values()`로 마지막 수집일 NAV·순자산·시가총액을 다시 쓴다(장중에는 건너뜀).
KIS 종목 마스터에 없는(상장폐지) 유니버스 ETF는 Price 노드와 함께 지우고, 이름이 바뀐 ETF는 이름과 운용사(MANAGED_BY)를 고친다(`sync_universe_listing`). 마스터에서 유니버스의 10%(최소 5개)를 넘게 사라지면 마스터 이상으로 보고 지우지 않는다.

#### 3. sync_holdings

`holdings_target_date(now)`가 정한 날짜로 `collect_holdings(etf_codes, date)`를 호출하고, 받은 날짜를 XCom(return_value)으로 넘긴다. 이후 비중변화 계산·수집 기록·디스코드 알림은 가격 날짜가 아니라 이 날짜를 따른다.

KIS 구성종목(PDF)은 **영업일 08:30에 그날 공시분(직전 영업일 장 마감 후 보유)으로 갱신**되고 다음 영업일 아침까지 그대로이며, 과거 날짜는 조회할 수 없다. 그래서:
- 오늘이 개장일(`is_market_open`, `market_calendar` 캐시)이고 08:35 이후면 받는다. 날짜는 **수집한 날(공시일)**이다.
- 주말·휴장일 실행은 구성종목을 받지 않는다(가격만 따라잡는다). 날짜가 비어도 비교는 ETF별 이전 수집일과 한다(예: 10/8 → 10/12).
- 장중·장 마감 후에 받아도 같은 내역이다 — 평가금액은 기준가격으로 고정이고 비중만 장중 가격으로 0.0x%p 움직인다(2026-10-14 확인).
- 그날 날짜의 변화는 실제로는 직전 영업일 장중 매매다. 2026-10 전에 쌓인 HOLDS는 실행일의 전날 날짜로 적혀 있어 대부분 하루 앞당겨져 있다(토요일 실행분 제외).

KIS는 과거 구성종목을 주지 않으므로 그날 놓치면 복구할 수 없다. 그래서 실패를 다음처럼 다룬다.
- KIS 호출: 네트워크 오류·타임아웃·5xx는 1·2·4초 간격으로 최대 3번 다시 시도한다(`kis_api_client._get`).
- 연속 10개 ETF가 실패하면 KIS 장애로 보고 나머지는 시도하지 않는다(타임아웃 대기 방지).
- 실패가 20% 이상이면 태스크를 실패시켜 Airflow 재시도(3회, 5분 간격)로 다시 받는다. 이미 HOLDS가 있는 ETF는 건너뛰므로 빠진 것만 받는다.
- 마지막 시도이거나 실패가 20% 미만이면 받은 것만으로 진행하고, 빠진 ETF는 로그에 남긴다. 그 ETF는 다음 영업일에 이틀치 변화로 비교된다(`weight_changes.prev_date`).

#### 4. sync_stock_prices

`collect_stock_prices_for_dates(actual_dates)` — 누락된 거래일의 Stock 가격을 수집한다.

#### 5. sync_weight_changes · record_collection · notify_discord

액티브 ETF의 이전 수집일(공시일) 대비 비중 변화를 계산해 `weight_changes`에 저장하고(`compute_weight_changes`), 구성종목을 받은 날짜를 `collection_runs`에 기록(`pg_notify` 발행)한 뒤 디스코드 알림을 보낸다. 구성종목을 받지 않은 실행(주말·휴장일)에서는 셋 다 건너뛴다. 기록은 계산이 실패해도 하고, 디스코드는 이미 보낸 날짜면 건너뛴다. 상세는 [notify.md](notify.md) 참고.

#### 6. sync_returns

`update_etf_returns()` — 새 거래일 데이터가 있을 때만 수익률을 다시 계산한다.

#### 7. tag_new_etfs

신규 편입 ETF에 룰 기반 태그(`코스피`, `코스닥`)만 부여한다 (`INDEX_TAG_PATTERNS`). LLM 태깅은 `age_tagging`에서 수행한다.

#### 8. notify_daily_report

그날 종가를 받은 실행(`actual_dates`의 마지막이 오늘, 즉 16:30)에서만 `send_daily_report(date, new_etfs)`를 호출한다. 디스코드 알림이 꺼져 있거나 웹훅이 없거나 그날 이미 보냈으면(`discord_notification_logs.kind = 'daily_report'`) 건너뛴다.
- 신규 편입 ETF(있을 때만)
- 오늘의 특징: 1일 수익률이 `discord_settings.rise_threshold`(기본 3%, 관리자 페이지) 이상인 ETF 전부(많이 오른 100개까지)의 비중 상위 5개 구성종목과 시장 수익률(KODEX 200)을 LLM에 한 번 넘겨, 시장보다 더 오른 테마 묶음과 이끈 종목, 혼자 튄 종목만 1~3줄로 정리한다. 시장만큼 오른 지수형 ETF와 대형주 비중 같은 구조 설명은 쓰지 않는다(`summarize_rising_etfs`, 추론 끔). LLM이 실패하면 특징 없이 보낸다
- 상승 ETF: 많이 오른 순 상위 10개의 이름·코드·1일 수익률만 나열한다. 전체 개수는 제목에 적는다
- 주식 가격·구성종목이 일부 실패해도 보낸다(`all_done`)

---

## 공용 수집 함수 (age_utils)

### collect_universe_and_prices(dates)

KRX Open API 없이 KIS만으로 유니버스와 ETF 가격을 갱신한다. `KIS_APP_KEY`/`KIS_APP_SECRET`이 없으면 건너뛴다.

1. **ETF 목록**: `kis_api_client.fetch_etf_master()` — KIS 공개 종목 마스터 파일(`https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip`, cp949, 행 끝 227자 고정폭 영역의 그룹코드 `EF` = ETF)에서 전체 ETF(약 1,175개) 코드/이름을 받는다. 인증 불필요.
2. **스냅샷 대상**: 기존 유니버스 ∪ 이름 필터(`passes_universe_name_filter`)를 통과한 ETF.
3. **현재 스냅샷**: 대상마다 `KISApiClient.get_etf_snapshot(code)` — ETF/ETN 현재가(`FHPST02400000`, `/uapi/etfetn/v1/quotations/inquire-price`)로 현재가(`stck_prpr`), NAV(`nav`, 없으면 `prdy_last_nav`), 순자산총액(`etf_ntas_ttam`), 상장주수(`lstn_stcn`)를 조회한다. 순자산 값이 1억 미만이면 억원 단위로 보고 ×1억 한다 (응답 단위 미확인이라 둔 방어 로직).
4. **유니버스 신규 편입 조건** (`check_new_universe_candidates`):
   - 순자산 500억 이상 (`MIN_AUM`)
   - 제외 키워드 미포함 (`EXCLUDE_KEYWORDS`, `EXCLUDE_PATTERNS`): 레버리지, 인버스, 합성/선물, 커버드콜, 채권, 금·은/원자재, 통화, 머니마켓, 리츠 등
   - 해외 키워드 미포함 (`FOREIGN_NAME_KEYWORDS`): 미국, 중국, 글로벌, S&P, NASDAQ, MSCI, 해외 개별종목명 등
- 한번 등록된 ETF는 이후 조건에 미달하더라도 유니버스에서 제거하지 않는다.
- 신규 ETF: `ETF` 노드 MERGE → `name` SET → 이름 prefix로 운용사를 추출해 `(ETF)-[:MANAGED_BY]->(Company)` 연결.
- 프로필(`refresh_etf_profiles`): 매 실행마다 유니버스 전체(신규 포함)의 `expense_ratio`, `description`, `base_index`, `listed_date`, `dividend_yield`, `dividend_per_share`를 조회해 저장된 값과 **다른 필드만** SET한다. ETF 노드 속성으로 ETF당 값 하나만 두고 이력은 남기지 않는다.
  - 출처는 네이버 증권 모바일 API(`naver_client.fetch_etf_profiles`, `https://m.stock.naver.com/api/stock/{code}/etfAnalysis`)의 `totalFee`(소수점 2째자리 올림), `etfSummary`(HTML 정리한 원문), `etfBaseIndex`, `listedDate`(`YYYY-MM-DD`)다. 비공식 API라 실패하거나 값이 없는 필드는 비워 두고 진행한다 (`set_etf_profiles`는 값이 있는 필드만 SET).
  - 첫 실행에서 기존 유니버스의 설명·기초지수·상장일이 백필되고, 이후에는 보수 인하·설명 수정 같은 변경분만 기록된다. 0.1초 간격 순차 호출이라 유니버스 200개 기준 20~40초 걸린다.
- 유니버스 ETF마다 KIS 일봉(`get_daily_bars(code, dates[0], 최근 거래일)`, `FHKST03010100`)으로 Price 노드를 저장한다 (AGE MERGE+SET 버그 회피를 위해 "없으면 CREATE" / "있으면 SET" 2단계).
  - 모든 날짜: `open, high, low, close, volume`, `trade_value`(`acml_tr_pbmn`)
  - 최근 거래일만: `nav`, `net_assets`, `market_cap`(종가 × 상장주수). 현재가 API에 날짜 파라미터가 없어 그 이전 날짜는 null로 둔다.
- 최근 거래일 순자산으로 ETF 노드의 `net_assets`도 갱신한다.

**저장:** AGE — `ETF`, `Company` 노드, `MANAGED_BY`, `Price`, `(ETF)-[:HAS_PRICE]->(Price)`

### collect_holdings(etf_codes, bd)

KIS Open API "ETF 구성종목시세"(`GET /uapi/etfetn/v1/quotations/inquire-component-stock-price`, tr_id `FHKST121600C0`, `airflow/dags/kis_api_client.py`)로 호출 시점의 구성종목을 조회해 `bd` 날짜의 HOLDS 엣지로 저장한다.

- 같은 날짜의 HOLDS가 이미 있는 ETF는 건너뛴다 (재실행 대비).
- `is_listed_security_code()`로 KRX 상장 단축코드(`^[0-9][0-9A-Z]{5}$`)만 남기고 설정현금액(`010010`)·채권·선물 등을 제외한 뒤, 비중 기준 상위 30개만 저장한다.
- 필드 매핑: `weight` ← `etf_cnfg_issu_rlim`(%), `shares` ← `etf_vltn_amt / stck_prpr` (API에 수량 필드가 없어 평가금액/현재가로 역산한 **추정치**).
- Stock 노드를 MERGE하고 `name`, `is_etf`를 설정한다. 주식 이름은 KIS `hts_kor_isnm`, ETF는 AGE ETF 노드 이름을 우선 사용한다.
- HOLDS는 50개 ETF 단위로 MERGE → SET 후 커밋한다.
- 저장 후 `refresh_current_holds(date)`로 현재 보유종목을 갱신한다. 그날 HOLDS가 있는 ETF만 CURRENT_HOLDS를 지우고 그날 HOLDS로 다시 만든다. CURRENT_HOLDS 날짜가 이미 더 최근인 ETF는 건너뛰고, KIS 조회에 실패한 ETF는 이전 구성종목을 유지한다. 같은 날짜로 재실행해도 결과가 같다.
- 접근 토큰은 24시간 유효하고 발급이 1분 1회로 제한되어 `kis_tokens` 테이블에 캐시한다 (앱키 SHA-256 해시 키, 만료 10분 전 재발급). 호출 간 최소 0.2초 간격을 둔다 (한도 근처로 몰면 HTTP 500이 잦다).
- `KIS_APP_KEY`/`KIS_APP_SECRET`이 없으면 경고 후 수집을 건너뛴다.

**저장:** AGE — `Stock` 노드, `(ETF)-[:HOLDS {date, weight, shares}]->(Stock)` (날짜별 이력), `(ETF)-[:CURRENT_HOLDS {date, weight, shares}]->(Stock)` (현재 보유, ETF당 최대 30개)

### collect_stock_prices_for_dates(dates)

- AGE에서 `is_etf = false`인 Stock 코드 목록과, 대상 기간에 이미 저장된 (종목, 날짜) 쌍을 조회한다.
- 누락이 있는 종목마다 KIS 국내주식기간별시세(`KISApiClient.get_daily_bars(code, min(dates), max(dates))`)를 한 번 호출해 기간 전체 일봉을 받는다 (호출당 최대 100건, 100일 단위 페이지네이션). 종목×날짜 단위 호출은 하지 않는다.
- 이미 저장된 (종목, 날짜)와 대상 날짜 밖의 일봉은 건너뛴다.
- `change_rate`는 `prdy_vrss`(전일 대비)와 `prdy_vrss_sign`(부호)으로 계산한다.
- MERGE+SET 분리 방식으로 `open, high, low, close, volume, change_rate`를 저장하고 50종목마다 커밋한다.
- 같은 응답의 `output1`(호출 시점 시세)에서 상장주수(`lstn_stcn`)와 KIS PER·EPS·PBR을 받아 Stock 노드에 남긴다 (`get_daily_bars_with_quote`, `stock_quote_item`). 호출은 늘지 않는다. PER·EPS·PBR은 현재가가 마지막 일봉 종가와 같을 때만(장중 실행이면 비움) 남긴다.

**저장:** AGE — `Price` 노드, `(Stock)-[:HAS_PRICE]->(Price)`, Stock 노드의 `listed_shares, kis_per, kis_eps, kis_pbr, quote_date`

### update_etf_returns()

ETF별 최근 45개 Price로 `close_price`, `return_1d`, `return_1w`, `return_1m`, `market_cap_change_1w`를 계산해 ETF 노드에 저장한다.

---

## 2. age_tagging (ETF 태깅)

아직 자동 태깅되지 않은 ETF(`tagged_at` 없음, 즉 신규 편입)만 룰 기반 + 키워드 + LLM으로 태깅한다. 이미 태깅된 ETF는 매주 다시 LLM에 보내지 않는다 (LLM 결과가 실행마다 달라 태그가 흔들리기 때문).

- **스케줄**: `0 3 * * 6` (토요일 03:00 KST), 수동 트리거 가능
- **파라미터**: `full_rebuild`(기본 `false`). `true`로 수동 실행하면 수동 지정 ETF를 뺀 전체를 다시 태깅한다. 규칙이나 태그 목록을 바꾼 뒤 사용
- **재시도**: 1회, 5분 간격
- **태스크**: `tag_all_etfs` (타임아웃 30분)

### 처리 순서

0. **수동 지정**: `manual_tags` 속성이 있는 ETF(관리자 페이지 > ETF 태그에서 지정)는 아래 단계를 모두 건너뛰고 그 태그를 그대로 쓴다. `MANUAL_ONLY_TAGS`(`우량주` — 산업 테마 없이 선별 기준(시가총액 상위, 성장성, ESG 등)으로 대형주를 골라 담는 ETF)는 태그 노드만 만들고 수동 지정으로만 붙는다.
1. **인덱스 태그**: 이름이 `INDEX_TAG_PATTERNS`에 매칭되면 `코스피`/`코스닥` 태그.
2. **키워드 태그**: 이름에 키워드가 있으면 해당 태그 (예: 배터리 → 2차전지, 헬스케어 → 바이오).
3. **LLM 태그**: 나머지 ETF는 현재 보유종목(`CURRENT_HOLDS`) 비중 TOP 10 종목명과 함께 5개씩 묶어 LLM에 보낸다.
   - 추론이 토큰 한도(8192)를 다 써서 실패한 배치는 추론을 끄고(`enable_thinking: false`) 한 번 더 시도한다.
   - openai SDK `client.chat.completions.parse(response_format=ETFTagBatchResult)` structured output, `temperature=0`.
   - 허용 태그(`ALLOWED_TAGS`, 24개) Enum에서만 0~3개 선택. 시장 대표형(대형주·우량주·ESG 등)처럼 맞는 태그가 없으면 태그를 달지 않는다(필요하면 관리자가 `우량주` 등으로 수동 지정).
   - 두 번 다 실패한 배치의 ETF는 태그와 `tagged_at`을 그대로 둬 다음 실행에서 다시 시도한다.
   - LLM이 배치에 없던 코드를 돌려주면 무시한다.
   - LiteLLM 프록시(`LLM_API_BASE`)의 `LLM_MODEL`(기본 `qwen38-27b`) 사용.
4. 새 태그 쌍을 메모리에 모두 구한 뒤 단일 트랜잭션으로 반영한다.
   - `Tag`: `ALLOWED_TAGS` + `RULE_ONLY_TAGS` + `MANUAL_ONLY_TAGS`를 모두 MERGE하고, 목록에 없는 Tag 노드는 삭제한다.
   - `TAGGED`: 이번 대상 ETF(LLM 실패 제외)와 수동 지정 ETF의 관계만 지우고 새로 만든다. 다른 ETF의 태그는 건드리지 않는다.
   - 이번에 태깅한 ETF에 `tagged_at`(`YYYY-MM-DD`)을 기록한다.

`LLM_API_KEY`가 없으면 태깅을 건너뛴다.

**저장:** AGE — `Tag` 노드, `(ETF)-[:TAGGED]->(Tag)`, `ETF.tagged_at`

---

## 3. rdb_sync_metadata (RDB)

KIS 종목 마스터 파일에서 전체 ETF 목록을 받아 RDB `etfs` 테이블에 code + name만 동기화한다 (포트폴리오의 비유니버스 ETF 이름 조회용).
ETF 상세 메타데이터(순자산, 보수율, 운용사 등)는 AGE에서 관리한다.

- **스케줄**: `40 8 * * *` (매일 08:40 KST)
- **재시도**: 3회, 5분 간격

```
start → fetch_etf_master → sync_etfs_to_rdb → end
```

- `fetch_etf_master`: `kis_api_client.fetch_etf_master()`로 마스터 파일의 ETF(그룹코드 `EF`) code/name 전체(약 1,175개)를 조회한다. 인증이 필요 없다.
- `sync_etfs_to_rdb`: `INSERT ... ON CONFLICT (code) DO UPDATE`로 UPSERT한다.

**저장:** RDB `etfs` — 프론트엔드 ETF 검색(pg_trgm 퍼지 매칭)과 포트폴리오 ETF 이름 조회에 사용

---

## 4. rdb_realtime_prices (RDB)

장중 10분마다 포트폴리오 보유 종목의 현재가를 `ticker_prices`에 업서트하고 포트폴리오 스냅샷을 갱신한다.

- **스케줄**: `*/10 9-15 * * 1-5`
- **재시도**: 1회, 2분 간격

```
check_market_open → collect_prices → update_snapshots
```

- `check_market_open` (ShortCircuit): KIS 국내휴장일조회(`CTCA0903R`, `opnd_yn`)로 오늘이 개장일인지 확인한다. KIS 요청에 따라 결과를 `market_calendar` 테이블에 하루 1회 캐시한다. 판정할 수 없으면(키 없음·오류) 수집을 진행한다. 장 마감(15:30) 이후 이미 갱신된 경우도 건너뛴다.
- `collect_prices`: `holdings`의 고유 티커(CASH 제외) 현재가를 yfinance로 조회한다. 오늘 날짜 1건만 업서트한다(과거 종가 백필 없음).
- `update_snapshots`: `snapshot_enabled = true`인 포트폴리오의 평가금액을 계산해 `portfolio_snapshots`에 저장한다 (금액 컬럼은 `ENCRYPTION_KEY`로 암호화).

**저장:** RDB `ticker_prices`, `portfolio_snapshots`

---

## 5. embed_code_examples (pgvector)

수동 트리거 전용. `code_examples`(agent 해결 절차)와 `layout_examples`(레이아웃 플래너 화면 설계)에서 테이블마다 태스크 하나씩(`embed_code_examples`, `embed_layout_examples`), `status='active'`(승인됨, 미임베딩) 레코드를 찾아 질문을 LLM(`LLM_MODEL`)으로 일반화한 뒤, `EMBEDDING_MODEL`(기본 `embedding-gemma-300m`, 768차원)로 임베딩을 생성하고 `status='embedded'`로 전환한다.

## 5-1. backfill_prices (AGE, 수동)

수동 트리거 전용 (`days` 파라미터, 기본 400, 30~800 — 1년 수익률에는 1년 전 거래일이 있어야 해 365보다 넉넉히). `plan_days → backfill_etf_prices → backfill_stock_prices → update_returns`.
지난 `days`일(달력 기준)의 영업일 중 Price가 빠진 (ETF, 날짜)·(종목, 날짜)를 KIS 일봉으로 채운다 (`fill_missing_etf_prices`, `collect_stock_prices_for_dates`).

- 일봉 API는 기간 지정이 되므로 종가·시고저·거래량·거래대금은 지난 날짜도 받는다. NAV·순자산·시가총액은 현재가 API라 지난 날짜는 비워 둔다 (정기 수집에서 빠진 날을 채울 때와 같음). 구성종목은 날짜 지정이 안 돼 백필하지 않는다
- 이미 있는 Price는 건드리지 않으므로 다시 돌려도 된다. 최근 `PRICE_REFILL_BUSINESS_DAYS`(10) 영업일은 정기 수집이 쓰는 범위라 빼서, 수집과 겹쳐 돌아도 같은 날 Price가 둘 생기지 않는다
- 로컬 실측: 60일(29영업일) = ETF 193개 4,426건 + 종목 568개 13,125건, 2분 21초. 365일(233영업일) = ETF 36,795건 + 종목 114,781건, 9분 42초. 백필 뒤에도 가격 조회는 0.01~0.04초
- 끝나면 `update_etf_returns`로 ETF의 return_1d/1w/1m을 다시 계산한다 (`RETURNS_LOOKBACK_DAYS`=70일만 읽는다)

## 6. dart_sync_rdb (RDB)

챗봇 기업 분석(`company_financials`, `company_disclosures` 스킬)과 그래프 밖 종목 안내에 쓰는 DART 데이터를 받는다.
대상은 그래프의 종목(`Stock`, ETF 제외) 중 DART에 종목코드가 있는 회사다.

- **스케줄**: `20 19 * * 1-5` (평일 19:20 KST, 장 마감 후 공시까지)
- **재시도**: 2회, 10분 간격 / **동시 실행**: 1개
- **키**: `dart_settings`(관리자 페이지에서 저장, 암호문)만 쓴다. 없으면 경고만 남기고 건너뛴다

```
sync_corps → [sync_disclosures, sync_financials]
```

- `sync_corps`: `corpCode.xml`(zip) 전체를 `dart_corps`에 upsert한다 (호출 1건). 리졸버는 이 표로 "상장사지만 수집 ETF가 담지 않은 종목"과 "없는 이름"을 구분한다.
- `sync_disclosures`: 전체 회사의 최근 3일 공시(`list.json`, 100건씩 페이지)를 받아 그래프 종목만 `stock_disclosures`에 남긴다. 공시가 하나도 없는 종목은 회사별로 최근 90일을 백필한다 (첫 실행).
- `sync_financials`: 최근 3개 사업연도 × 4개 보고서(1분기·반기·3분기·사업보고서)를 `fnlttMultiAcnt.json`으로 100개 회사씩 받아 `stock_financials`에 upsert한다. 매출액·영업이익·당기순이익·자산총계·부채총계·자본총계만, 연결(CFS)·별도(OFS) 모두 원본 그대로 저장한다 (분·반기 손익은 3개월 금액과 누적 금액). 하루 호출은 수십 건이다 (키당 일일 한도 2만 건).

## 7. dart_report_index (RDB, LLM)

정기보고서를 목차 트리로 색인한다 (PageIndex 방식, 설계는 [report-index.md](report-index.md)). 파서와 노드 요약 프롬프트는 backend의 `app.services.report_tree`를 그대로 import한다.

- **스케줄**: `0 21 * * *` (매일 21:00 KST — 평일엔 `dart_sync_rdb`가 공시·주요계정을 받은 뒤, 주말엔 밀린 요약)
- **재시도**: 1회 / **동시 실행**: 1개 / 처음 등록될 때부터 켜져 있다 (`is_paused_upon_creation=False`)
- **키**: DART 키는 `dart_settings`, LLM은 등록된 설정(`ai_settings`, 없으면 `LLM_API_*` 환경변수). DART 키가 없으면 새 원문은 받지 않고, LLM 키가 없으면 요약을 건너뛴다

```
queue_reports → build_trees → summarize_nodes → prune_reports
```

- `queue_reports`: 그래프 종목의 최근 1년 정기보고서를 `stock_reports`에 `pending`으로 올린다. 접수번호는 `stock_financials`(보고서 코드)와 `stock_disclosures`(공시 제목, 정정 표시)에서 모으고, 같은 종목·기간이면 가장 최근 접수(정정본)만 (`report_tree.latest_reports`). 첨부만 바꾼 공시(`[첨부정정]`·`[첨부추가]` — 본문은 원래 보고서 그대로)와, 접수는 최근이어도 기간이 오래된 정정본(기간 끝 + 92일이 1년 범위 밖)은 올리지 않고 이미 올라 있으면 지운다. `missing` 접수번호는 빼고 고르므로 같은 기간의 그 전 접수가 올라간다.
- `build_trees`: 원문 zip(`document.xml`)을 받아 `stock_report_docs`에 보관하고 트리를 만들어 `report_nodes`에 쓴다 → `tree`. 종목별 최신 보고서부터, 실행당 90분. 파서 버전(`PARSER_VERSION`)이 오른 보고서는 보관한 원문으로 다시 만들고, 내용이 같은 노드(`content_hash`)는 요약을 이어받는다. 실패하면 `failed`로 남기고 다음 실행에서 다시 한다. 단 DART가 원문을 주지 않는 접수번호(`document.xml` 상태 014 '파일이 존재하지 않습니다' — 정정 공시에서 나온다)는 다시 받아도 같으므로 `missing`으로 두고, 그 회사의 기간 끝~접수일 공시를 DART에서 받아 `stock_disclosures`에 넣는다 (원래 보고서의 접수번호를 몰랐을 때 다음 `queue_reports`가 찾게).
- `summarize_nodes`: `tree` 보고서의 노드마다 '이 절에 든 항목' 한 줄 요약을 등록된 LLM으로 만든다 (추론 끔, 동시 6개, 노드 입력 8천 자 — 긴 노드는 소제목·표 제목 목록 + 앞부분). 100자 미만 노드, 재무제표 본표, XII 상세표는 요약하지 않는다. 다 되면 `summarized`, 실패한 노드가 있으면 `tree`로 두고 다음 실행에서 남은 노드만. 실행당 600분(21:00부터 밤새) — 처음에는 보고서가 수천 건이라 2~3일에 나눠 끝난다 (보고서당 약 1분). 그 뒤로는 새 보고서만이라 금방 끝난다. 동시 수는 등록 LLM(H100 한 장, FP8) 실측으로 정했다: 4개 대비 8개가 약 1.3배, 16개는 오히려 느리고 응답이 3배 늦어져 챗봇과 나눠 쓰도록 6개. 트리만 있어도 챗봇은 제목으로 고른다. 밀린 색인을 빨리 끝낼 때는 같은 모델을 띄운 서버를 Airflow Variable `report_summary_endpoints`(없으면 환경변수 `REPORT_SUMMARY_ENDPOINTS`)에 JSON 목록으로 적는다 — `[{"base_url": …, "api_key": …, "model": …, "workers": 8}]`. 등록 LLM 6개 자리와 함께 서버마다 workers개 자리를 두고 빈 자리에 노드를 보내므로 빠른 서버가 더 많이 맡는다. Variable은 컨테이너 재시작 없이 바뀌고, 다음 `summarize_nodes` 실행부터 쓴다. 보고서 사이에 자리가 놀지 않게 노드를 동시 수의 4배씩 모아 보낸다.
- `prune_reports`: 정정본이 색인된 같은 기간의 원래 보고서와, 1년 지난 보고서(종목마다 기간이 가장 최근인 색인본 1건은 남긴다)를 지운다 (원문·노드는 FK CASCADE).

---

## 저장 대상별 요약

### RDB

| 테이블 | DAG | 적재 태스크 | 용도 |
|--------|-----|-------------|------|
| `etfs` | rdb_sync_metadata | sync_etfs_to_rdb | pg_trgm 퍼지 검색, 포트폴리오 ETF 이름 조회 |
| `ticker_prices` | rdb_realtime_prices | collect_prices | 티커별 일별 가격 캐시 |
| `portfolio_snapshots` | rdb_realtime_prices | update_snapshots | 포트폴리오 일별 평가금액 이력 |
| `collection_runs` | age_sync_universe | record_collection | 수집 완료 기록, 알림 트리거 |
| `weight_changes`, `weight_change_dates` | age_sync_universe | sync_weight_changes | 액티브 ETF 비중 변화 (웹·디스코드 공용) |
| `discord_notification_logs` | age_sync_universe | notify_discord | 디스코드 발송 이력 |
| `kis_tokens` | KIS를 호출하는 모든 DAG | - | KIS 접근 토큰 캐시 |
| `market_calendar` | rdb_realtime_prices | check_market_open | 개장일 여부 캐시 (하루 1회) |
| `code_examples` | embed_code_examples | embed_code_examples | 챗봇 few-shot 코드 예제 (vector(768)) |
| `layout_examples` | embed_code_examples | embed_layout_examples | 레이아웃 플래너 few-shot 화면 설계 예제 (vector(768)) |
| `dart_corps` | dart_sync_rdb | sync_corps | DART 고유번호 ↔ 종목코드, 그래프 밖 상장사 안내 |
| `stock_disclosures` | dart_sync_rdb | sync_disclosures | 그래프 종목의 공시 목록 |
| `stock_financials` | dart_sync_rdb | sync_financials | 그래프 종목의 주요계정 (분기·연간 실적) |
| `stock_reports`, `stock_report_docs`, `report_nodes` | dart_report_index | queue_reports, build_trees, summarize_nodes | 정기보고서 목차 트리 색인 (`company_report`·`company_revenue_mix`) |

### Apache AGE

| 노드/관계 | 적재 함수 | 용도 |
|-----------|-----------|------|
| `ETF`, `Company`, `MANAGED_BY` | collect_universe_and_prices | 유니버스, 메타데이터, 운용사 |
| `Price`, `(ETF)-[:HAS_PRICE]->` | collect_universe_and_prices (KIS 일봉 + 현재가) | ETF 가격 시계열 |
| `Stock`, `HOLDS` | collect_holdings (KIS) | 보유종목 이력 (수집일 기준 스냅샷, 변화 비교용) |
| `CURRENT_HOLDS` | collect_holdings → refresh_current_holds | 현재 보유종목 (ETF당 최대 30개) |
| `Price`, `(Stock)-[:HAS_PRICE]->` | collect_stock_prices_for_dates (KIS 일봉) | 주식 가격 시계열 |
| ETF 수익률 속성 | update_etf_returns | 1D/1W/1M 수익률 |
| `Tag`, `TAGGED`, `ETF.tagged_at` | age_tagging, tag_new_etfs | ETF 테마 분류 |

## 컨테이너 시작 확인 (빈 DAG 폴더)

WSL 부팅 직후 Airflow 컨테이너가 바인드 마운트가 준비되기 전에 붙으면 `/opt/airflow/dags`가 빈 채로 보인다. 스케줄러는 떠 있지만 DAG를 못 읽어 실행을 만들지 않고 오류도 없다 (2026-10-14~18 수집 누락, 그 사이 구성종목은 KIS가 과거 날짜를 주지 않아 복구 불가).
그래서 api-server·scheduler·dag-processor는 시작할 때 `/opt/airflow/dags`와 `/opt/backend`가 비어 있으면 종료하고(`docker-compose.yml`의 `airflow-mount-guard`), `restart: unless-stopped`가 다시 띄운다. 재시작하면 마운트가 제대로 붙는다.
계속 비어 있으면 컨테이너가 재시작을 반복하므로 `docker ps`의 Restarting으로 드러난다.

## 환경 변수

| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | 앱 DB(`etf_atlas`) 연결 문자열 (Airflow 메타데이터는 별도 `airflow` DB) |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | KIS Open API 앱키 (ETF 현재가, ETF/주식 일봉, 구성종목, 영업일, 휴장일) |
| `KIS_BASE_URL` | KIS 엔드포인트 (기본 `https://openapi.koreainvestment.com:9443`) |
| `LLM_API_BASE`, `LLM_API_KEY` | LiteLLM 프록시 (기본 `http://localhost:4000`) |
| `LLM_MODEL` | 태그 분류/질문 일반화 모델 (기본 `qwen38-27b`) |
| `EMBEDDING_API_BASE`, `EMBEDDING_API_KEY` | 임베딩용 LiteLLM 프록시 (채팅 모델과 키가 다름) |
| `EMBEDDING_MODEL` | 임베딩 모델 (기본 `embedding-gemma-300m`, 768차원) |

LLM/임베딩 항목(`LLM_*`, `EMBEDDING_*`)은 관리자 페이지 > AI 탭에서 저장한 값(`ai_settings`)이 우선하고, 비어 있는 항목만 환경변수를 쓴다 (`age_utils.load_ai_config`).
| `ENCRYPTION_KEY` | 포트폴리오 금액·저장한 API 키 암호화 키 |
| `DISCORD_WEBHOOK_URL` | (선택) 수집 완료 디스코드 알림 |

## 의존성 (airflow/requirements.txt)

Airflow 공식 constraints(`constraints-3.3.2/constraints-3.14.txt`)를 적용해 이미지 빌드 시 설치한다 (`docker/airflow/Dockerfile`).

```
psycopg2-binary>=2.9.11
pandas>=2.2
requests>=2.32
yfinance>=1.1.0
openai>=2.0.0
cryptography>=46.0.0
```
