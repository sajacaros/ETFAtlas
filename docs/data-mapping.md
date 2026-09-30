# 데이터 소스 매핑

## 개요

외부 데이터 소스에서 수집하는 데이터와 DB 저장 구조 매핑.

| 데이터 | 소스 | 저장 위치 |
|--------|------|-----------|
| ETF 목록/일별 시세/순자산 | KRX Open API (`etf_bydd_trd`) | AGE `ETF`, `Price` |
| ETF 보수율 | 네이버 증권 모바일 API (비공식, `etfAnalysis.totalFee`) | AGE `ETF.expense_ratio` |
| ETF 구성종목 | 한국투자증권 KIS Open API (ETF 구성종목시세) | AGE `Stock`, `HOLDS` |
| 주식 일별 시세 | KIS Open API (국내주식기간별시세) | AGE `Price` |
| 영업일 | KIS Open API (기준 ETF 069500 일봉) | - |
| 개장일(휴장일) | KIS Open API (국내휴장일조회) | RDB `market_calendar` |
| 포트폴리오 티커 현재가, ETF 종가 이력 백필 | yfinance | RDB `ticker_prices` |

수집 흐름과 DAG 구조는 [dags.md](dags.md) 참고.

---

## ETF 유니버스 정의

### 포함 조건

| 조건 | 설명 |
|------|------|
| 국내 주식형 ETF | 국내 상장 주식으로 구성 |
| 순자산 500억 이상 | 유동성 확보 |

### 제외 조건

| 조건 | 제외 이유 |
|------|----------|
| 해외 주식형 ETF | 미국, 중국, 글로벌, S&P, NASDAQ, MSCI, 해외 개별종목명 등 — 구성종목이 국내 종목 아님 |
| 합성/파생 ETF | 실물 구성종목 없음 (스왑·선물·옵션) |
| 레버리지/인버스 ETF | 파생 상품, 일별 수익률 추종 |
| 커버드콜/프리미엄 ETF | 옵션 전략 포함 |
| 채권 ETF (TDF 포함) | 주식 종목 아님 |
| 원자재/금/은 ETF | 주식 종목 아님 |
| 통화/머니마켓 ETF | 주식 종목 아님 |
| 리츠 ETF | 주식 종목 아님 |

### 필터링 로직

`airflow/dags/age_utils.py`의 `check_new_universe_candidates()` (요약):

```python
MIN_AUM = 500 * 100_000_000  # 500억

for item in krx_data_dicts:
    if item['code'] in existing_codes:      # 이미 유니버스
        continue
    if item['net_assets'] < MIN_AUM:
        continue
    if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
        continue
    if any(kw.lower() in name_lower or kw in name for kw in FOREIGN_NAME_KEYWORDS):
        continue
    candidates.append(...)
```

한번 편입된 ETF는 이후 조건에 미달해도 유니버스에서 제거하지 않는다.

---

## 1. ETF 목록 / 시세 수집 (KRX Open API)

### API

```
GET https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd?basDd=YYYYMMDD
헤더: AUTH_KEY: {KRX_AUTH_KEY}
```

`airflow/dags/krx_api_client.py`의 `KRXApiClient.get_etf_daily_trading(date)`. 해당 날짜에 데이터가 없으면(휴장일) 최대 7일 전까지 거슬러 올라가 실제 거래일을 찾는다.

### DB 매핑 (Apache AGE - ETF 노드 / Price 노드)

| KRX 필드 | 속성 | 저장 위치 | 비고 |
|----------|------|-----------|------|
| ISU_CD | code | ETF | PK |
| ISU_NM | name | ETF | |
| INVSTASST_NETASST_TOTAMT | net_assets | ETF, Price | 순자산총액 |
| BAS_DD | date | Price | `YYYY-MM-DD` |
| TDD_OPNPRC / TDD_HGPRC / TDD_LWPRC / TDD_CLSPRC | open / high / low / close | Price | |
| ACC_TRDVOL | volume | Price | |
| ACC_TRDVAL | trade_value | Price | 거래대금 |
| NAV | nav | Price | |
| MKTCAP | market_cap | Price | |

### 추가 메타정보

| 속성 | 소스 | 비고 |
|------|------|------|
| expense_ratio | 네이버 증권 `GET https://m.stock.naver.com/api/stock/{code}/etfAnalysis`의 `totalFee` (`airflow/dags/naver_client.py`) | 신규 편입 후보만 조회. 소수점 2째자리 올림. 비공식 API라 실패 시 `expense_ratio` 미설정 |
| 운용사 | ETF 이름 prefix (KODEX, TIGER, RISE 등) → `ETF_COMPANY_MAP` | `(ETF)-[:MANAGED_BY]->(Company)` |

