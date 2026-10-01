# 데이터 소스 매핑

## 개요

외부 데이터 소스에서 수집하는 데이터와 DB 저장 구조 매핑.

| 데이터 | 소스 | 저장 위치 |
|--------|------|-----------|
| ETF 전체 목록 (코드/이름) | KIS 종목 마스터 파일 (`kospi_code.mst.zip`, 인증 불필요) | AGE `ETF`, RDB `etfs` |
| ETF NAV/순자산/상장주수 (현재 시점) | KIS Open API (ETF/ETN 현재가) | AGE `ETF.net_assets`, 최근 거래일 `Price` |
| ETF 일별 시세 | KIS Open API (국내주식기간별시세) | AGE `Price` |
| ETF 보수율 | 네이버 증권 모바일 API (비공식, `etfAnalysis.totalFee`) | AGE `ETF.expense_ratio` |
| ETF 구성종목 | 한국투자증권 KIS Open API (ETF 구성종목시세) | AGE `Stock`, `HOLDS`, `CURRENT_HOLDS` |
| 주식 일별 시세 | KIS Open API (국내주식기간별시세) | AGE `Price` |
| 영업일 | KIS Open API (기준 ETF 069500 일봉) | - |
| 개장일(휴장일) | KIS Open API (국내휴장일조회) | RDB `market_calendar` |
| 포트폴리오 티커 현재가 | yfinance | RDB `ticker_prices` |

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

`airflow/dags/age_utils.py` (요약). `EXCLUDE_KEYWORDS`, `EXCLUDE_PATTERNS`, `FOREIGN_NAME_KEYWORDS`, `MIN_AUM`은 모듈 상수다. `EXCLUDE_PATTERNS`는 부분 문자열로는 오탐이 나는 대상용 정규식이다(단어 첫머리의 `은` — `은행`은 제외).

```python
MIN_AUM = 500 * 100_000_000  # 500억

def passes_universe_name_filter(name):   # API 호출 전 1차 필터
    if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
        return False
    if any(re.search(p, name) for p in EXCLUDE_PATTERNS):
        return False
    if any(kw.lower() in name_lower or kw in name for kw in FOREIGN_NAME_KEYWORDS):
        return False
    return True

def check_new_universe_candidates(etf_dicts, existing_codes):
    for item in etf_dicts:               # {code, name, net_assets} — net_assets는 KIS 현재가 스냅샷
        if item['code'] in existing_codes:   # 이미 유니버스
            continue
        if item['net_assets'] < MIN_AUM:
            continue
        if not passes_universe_name_filter(item['name']):
            continue
        candidates.append(...)
```

이름 필터를 먼저 적용해, 현재가 API(순자산 조회)는 기존 유니버스 ∪ 이름 필터 통과 ETF에 대해서만 호출한다.

한번 편입된 ETF는 이후 조건에 미달해도 유니버스에서 제거하지 않는다.

---

## 1. ETF 목록 / 시세 수집 (KIS)

### ETF 목록: KIS 종목 마스터 파일

```
GET https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip   (공개 파일, 인증 불필요)
```

`airflow/dags/kis_api_client.py`의 `fetch_etf_master()`. zip 안의 `kospi_code.mst`(cp949)를 행 단위로 읽어, 행 끝 227자 고정폭 영역의 앞 2자리(그룹코드)가 `EF`인 행만 ETF로 취한다 (약 1,175개).

| 위치 | 속성 | 비고 |
|------|------|------|
| 앞부분 `[0:9]` | code | 단축코드 |
| 앞부분 `[21:]` | name | 한글명 |
| 고정폭 영역 `[0:2]` | (그룹코드) | `EF` = ETF |

`age_sync_universe`(유니버스)와 `rdb_sync_metadata`(RDB `etfs`의 code/name 동기화)가 함께 사용한다.

### ETF 현재가 (ETF/ETN 현재가)

```
GET {KIS_BASE_URL}/uapi/etfetn/v1/quotations/inquire-price
tr_id: FHPST02400000
params: FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD={ETF코드}
```

`KISApiClient.get_etf_snapshot(code)`. 날짜 파라미터가 없어 호출 시점 값만 반환한다.

| KIS 필드 | 속성 | 비고 |
|----------|------|------|
| stck_prpr | (현재가) | |
| nav (없으면 prdy_last_nav) | Price.nav | 최근 거래일 Price에만 저장 |
| etf_ntas_ttam | ETF.net_assets, Price.net_assets | 원 단위로 저장. 값이 1억 미만이면 억원 단위로 보고 ×1억 (응답 단위 미확인이라 둔 방어 로직) |
| lstn_stcn | (상장주수) | Price.market_cap = 종가 × 상장주수 |

### ETF 일별 시세 (국내주식기간별시세)

