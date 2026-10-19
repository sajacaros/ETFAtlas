"""ETF Atlas가 무엇을 수집하는지 — 분석할 수 없는 대상을 안내할 때 쓰는 문구.

조건 자체는 수집 DAG에 있다 (airflow/dags/age_utils.py의 MIN_AUM, EXCLUDE_KEYWORDS, FOREIGN_NAME_KEYWORDS).
그쪽을 바꾸면 이 문구도 같이 바꾼다.
"""

UNIVERSE_DESCRIPTION = (
    "국내 주식형 ETF 중 순자산 500억 원 이상인 ETF(해외·레버리지·인버스·합성·파생·커버드콜·채권·원자재·통화·리츠 제외)"
)
# ETF마다 구성종목을 비중 상위 몇 개까지 받는지 (KIS 구성종목 API 한도)
HOLDINGS_PER_ETF = 30

STOCK_SCOPE = (
    f"ETF Atlas는 {UNIVERSE_DESCRIPTION}를 수집하고, "
    f"그 ETF들이 담은 종목(ETF마다 비중 상위 {HOLDINGS_PER_ETF}개)만 분석합니다."
)