RDB `etfs` 테이블에는 `rdb_sync_metadata` DAG이 같은 KRX API로 전체 ETF의 code/name만 동기화한다.

---

## 2. ETF 구성종목 수집 (KIS Open API)

### API

```
GET {KIS_BASE_URL}/uapi/etfetn/v1/quotations/inquire-component-stock-price
tr_id: FHKST121600C0
params: FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD={ETF코드}, FID_COND_SCR_DIV_CODE=11216
```

`airflow/dags/kis_api_client.py`의 `KISApiClient.get_etf_components(etf_code)`. 기본 `KIS_BASE_URL`은 실전투자 `https://openapi.koreainvestment.com:9443`.

- **날짜 파라미터가 없다.** 항상 호출 시점의 구성종목을 반환하므로, 수집한 스냅샷을 최근 거래일 날짜의 HOLDS로 저장한다. 과거 구성종목 백필은 불가능하다.
- 접근 토큰(`/oauth2/tokenP`)은 24시간 유효, 발급은 1분 1회 제한 → `kis_tokens` 테이블에 캐시.
- 초당 호출 제한(실전 20건/s) 대비 호출 간 최소 0.06초 간격, 제한 초과(`EGW00201`) 시 재시도.

### 반환 데이터 (output2 한 행)

| KIS 필드 | 설명 |
|----------|------|
| stck_shrn_iscd | 주식 단축 종목코드 |
| hts_kor_isnm | HTS 한글 종목명 |
| etf_cnfg_issu_rlim | ETF 구성종목 비중 (%) |
| etf_vltn_amt | ETF 구성종목 내 평가금액 |
| stck_prpr | 주식 현재가 |

### DB 매핑 (Apache AGE - HOLDS 엣지 / Stock 노드)

| KIS 필드 | DB 필드 | 타입 | 비고 |
|----------|---------|------|------|
| stck_shrn_iscd | Stock.code | string | Stock 노드 연결 |
| hts_kor_isnm | Stock.name | string | ETF 종목이면 AGE ETF 노드 이름 우선 |
| etf_cnfg_issu_rlim | HOLDS.weight | float | |
| etf_vltn_amt / stck_prpr | HOLDS.shares | int | API에 수량 필드가 없어 역산한 **추정치** |
| (수집 기준 거래일) | HOLDS.date | string | `YYYY-MM-DD` |

### 저장 로직

`age_utils.collect_holdings(etf_codes, bd)` (요약):

```python
for ticker in remaining_etfs:              # 같은 날짜 HOLDS가 이미 있는 ETF는 제외
    components = [
        c for c in kis.get_etf_components(ticker)
        if is_listed_security_code(c.stock_code)  # 주식/ETF만 (채권·현금·선물 제외)
    ]
    components.sort(key=lambda c: c.weight, reverse=True)
    for c in components[:30]:              # 비중 상위 30개
        all_holds.append({'etf_code': ticker, 'stock_code': c.stock_code,
                          'date': date_str, 'weight': c.weight, 'shares': c.shares})

# is_listed_security_code: KRX 상장 단축코드 ^[0-9][0-9A-Z]{5}$ 이면서 설정현금액(010010)이 아닌 코드
# (AGE에 이미 있는 코드로 거르지 않으므로 ETF 노드만 있는 빈 DB에서도 주식 구성종목이 저장된다)

# 1) Stock MERGE → name, is_etf SET
# 2) HOLDS MERGE {date} → weight, shares SET (50개 ETF 단위 커밋)
```

---

## 3. 주식 가격 / 영업일 / 휴장일 (KIS Open API)

### 국내주식기간별시세 (일봉)

```
GET {KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
tr_id: FHKST03010100
params: FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD={종목코드}, FID_INPUT_DATE_1={시작}, FID_INPUT_DATE_2={종료},
        FID_PERIOD_DIV_CODE=D, FID_ORG_ADJ_PRC=0
```

`KISApiClient.get_daily_bars(code, start, end)`. 호출당 최대 100건이라 가장 오래된 날짜 이전으로 종료일을 옮겨 가며 페이지네이션한다.

| KIS 필드 | DB 필드 (Price) | 비고 |
|----------|-----------------|------|
| stck_bsop_date | date | `YYYY-MM-DD` |
| stck_oprc / stck_hgpr / stck_lwpr / stck_clpr | open / high / low / close | float |
| acml_vol | volume | int |
| prdy_vrss, prdy_vrss_sign | change_rate | `prdy_vrss / (종가 - prdy_vrss) × 100`. 부호 코드 4(하한)/5(하락)이면 음수로 보정 |