유니버스 ETF마다 `get_daily_bars(code, dates[0], 최근 거래일)`로 일봉을 받는다 (API 상세는 [3절](#3-주식-가격--영업일--휴장일-kis-open-api)).

### DB 매핑 (Apache AGE - ETF 노드 / Price 노드)

| 소스 | 속성 | 저장 위치 | 비고 |
|------|------|-----------|------|
| 마스터 파일 code / name | code / name | ETF | 신규 편입 시 |
| 일봉 stck_bsop_date | date | Price | `YYYY-MM-DD` |
| 일봉 stck_oprc / stck_hgpr / stck_lwpr / stck_clpr | open / high / low / close | Price | 모든 날짜 |
| 일봉 acml_vol | volume | Price | 모든 날짜 |
| 일봉 acml_tr_pbmn | trade_value | Price | 거래대금, 모든 날짜 |
| 현재가 nav | nav | Price | 최근 거래일만 (이전 날짜는 null) |
| 현재가 etf_ntas_ttam | net_assets | ETF, Price | 최근 거래일만 (이전 날짜는 null) |
| 일봉 종가 × 현재가 lstn_stcn | market_cap | Price | 최근 거래일만 (이전 날짜는 null) |

### 추가 메타정보

| 속성 | 소스 | 비고 |
|------|------|------|
| expense_ratio | 네이버 증권 `GET https://m.stock.naver.com/api/stock/{code}/etfAnalysis`의 `totalFee` (`airflow/dags/naver_client.py`) | 신규 편입 후보만 조회. 소수점 2째자리 올림. 비공식 API라 실패 시 `expense_ratio` 미설정 |
| 운용사 | ETF 이름 prefix (KODEX, TIGER, RISE 등) → `ETF_COMPANY_MAP` | `(ETF)-[:MANAGED_BY]->(Company)` |

RDB `etfs` 테이블에는 `rdb_sync_metadata` DAG이 같은 마스터 파일로 전체 ETF의 code/name만 동기화한다.

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
- **비중 상위 30개만 반환한다.** 연속 조회(`tr_cont`)를 지원하지 않아 다음 페이지를 요청해도 같은 30개가 온다. 구성종목이 많은 지수형 ETF는 비중 합이 100%에 못 미친다(KODEX 200: 202종목 중 30개, 합 약 85%). HOLDS는 "XX·YY 비중이 큰 ETF" 같은 챗봇 질의에 쓰는 것이라 상위 종목만으로 충분하다고 보고 그대로 둔다.
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

`CURRENT_HOLDS`는 같은 속성(date, weight, shares)을 HOLDS에서 그대로 복사한다.

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
# 3) refresh_current_holds(date): 그날 HOLDS가 있는 ETF 중 CURRENT_HOLDS 날짜가 date 이하인 ETF만
#    CURRENT_HOLDS 삭제 → 그날 HOLDS로 재생성 (KIS 실패 ETF는 이전 구성종목 유지, 재실행해도 결과 동일)
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
| acml_tr_pbmn | (trade_value) | 거래대금. ETF Price에만 저장 |
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
| KIS 종목 마스터 파일 | cp949 고정폭 포맷 (KIS 공식 샘플 `kis_kospi_code_mst.py` 기준 행 끝 227자) | 227자 이하 행·그룹코드 `EF`가 아닌 행은 건너뜀 |
| KIS Open API | 구성종목·ETF 현재가 날짜 지정 불가, 토큰 발급 1분 1회, 초당 20건, 일봉 호출당 100건, 휴장일조회 1일 1회 권장 | 최근 거래일로 기록, `kis_tokens` 캐시, 0.06초 간격 + 재시도, 100일 단위 페이지네이션, `market_calendar` 캐시 |
| 네이버 증권 모바일 API | 비공식 API (사전 공지 없이 변경 가능) | 신규 ETF만 조회, 0.1초 간격, 실패 시 보수율 생략 |

### 에러 처리

| 상황 | 처리 |
|------|------|
| `KIS_APP_KEY`/`KIS_APP_SECRET` 없음 | 유니버스/ETF 가격·구성종목·주식 가격 수집 skip, 경고 로그 |
| 개별 ETF 현재가/일봉 조회 실패 | 해당 ETF만 skip, 경고 로그 |
| 개별 ETF 구성종목 조회 실패 | 해당 ETF만 skip, 실패 건수 로그 |
| HOLDS 배치 저장 실패 | 해당 배치 rollback 후 다음 배치 진행 |
| 개별 종목 시세 실패 | 해당 종목만 skip (5건까지 상세 로그) |
| KIS 키 없음 (영업일/휴장일) | 영업일 빈 리스트 → 수집 없음, 휴장일 판정 불가 → 수집 진행 |

---

## 6. 초기 데이터 로드

백필 DAG는 없다. 신규 환경에서 `age_sync_universe` DAG을 처음 실행하면 AGE가 비어 있음을 감지해 **최근 거래일 하루**의 유니버스·ETF 가격·구성종목·주식 가격만 수집한다.
이후 매일 증분으로 쌓이며, 1주/1개월 수익률·비중 변화는 데이터가 그만큼 쌓인 뒤부터 계산된다. 과거 이력이 필요해지면 그때 백필을 추가한다.
태그는 `age_tagging` DAG으로 부여한다.
