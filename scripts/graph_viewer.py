"""
ETF Atlas Graph Viewer
Apache AGE 그래프 데이터를 시각화하는 Streamlit 앱
"""

import streamlit as st
import psycopg2
import pandas as pd
import networkx as nx
from pyvis.network import Network
import tempfile
import os

# 페이지 설정
st.set_page_config(
    page_title="ETF Atlas Graph Viewer",
    page_icon="📊",
    layout="wide"
)

# DB 연결 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "etf_atlas"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}


@st.cache_resource
def get_connection():
    """DB 연결 생성"""
    return psycopg2.connect(**DB_CONFIG)


def init_age(conn):
    """Apache AGE 초기화"""
    cur = conn.cursor()
    cur.execute("LOAD 'age';")
    cur.execute("SET search_path = ag_catalog, '$user', public;")
    return cur


def execute_cypher(cur, query):
    """Cypher 쿼리 실행"""
    sql = f"""
        SELECT * FROM cypher('etf_graph', $$
            {query}
        $$) as (result agtype);
    """
    cur.execute(sql)
    return cur.fetchall()


def get_etf_count(cur):
    """ETF 노드 수 조회"""
    result = execute_cypher(cur, "MATCH (e:ETF) RETURN count(e)")
    return int(result[0][0]) if result else 0


def get_stock_count(cur):
    """Stock 노드 수 조회"""
    result = execute_cypher(cur, "MATCH (s:Stock) RETURN count(s)")
    return int(result[0][0]) if result else 0


def get_holds_count(cur):
    """HOLDS 엣지 수 조회"""
    result = execute_cypher(cur, "MATCH ()-[h:HOLDS]->() RETURN count(h)")
    return int(result[0][0]) if result else 0


def get_etf_list(cur, limit=100):
    """ETF 목록 조회"""
    sql = """
        SELECT * FROM cypher('etf_graph', $$
            MATCH (e:ETF)
            RETURN e.code, e.name
            ORDER BY e.code
            LIMIT %s
        $$) as (code agtype, name agtype);
    """
    cur.execute(sql % limit)
    results = cur.fetchall()

    data = []
    for row in results:
        code = str(row[0]).strip('"') if row[0] else ""
        name = str(row[1]).strip('"') if row[1] else ""
        data.append({"code": code, "name": name})

    return pd.DataFrame(data)


def get_etf_holdings(cur, etf_code, date=None):
    """특정 ETF의 구성종목 조회"""
    if date:
        query = f"""
            MATCH (e:ETF {{code: '{etf_code}'}})-[h:HOLDS {{date: '{date}'}}]->(s:Stock)
            RETURN s.code, s.name, h.weight, h.shares
            ORDER BY h.weight DESC
        """
    else:
        query = f"""
            MATCH (e:ETF {{code: '{etf_code}'}})-[h:HOLDS]->(s:Stock)
            RETURN s.code, s.name, h.weight, h.shares, h.date
            ORDER BY h.date DESC, h.weight DESC
            LIMIT 100
        """

    sql = f"""
        SELECT * FROM cypher('etf_graph', $$
            {query}
        $$) as (stock_code agtype, stock_name agtype, weight agtype, shares agtype{", date agtype" if not date else ""});
    """
    cur.execute(sql)
    results = cur.fetchall()

    data = []
    for row in results:
        item = {
            "stock_code": str(row[0]).strip('"') if row[0] else "",
            "stock_name": str(row[1]).strip('"') if row[1] else "",
            "weight": float(row[2]) if row[2] else 0,
            "shares": int(row[3]) if row[3] else 0,
        }
        if not date and len(row) > 4:
            item["date"] = str(row[4]).strip('"') if row[4] else ""
        data.append(item)

    return pd.DataFrame(data)


