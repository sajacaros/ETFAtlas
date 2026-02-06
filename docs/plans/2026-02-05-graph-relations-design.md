# ETF 운용사 및 Stock 섹터 관계 추가 설계

## 개요

Apache AGE 성능 테스트를 위해 다양한 관계를 추가한다:
- ETF 운용사: `(ETF)-[:MANAGED_BY]->(Company)`
- Stock 섹터: `(Stock)-[:BELONGS_TO]->(Sector)-[:PART_OF]->(Market)`

## 그래프 구조

**새로운 노드:**
```
(Company {name})           -- 운용사 (삼성자산운용, 미래에셋자산운용 등)
(Market {name})            -- 시장 (KOSPI, KOSDAQ)
(Sector {name})            -- 업종 (전기전자, 서비스업 등)
```

**새로운 관계:**
```
(ETF)-[:MANAGED_BY]->(Company)
(Stock)-[:BELONGS_TO]->(Sector)-[:PART_OF]->(Market)
```

**전체 그래프 구조:**
```
(Company)<-[:MANAGED_BY]-(ETF)-[:HOLDS]->(Stock)-[:BELONGS_TO]->(Sector)-[:PART_OF]->(Market)
                           |
                           +-[:HAS_CHANGE]->(Change)
```

---

## ETF 운용사 매핑

ETF 이름 prefix로 운용사를 매핑한다.

```python
ETF_COMPANY_MAP = {
    # 삼성
    'KODEX': '삼성자산운용',
    'KoAct': '삼성액티브자산운용',

    # 미래에셋
    'TIGER': '미래에셋자산운용',

    # KB
    'RISE': 'KB자산운용',

    # 한국투자
    'ACE': '한국투자신탁운용',

    # NH아문디
    'HANARO': 'NH아문디자산운용',

    # 신한
    'SOL': '신한자산운용',

    # 한화
    'PLUS': '한화자산운용',

    # 키움
    'KIWOOM': '키움자산운용',

    # 하나
    '1Q': '하나자산운용',

    # 타임폴리오
    'TIMEFOLIO': '타임폴리오자산운용',
    'TIME': '타임폴리오자산운용',

    # 우리
    'WON': '우리자산운용',

    # 기타
    '마이다스': '마이다스자산운용',
    '파워': '교보악사자산운용',
    'BNK': 'BNK자산운용',
    'DAISHIN343': '대신자산운용',
    'HK': '흥국자산운용',
    'UNICORN': '현대자산운용',
}
```

**수집 로직 (`collect_etf_metadata` 수정):**
```python
def get_company_from_etf_name(name: str) -> str:
    for prefix, company in ETF_COMPANY_MAP.items():
        if name.startswith(prefix):
            return company
    return '기타'

# Company 노드 생성 및 관계 연결
company = get_company_from_etf_name(etf_name)
MERGE (c:Company {name: $company})
MERGE (e:ETF {code: $code})-[:MANAGED_BY]->(c)
```

---

## Stock 섹터 수집

KRX 업종 분류를 사용하여 2레벨 계층(Market > Sector)으로 관리한다.

**데이터 소스:**
```python
from pykrx import stock

# 시장별 종목+업종 조회
kospi = stock.get_market_ticker_and_name("20260205", "KOSPI")
kosdaq = stock.get_market_ticker_and_name("20260205", "KOSDAQ")
```

**수집 로직 (`collect_holdings` 수정):**
```python
# Stock 저장 시 섹터 정보도 함께 저장
# 1. Market 노드 생성
MERGE (m:Market {name: $market})  # "KOSPI" or "KOSDAQ"

# 2. Sector 노드 생성 및 Market 연결
MERGE (sec:Sector {name: $sector})
MERGE (sec)-[:PART_OF]->(m)

# 3. Stock - Sector 관계 생성
MATCH (s:Stock {code: $code})
MERGE (s)-[:BELONGS_TO]->(sec)
```

---

## 변경 파일 목록

1. `airflow/dags/etf_daily_etl.py`
   - `ETF_COMPANY_MAP` 상수 추가
   - `get_company_from_etf_name()` 함수 추가
   - `collect_etf_metadata`: Company 노드 생성 및 MANAGED_BY 관계 추가
   - `collect_holdings`: Market, Sector 노드 생성 및 관계 추가
