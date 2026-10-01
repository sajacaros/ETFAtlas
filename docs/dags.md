# Airflow DAGs

Airflow 3.3.2 (Python 3.14, 커스텀 이미지 `docker/airflow/Dockerfile`) 위에서 동작한다.
DAG은 `airflow.sdk.DAG` + `airflow.providers.standard` 오퍼레이터를 사용하며 스케줄은 `schedule=` 인자로 지정한다.
AGE 수집 공용 로직은 `airflow/dags/age_utils.py`에 모여 있다.

| DAG ID | 파일 | 스케줄 | 저장소 | 역할 |
|--------|------|--------|--------|------|
| `age_sync_universe` | `sync_universe_age.py` | `30 8 * * 2-6` (화~토 08:30 KST) | AGE | 일일 증분 수집 |
| `age_tagging` | `age_tagging.py` | `0 3 * * 6` (토 03:00 KST) | AGE | ETF 태그 전체 재구축 |
| `rdb_sync_metadata` | `sync_metadata_rdb.py` | `30 8 * * 1-5` (평일 08:30 KST) | RDB | `etfs` 코드/이름 동기화 |
| `rdb_realtime_prices` | `realtime_prices_rdb.py` | `*/10 9-15 * * 1-5` | RDB | 장중 현재가 + 포트폴리오 스냅샷 |
| `embed_code_examples` | `embed_code_examples.py` | 수동 | RDB (pgvector) | 챗봇 코드 예제 임베딩 |

### 데이터 소스

| 소스 | 용도 | 인증 |
|------|------|------|
| KIS 종목 마스터 파일 (`kospi_code.mst.zip`) | 전체 ETF 코드/이름 목록 (그룹코드 `EF`) | 불필요 (공개 파일) |
| 한국투자증권 KIS Open API | ETF 현재가(NAV·순자산·상장주수), ETF/주식 일봉, ETF 현재 구성종목(HOLDS)·종목명, 영업일(기준 ETF 일봉), 휴장일 | `KIS_APP_KEY`, `KIS_APP_SECRET` (`KIS_BASE_URL` 선택) |
| 네이버 증권 모바일 API (비공식) | 신규 ETF 보수율(`totalFee`) | 불필요 |
| yfinance | 포트폴리오 보유 티커 현재가 (RDB) | 불필요 |
| LiteLLM 프록시 (OpenAI 호환) | ETF 태그 분류·질문 일반화(`LLM_MODEL`), 코드 예제 임베딩(`EMBEDDING_MODEL`) | `LLM_API_BASE`/`LLM_API_KEY`, `EMBEDDING_API_BASE`/`EMBEDDING_API_KEY` |

---

## 1. age_sync_universe (일일 증분)

마지막 수집일 이후 ~ 오늘까지 누락된 영업일의 데이터를 자동 수집한다.

- **스케줄**: `30 8 * * 2-6` (거래일 다음날 08:30 KST, 화~토)
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화

### 태스크 구조

```
start
  └─ fetch_trading_dates
       └─ sync_universe_and_prices
            ├─ sync_holdings
            │    ├─ sync_stock_prices ─┐
            │    └─ record_and_notify ─┤
            ├─ sync_returns ───────────┤
            └─ tag_new_etfs ───────────┘
                                      end
```

### 태스크 상세

#### 1. fetch_trading_dates

AGE에서 마지막 ETF Price 날짜(`get_last_collected_date`)를 조회하고, 그 다음날부터 오늘까지의 영업일 목록을 반환한다.
AGE가 비어 있으면(첫 실행) 최근 10일 중 마지막 거래일 하루만 반환한다. 과거 이력 백필은 없다(필요해지면 그때 추가). 첫 실행에는 최근 거래일 하루만 수집하고 이후 매일 쌓인다.

#### 2. sync_universe_and_prices

`collect_universe_and_prices(dates)`를 호출하고, 신규 편입 ETF(`new_etfs`)와 실제로 ETF Price가 저장된 거래일(`actual_dates`)을 XCom으로 push한다.

#### 3. sync_holdings

`collect_holdings(etf_codes, actual_dates[-1])` — 여러 날이 밀려 있어도 **최근 거래일 1일치**만 수집한다 (KIS는 과거 날짜 조회 불가).