def get_stock_etfs(cur, stock_code):
    """특정 종목을 보유한 ETF 목록"""
    query = f"""
        MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}})
        RETURN e.code, e.name, h.weight, h.date
        ORDER BY h.weight DESC
    """

    sql = f"""
        SELECT * FROM cypher('etf_graph', $$
            {query}
        $$) as (etf_code agtype, etf_name agtype, weight agtype, date agtype);
    """
    cur.execute(sql)
    results = cur.fetchall()

    data = []
    for row in results:
        data.append({
            "etf_code": str(row[0]).strip('"') if row[0] else "",
            "etf_name": str(row[1]).strip('"') if row[1] else "",
            "weight": float(row[2]) if row[2] else 0,
            "date": str(row[3]).strip('"') if row[3] else "",
        })

    return pd.DataFrame(data)


def create_etf_graph(cur, etf_code, limit=20):
    """ETF 중심 그래프 생성"""
    G = nx.Graph()

    # ETF 노드 추가
    G.add_node(etf_code, label=etf_code, color="#4CAF50", size=30, title="ETF")

    # 구성종목 조회
    df = get_etf_holdings(cur, etf_code)

    if df.empty:
        return G

    # 상위 N개 종목만 표시
    df = df.head(limit)

    for _, row in df.iterrows():
        stock_code = row["stock_code"]
        stock_name = row["stock_name"]
        weight = row["weight"]

        # Stock 노드 추가
        G.add_node(
            stock_code,
            label=f"{stock_name}\n({weight:.1f}%)",
            color="#2196F3",
            size=15 + weight,
            title=f"{stock_name} ({stock_code})\n비중: {weight:.2f}%"
        )

        # HOLDS 엣지 추가
        G.add_edge(etf_code, stock_code, weight=weight)

    return G


def create_stock_graph(cur, stock_code, limit=20):
    """종목 중심 그래프 생성 (역추적)"""
    G = nx.Graph()

    # Stock 노드 추가
    G.add_node(stock_code, label=stock_code, color="#2196F3", size=30, title="Stock")

    # 보유 ETF 조회
    df = get_stock_etfs(cur, stock_code)

    if df.empty:
        return G

    # 상위 N개 ETF만 표시
    df = df.head(limit)

    for _, row in df.iterrows():
        etf_code = row["etf_code"]
        etf_name = row["etf_name"]
        weight = row["weight"]

        # ETF 노드 추가
        G.add_node(
            etf_code,
            label=f"{etf_name[:10]}...\n({weight:.1f}%)" if len(etf_name) > 10 else f"{etf_name}\n({weight:.1f}%)",
            color="#4CAF50",
            size=15 + weight,
            title=f"{etf_name} ({etf_code})\n비중: {weight:.2f}%"
        )

        # HOLDS 엣지 추가
        G.add_edge(etf_code, stock_code, weight=weight)

    return G


def render_graph(G, height="500px"):
    """NetworkX 그래프를 PyVis로 렌더링"""
    if len(G.nodes()) == 0:
        st.warning("표시할 데이터가 없습니다.")
        return

    net = Network(height=height, width="100%", bgcolor="#222222", font_color="white")
    net.from_nx(G)
    net.set_options("""
    {
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "centralGravity": 0.01,
                "springLength": 100,
                "springConstant": 0.08
            },
            "maxVelocity": 50,
            "solver": "forceAtlas2Based",
            "timestep": 0.35,
            "stabilization": {"iterations": 150}
        }
    }
    """)

    # 임시 파일에 저장 후 표시
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as f:
        net.save_graph(f.name)
        with open(f.name, "r", encoding="utf-8") as html_file:
            html_content = html_file.read()
        os.unlink(f.name)

    st.components.v1.html(html_content, height=int(height.replace("px", "")) + 50)