`collect_stock_prices_for_dates(dates)`는 `is_etf = false`인 Stock마다 `get_daily_bars(code, min(dates), max(dates))`를 한 번 호출하고(종목×날짜 호출 없음), AGE에 이미 있는 (종목, 날짜)는 건너뛰며, 50종목마다 커밋한다. `(Stock)-[:HAS_PRICE]->(Price)`로 연결한다.

### 영업일

`get_business_days(from_date, to_date)`는 기준 ETF `069500`(KODEX 200, `BUSINESS_DAY_REFERENCE_CODE`)의 일봉을 같은 API로 받아 그 날짜 목록을 영업일로 사용한다.

### 국내휴장일조회

```
GET {KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/chk-holiday
tr_id: CTCA0903R
params: BASS_DT={YYYYMMDD}
```

응답의 `opnd_yn == 'Y'`면 개장일. KIS 요청에 따라 가급적 1일 1회만 호출하도록 `rdb_realtime_prices`가 결과를 `market_calendar(date PK, is_open, checked_at)`에 캐시한다. 판정할 수 없으면(키 없음·오류) 수집을 진행한다.

---

## 4. 포트폴리오 변화 감지

별도 Change 노드나 변화 감지 태스크 없이, 조회 시점에 두 날짜의 HOLDS 스냅샷을 비교한다 (`GraphService.get_etf_holdings_changes`).

### 로직

```python
current, actual_date = self._get_holdings_at(etf_code, base_date)     # 기준일 이하 최근 HOLDS
previous, prev_actual = self._get_holdings_at(etf_code, prev_date)    # 1d: 이전 거래일, 1w: -7일, 1m: -30일

for code in set(current) | set(previous):
    if curr and not prev:   change_type = "added"
    elif prev and not curr: change_type = "removed"
    elif cw > pw:           change_type = "increased"
    elif cw < pw:           change_type = "decreased"
    else:                   change_type = "unchanged"
```

반환 필드: `stock_code`, `stock_name`, `change_type`, `current_weight`, `previous_weight`, `weight_change`.

> KIS API는 과거 구성종목을 조회할 수 없으므로 비교 가능한 이력은 HOLDS 수집을 시작한 날부터 쌓인다.

---

## 5. 데이터 수집 주의사항

### 소스별 제한사항

| 소스 | 제한 | 대응 |
|------|------|------|
| KRX Open API | 휴장일 응답 없음 | 최대 7일 전까지 거래일 탐색, 이미 수집한 거래일 skip |
| KIS Open API | 구성종목 날짜 지정 불가, 토큰 발급 1분 1회, 초당 20건, 일봉 호출당 100건, 휴장일조회 1일 1회 권장 | 최근 거래일로 기록, `kis_tokens` 캐시, 0.06초 간격 + 재시도, 100일 단위 페이지네이션, `market_calendar` 캐시 |
| 네이버 증권 모바일 API | 비공식 API (사전 공지 없이 변경 가능) | 신규 ETF만 조회, 0.1초 간격, 실패 시 보수율 생략 |

### 에러 처리

| 상황 | 처리 |
|------|------|
| `KRX_AUTH_KEY` 없음 | 빈 결과 반환, 경고 로그 |
| `KIS_APP_KEY`/`KIS_APP_SECRET` 없음 | 구성종목 수집 skip, 경고 로그 |
| 개별 ETF 구성종목 조회 실패 | 해당 ETF만 skip, 실패 건수 로그 |
| HOLDS 배치 저장 실패 | 해당 배치 rollback 후 다음 배치 진행 |
| 개별 종목 시세 실패 | 해당 종목만 skip (5건까지 상세 로그) |
| KIS 키 없음 (영업일/휴장일) | 영업일 빈 리스트 → 수집 없음, 휴장일 판정 불가 → 수집 진행 |

---

## 6. 초기 데이터 로드

신규 환경에서는 `age_backfill` DAG을 수동 트리거한다.

- 유니버스/ETF 가격/주식 가격: 고정 시작일 `2026-01-02`부터 최근 영업일까지 일괄 수집
- 구성종목(HOLDS): 현재 스냅샷 1회만 최근 거래일로 저장 (과거 백필 없음)
- 이후 `age_sync_universe` DAG이 증분 수집을 이어받고, 태그는 `age_tagging` DAG으로 부여