#### 4. sync_stock_prices

`collect_stock_prices_for_dates(actual_dates)` — 누락된 거래일의 Stock 가격을 수집한다.

#### 5. record_and_notify

최근 거래일을 `collection_runs`에 기록(`pg_notify` 발행)하고, 신규 기록일 때만 디스코드 알림을 보낸다. 상세는 [notify.md](notify.md) 참고.

#### 6. sync_returns

`update_etf_returns()` — 새 거래일 데이터가 있을 때만 수익률을 다시 계산한다.

#### 7. tag_new_etfs

신규 편입 ETF에 룰 기반 태그(`코스피`, `코스닥`)만 부여한다 (`INDEX_TAG_PATTERNS`). LLM 태깅은 `age_tagging`에서 수행한다.

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
- 신규 ETF: `ETF` 노드 MERGE → `name`, `expense_ratio` SET → 이름 prefix로 운용사를 추출해 `(ETF)-[:MANAGED_BY]->(Company)` 연결.
  - 보수율은 신규 편입 후보만 네이버 증권 모바일 API(`naver_client.fetch_expense_ratios`, `https://m.stock.naver.com/api/stock/{code}/etfAnalysis`의 `totalFee`)로 조회하고 소수점 2째자리 올림 처리한다. 비공식 API라 실패하면 `expense_ratio`만 비워 두고 진행한다.
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
- 접근 토큰은 24시간 유효하고 발급이 1분 1회로 제한되어 `kis_tokens` 테이블에 캐시한다 (앱키 SHA-256 해시 키, 만료 10분 전 재발급). 호출 간 최소 0.06초 간격을 둔다.
- `KIS_APP_KEY`/`KIS_APP_SECRET`이 없으면 경고 후 수집을 건너뛴다.

**저장:** AGE — `Stock` 노드, `(ETF)-[:HOLDS {date, weight, shares}]->(Stock)`

### collect_stock_prices_for_dates(dates)

- AGE에서 `is_etf = false`인 Stock 코드 목록과, 대상 기간에 이미 저장된 (종목, 날짜) 쌍을 조회한다.
- 누락이 있는 종목마다 KIS 국내주식기간별시세(`KISApiClient.get_daily_bars(code, min(dates), max(dates))`)를 한 번 호출해 기간 전체 일봉을 받는다 (호출당 최대 100건, 100일 단위 페이지네이션). 종목×날짜 단위 호출은 하지 않는다.
- 이미 저장된 (종목, 날짜)와 대상 날짜 밖의 일봉은 건너뛴다.
- `change_rate`는 `prdy_vrss`(전일 대비)와 `prdy_vrss_sign`(부호)으로 계산한다.
- MERGE+SET 분리 방식으로 `open, high, low, close, volume, change_rate`를 저장하고 50종목마다 커밋한다.

**저장:** AGE — `Price` 노드, `(Stock)-[:HAS_PRICE]->(Price)`

### update_etf_returns()

ETF별 최근 45개 Price로 `close_price`, `return_1d`, `return_1w`, `return_1m`, `market_cap_change_1w`를 계산해 ETF 노드에 저장한다.

---

## 2. age_tagging (태그 재구축)

전체 ETF의 태그를 룰 기반 + 키워드 + LLM으로 재구축한다.

- **스케줄**: `0 3 * * 6` (토요일 03:00 KST), 수동 트리거 가능
- **재시도**: 1회, 5분 간격
- **태스크**: `tag_all_etfs` (타임아웃 30분)

### 처리 순서