def main():
    st.title("📊 ETF Atlas Graph Viewer")
    st.markdown("Apache AGE에 저장된 ETF-Stock 관계 그래프를 시각화합니다.")

    # DB 연결
    try:
        conn = get_connection()
        cur = init_age(conn)
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        st.info("DB 설정을 확인하세요. 환경변수: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
        return

    # 사이드바: 통계
    with st.sidebar:
        st.header("📈 그래프 통계")

        col1, col2 = st.columns(2)
        with col1:
            etf_count = get_etf_count(cur)
            st.metric("ETF 노드", etf_count)
        with col2:
            stock_count = get_stock_count(cur)
            st.metric("Stock 노드", stock_count)

        holds_count = get_holds_count(cur)
        st.metric("HOLDS 엣지", holds_count)

        st.divider()
        st.header("⚙️ 설정")
        node_limit = st.slider("표시할 노드 수", 5, 50, 20)

    # 탭 구성
    tab1, tab2, tab3 = st.tabs(["🔍 ETF 탐색", "🔄 종목 역추적", "📋 데이터 조회"])

    with tab1:
        st.subheader("ETF 구성종목 그래프")

        # ETF 목록 조회
        etf_df = get_etf_list(cur, limit=1000)

        if etf_df.empty:
            st.warning("ETF 데이터가 없습니다.")
        else:
            # ETF 선택
            etf_options = [f"{row['code']} - {row['name']}" for _, row in etf_df.iterrows()]
            selected_etf = st.selectbox("ETF 선택", etf_options)

            if selected_etf:
                etf_code = selected_etf.split(" - ")[0]

                # 그래프 생성 및 표시
                G = create_etf_graph(cur, etf_code, limit=node_limit)
                render_graph(G, height="600px")

                # 구성종목 테이블
                st.subheader("구성종목 목록")
                holdings_df = get_etf_holdings(cur, etf_code)
                if not holdings_df.empty:
                    st.dataframe(holdings_df, use_container_width=True)
                else:
                    st.info("구성종목 데이터가 없습니다.")

    with tab2:
        st.subheader("종목 → ETF 역추적")

        stock_code = st.text_input("종목 코드 입력 (예: 005930)", value="005930")

        if stock_code:
            # 그래프 생성 및 표시
            G = create_stock_graph(cur, stock_code, limit=node_limit)
            render_graph(G, height="600px")

            # ETF 목록 테이블
            st.subheader(f"{stock_code}을 보유한 ETF 목록")
            etf_list_df = get_stock_etfs(cur, stock_code)
            if not etf_list_df.empty:
                st.dataframe(etf_list_df, use_container_width=True)
            else:
                st.info("해당 종목을 보유한 ETF가 없습니다.")

    with tab3:
        st.subheader("데이터 조회")

        query_type = st.radio("조회 유형", ["ETF 목록", "Stock 목록", "커스텀 Cypher"])

        if query_type == "ETF 목록":
            df = get_etf_list(cur, limit=500)
            st.dataframe(df, use_container_width=True)
            st.download_button("CSV 다운로드", df.to_csv(index=False), "etf_list.csv", "text/csv")

        elif query_type == "Stock 목록":
            sql = """
                SELECT * FROM cypher('etf_graph', $$
                    MATCH (s:Stock)
                    RETURN s.code, s.name
                    ORDER BY s.code
                    LIMIT 500
                $$) as (code agtype, name agtype);
            """
            cur.execute(sql)
            results = cur.fetchall()
            data = [{"code": str(r[0]).strip('"'), "name": str(r[1]).strip('"')} for r in results]
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            st.download_button("CSV 다운로드", df.to_csv(index=False), "stock_list.csv", "text/csv")

        else:
            st.warning("주의: Cypher 쿼리는 읽기 전용으로 사용하세요.")
            custom_query = st.text_area(
                "Cypher 쿼리",
                value="MATCH (e:ETF) RETURN e.code, e.name LIMIT 10",
                height=100
            )

            if st.button("실행"):
                try:
                    sql = f"""
                        SELECT * FROM cypher('etf_graph', $$
                            {custom_query}
                        $$) as (result agtype);
                    """
                    cur.execute(sql)
                    results = cur.fetchall()
                    st.json([str(r[0]) for r in results])
                except Exception as e:
                    st.error(f"쿼리 실행 오류: {e}")


if __name__ == "__main__":
    main()