0. **수동 지정**: `manual_tags` 속성이 있는 ETF(관리자 페이지 > ETF 태그에서 지정)는 아래 단계를 모두 건너뛰고 그 태그를 그대로 쓴다. `MANUAL_ONLY_TAGS`(`우량주` — 특정 테마 없이 대형 우량주를 소수만 골라 집중하는 ETF)는 태그 노드만 만들고 수동 지정으로만 붙는다.
1. **인덱스 태그**: 이름이 `INDEX_TAG_PATTERNS`에 매칭되면 `코스피`/`코스닥` 태그.
2. **키워드 태그**: 이름에 키워드가 있으면 해당 태그 (예: 배터리 → 2차전지, 헬스케어 → 바이오).
3. **LLM 태그**: 나머지 ETF는 최신 HOLDS 날짜의 보유종목 TOP 10 종목명과 함께 5개씩 묶어 LLM에 보낸다.
   - 추론이 토큰 한도(8192)를 다 써서 실패한 배치는 추론을 끄고(`enable_thinking: false`) 한 번 더 시도한다.
   - openai SDK `client.chat.completions.parse(response_format=ETFTagBatchResult)` structured output, `temperature=0`.
   - 허용 태그(`ALLOWED_TAGS`, 24개) Enum에서만 0~3개 선택. 시장 대표형(대형주·우량주·ESG 등)처럼 맞는 태그가 없으면 태그를 달지 않는다.
   - LiteLLM 프록시(`LLM_API_BASE`)의 `LLM_MODEL`(기본 `qwen38-27b`) 사용.
4. 새 태그 쌍을 메모리에 모두 구축한 뒤, 기존 `TAGGED`/`Tag`를 삭제하고 일괄 재생성한다 (단일 트랜잭션 — LLM 실패 시에도 기존 태그 보존).

`LLM_API_KEY`가 없으면 태깅을 건너뛴다.

**저장:** AGE — `Tag` 노드, `(ETF)-[:TAGGED]->(Tag)`

---

## 3. rdb_sync_metadata (RDB)

KIS 종목 마스터 파일에서 전체 ETF 목록을 받아 RDB `etfs` 테이블에 code + name만 동기화한다 (포트폴리오의 비유니버스 ETF 이름 조회용).
ETF 상세 메타데이터(순자산, 보수율, 운용사 등)는 AGE에서 관리한다.

- **스케줄**: `30 8 * * 1-5` (평일 08:30 KST)
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

수동 트리거 전용. `code_examples`에서 `status='active'`(승인됨, 미임베딩) 레코드를 찾아 질문을 LLM(`LLM_MODEL`)으로 일반화한 뒤, `EMBEDDING_MODEL`(기본 `embedding-gemma-300m`, 768차원)로 임베딩을 생성하고 `status='embedded'`로 전환한다.

---

## 저장 대상별 요약

### RDB

| 테이블 | DAG | 적재 태스크 | 용도 |
|--------|-----|-------------|------|
| `etfs` | rdb_sync_metadata | sync_etfs_to_rdb | pg_trgm 퍼지 검색, 포트폴리오 ETF 이름 조회 |
| `ticker_prices` | rdb_realtime_prices | collect_prices | 티커별 일별 가격 캐시 |
| `portfolio_snapshots` | rdb_realtime_prices | update_snapshots | 포트폴리오 일별 평가금액 이력 |
| `collection_runs` | age_sync_universe | record_and_notify | 수집 완료 기록, 알림 트리거 |
| `kis_tokens` | KIS를 호출하는 모든 DAG | - | KIS 접근 토큰 캐시 |
| `market_calendar` | rdb_realtime_prices | check_market_open | 개장일 여부 캐시 (하루 1회) |
| `code_examples` | embed_code_examples | embed_code_examples | 챗봇 few-shot 코드 예제 (vector(768)) |

### Apache AGE

| 노드/관계 | 적재 함수 | 용도 |
|-----------|-----------|------|
| `ETF`, `Company`, `MANAGED_BY` | collect_universe_and_prices | 유니버스, 메타데이터, 운용사 |
| `Price`, `(ETF)-[:HAS_PRICE]->` | collect_universe_and_prices (KIS 일봉 + 현재가) | ETF 가격 시계열 |
| `Stock`, `HOLDS` | collect_holdings (KIS) | 보유종목 (수집일 기준 스냅샷) |
| `Price`, `(Stock)-[:HAS_PRICE]->` | collect_stock_prices_for_dates (KIS 일봉) | 주식 가격 시계열 |
| ETF 수익률 속성 | update_etf_returns | 1D/1W/1M 수익률 |
| `Tag`, `TAGGED` | age_tagging, tag_new_etfs | ETF 테마 분류 |

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
| `ENCRYPTION_KEY` | 포트폴리오 금액 암호화 키 |
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
