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
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    /* 메인 컨테이너 */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* 헤더 스타일 */
    h1 {
        background: linear-gradient(120deg, #1e3a5f 0%, #2d5a87 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }

    /* 사이드바 스타일 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
    }

    section[data-testid="stSidebar"] .stMarkdown h2 {
        color: #1e3a5f;
        font-size: 1.1rem;
        font-weight: 600;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #3b82f6;
        margin-bottom: 1rem;
    }

    /* 메트릭 카드 스타일 */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s, box-shadow 0.2s;
    }

    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    div[data-testid="stMetric"] label {
        color: #64748b;
        font-weight: 500;
        font-size: 0.85rem;
    }

    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #1e3a5f;
        font-weight: 700;
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #f1f5f9;
        padding: 0.5rem;
        border-radius: 12px;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 500;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        color: white;
    }

    /* 데이터프레임 스타일 */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    }

    /* 버튼 스타일 */
    .stButton > button {
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 500;
        transition: all 0.2s;
    }

    .stButton > button:hover {
        background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
    }

    /* 다운로드 버튼 */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
        border: none;
        border-radius: 8px;
    }

    .stDownloadButton > button:hover {
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
    }

    /* 셀렉트박스 스타일 */
    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1px solid #e2e8f0;
    }

    /* 텍스트 인풋 스타일 */
    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 1px solid #e2e8f0;
    }

    /* 경고/정보 메시지 스타일 */
    .stAlert {
        border-radius: 12px;
    }

    /* 서브헤더 스타일 */
    .stSubheader {
        color: #1e3a5f;
        font-weight: 600;
    }

    /* 카드 컨테이너 */
    .card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        margin-bottom: 1rem;
    }

    /* 구분선 스타일 */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, #e2e8f0, #3b82f6, #e2e8f0);
        margin: 1.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# 색상 테마
COLORS = {
    "etf_primary": "#3b82f6",      # 밝은 파랑
    "etf_secondary": "#1d4ed8",    # 진한 파랑
    "stock_primary": "#10b981",    # 밝은 초록
    "stock_secondary": "#059669",  # 진한 초록
    "edge_color": "#94a3b8",       # 회색
    "highlight": "#f59e0b",        # 주황 (하이라이트)
    "background": "#ffffff",       # 배경
    "text": "#1e293b",             # 텍스트
}

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
        # NaN 체크를 위해 pd.notna 사용
        item = {
            "종목코드": str(row[0]).strip('"') if row[0] else "",
            "종목명": str(row[1]).strip('"') if row[1] else "",
            "비중(%)": float(row[2]) if pd.notna(row[2]) else 0,
            "보유수량": int(row[3]) if pd.notna(row[3]) else 0,
        }
        if not date and len(row) > 4:
            item["기준일"] = str(row[4]).strip('"') if row[4] else ""
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
            "ETF코드": str(row[0]).strip('"') if row[0] else "",
            "ETF명": str(row[1]).strip('"') if row[1] else "",
            "비중(%)": float(row[2]) if pd.notna(row[2]) else 0,
            "기준일": str(row[3]).strip('"') if row[3] else "",
        })

    return pd.DataFrame(data)


def create_etf_graph(cur, etf_code, etf_name, limit=20):
    """ETF 중심 그래프 생성"""
    G = nx.Graph()

    # ETF 노드 추가
    G.add_node(
        etf_code,
        label=f"{etf_name}\n({etf_code})" if etf_name else etf_code,
        color=COLORS["etf_primary"],
        size=40,
        title=f"ETF: {etf_name} ({etf_code})",
        font={"size": 14, "color": "#1e293b", "face": "arial", "bold": True},
        borderWidth=3,
        borderWidthSelected=5,
        shadow=True
    )

    # 구성종목 조회
    df = get_etf_holdings(cur, etf_code)

    if df.empty:
        return G

    # 상위 N개 종목만 표시
    df = df.head(limit)
    max_weight = df["비중(%)"].max() if not df.empty else 1
    # max_weight가 0이거나 NaN인 경우 1로 설정
    if pd.isna(max_weight) or max_weight == 0:
        max_weight = 1

    for _, row in df.iterrows():
        stock_code = row["종목코드"]
        stock_name = row["종목명"]
        weight = row["비중(%)"]

        # weight가 NaN인 경우 0으로 처리
        if pd.isna(weight):
            weight = 0

        # 크기 계산 (비중에 비례)
        node_size = 15 + (weight / max_weight) * 25

        # Stock 노드 추가
        G.add_node(
            stock_code,
            label=f"{stock_name}\n{weight:.1f}%",
            color=COLORS["stock_primary"],
            size=node_size,
            title=f"종목: {stock_name}\n코드: {stock_code}\n비중: {weight:.2f}%",
            font={"size": 11, "color": "#1e293b"},
            borderWidth=2,
            shadow=True
        )

        # HOLDS 엣지 추가
        edge_width = 1 + (weight / max_weight) * 4
        G.add_edge(
            etf_code, stock_code,
            width=edge_width,
            color={"color": COLORS["edge_color"], "highlight": COLORS["highlight"]},
            title=f"비중: {weight:.2f}%"
        )

    return G


def create_stock_graph(cur, stock_code, limit=20):
    """종목 중심 그래프 생성 (역추적)"""
    G = nx.Graph()

    # 보유 ETF 조회
    df = get_stock_etfs(cur, stock_code)

    if df.empty:
        G.add_node(
            stock_code,
            label=stock_code,
            color=COLORS["stock_primary"],
            size=40,
            title=f"종목: {stock_code}",
            font={"size": 14, "color": "#1e293b", "bold": True},
            borderWidth=3,
            shadow=True
        )
        return G

    # 종목명 가져오기 (첫 번째 결과에서)
    stock_name = stock_code

    # Stock 노드 추가
    G.add_node(
        stock_code,
        label=f"{stock_name}\n({stock_code})",
        color=COLORS["stock_primary"],
        size=40,
        title=f"종목: {stock_name} ({stock_code})",
        font={"size": 14, "color": "#1e293b", "bold": True},
        borderWidth=3,
        borderWidthSelected=5,
        shadow=True
    )

    # 상위 N개 ETF만 표시
    df = df.head(limit)
    max_weight = df["비중(%)"].max() if not df.empty else 1
    # max_weight가 0이거나 NaN인 경우 1로 설정
    if pd.isna(max_weight) or max_weight == 0:
        max_weight = 1

    for _, row in df.iterrows():
        etf_code = row["ETF코드"]
        etf_name = row["ETF명"]
        weight = row["비중(%)"]

        # weight가 NaN인 경우 0으로 처리
        if pd.isna(weight):
            weight = 0

        # 크기 계산 (비중에 비례)
        node_size = 15 + (weight / max_weight) * 25

        # ETF 노드 추가
        display_name = etf_name[:12] + "..." if len(etf_name) > 12 else etf_name
        G.add_node(
            etf_code,
            label=f"{display_name}\n{weight:.1f}%",
            color=COLORS["etf_primary"],
            size=node_size,
            title=f"ETF: {etf_name}\n코드: {etf_code}\n비중: {weight:.2f}%",
            font={"size": 11, "color": "#1e293b"},
            borderWidth=2,
            shadow=True
        )

        # HOLDS 엣지 추가
        edge_width = 1 + (weight / max_weight) * 4
        G.add_edge(
            etf_code, stock_code,
            width=edge_width,
            color={"color": COLORS["edge_color"], "highlight": COLORS["highlight"]},
            title=f"비중: {weight:.2f}%"
        )

    return G


def render_graph(G, height="600px"):
    """NetworkX 그래프를 PyVis로 렌더링"""
    if len(G.nodes()) == 0:
        st.warning("표시할 데이터가 없습니다.")
        return

    net = Network(
        height=height,
        width="100%",
        bgcolor="#ffffff",
        font_color="#1e293b",
        select_menu=False,
        filter_menu=False
    )
    net.from_nx(G)

    # 개선된 물리 엔진 설정
    net.set_options("""
    {
        "nodes": {
            "shape": "dot",
            "scaling": {
                "min": 10,
                "max": 50
            },
            "font": {
                "size": 12,
                "face": "Pretendard, -apple-system, BlinkMacSystemFont, sans-serif"
            }
        },
        "edges": {
            "color": {
                "inherit": false
            },
            "smooth": {
                "enabled": true,
                "type": "continuous",
                "roundness": 0.5
            }
        },
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.015,
                "springLength": 150,
                "springConstant": 0.05,
                "damping": 0.4
            },
            "maxVelocity": 50,
            "solver": "forceAtlas2Based",
            "timestep": 0.35,
            "stabilization": {
                "enabled": true,
                "iterations": 200,
                "updateInterval": 25
            }
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "hideEdgesOnDrag": true,
            "navigationButtons": true,
            "keyboard": {
                "enabled": true
            }
        }
    }
    """)

    # 임시 파일에 저장 후 표시
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as f:
        net.save_graph(f.name)
        with open(f.name, "r", encoding="utf-8") as html_file:
            html_content = html_file.read()
        os.unlink(f.name)

    # HTML에 스타일 추가
    custom_style = """
    <style>
        body { margin: 0; padding: 0; }
        #mynetwork {
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
    </style>
    """
    html_content = html_content.replace("</head>", f"{custom_style}</head>")

    st.components.v1.html(html_content, height=int(height.replace("px", "")) + 50)


def style_dataframe(df, highlight_col=None):
    """데이터프레임 스타일링"""
    if df.empty:
        return df

    def highlight_weight(val):
        """비중에 따른 배경색"""
        if isinstance(val, (int, float)):
            if val >= 10:
                return 'background-color: #dcfce7; color: #166534; font-weight: 600'
            elif val >= 5:
                return 'background-color: #fef9c3; color: #854d0e'
            elif val >= 1:
                return 'background-color: #fef3c7; color: #92400e'
        return ''

    styled = df.style

    # 비중 컬럼에 스타일 적용
    weight_cols = [col for col in df.columns if '비중' in col]
    if weight_cols:
        styled = styled.applymap(highlight_weight, subset=weight_cols)

    # 숫자 포맷팅
    format_dict = {}
    for col in df.columns:
        if '비중' in col:
            format_dict[col] = '{:.2f}'
        elif '수량' in col:
            format_dict[col] = '{:,.0f}'

    if format_dict:
        styled = styled.format(format_dict)

    return styled


def main():
    # 헤더
    st.markdown("""
        <h1 style="text-align: center; margin-bottom: 0;">
            📊 ETF Atlas Graph Viewer
        </h1>
        <p style="text-align: center; color: #64748b; margin-top: 0.5rem; margin-bottom: 2rem;">
            Apache AGE 기반 ETF-Stock 관계 그래프 시각화 도구
        </p>
    """, unsafe_allow_html=True)

    # DB 연결
    try:
        conn = get_connection()
        cur = init_age(conn)
    except Exception as e:
        st.error(f"❌ DB 연결 실패: {e}")
        st.info("💡 DB 설정을 확인하세요. 환경변수: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
        return

    # 사이드바: 통계
    with st.sidebar:
        st.markdown("## 📈 그래프 통계")

        # 통계 로딩
        with st.spinner("통계 조회 중..."):
            etf_count = get_etf_count(cur)
            stock_count = get_stock_count(cur)
            holds_count = get_holds_count(cur)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("ETF", f"{etf_count:,}")
        with col2:
            st.metric("종목", f"{stock_count:,}")

        st.metric("보유관계", f"{holds_count:,}")

        st.markdown("---")
        st.markdown("## ⚙️ 표시 설정")
        node_limit = st.slider(
            "표시할 노드 수",
            min_value=5,
            max_value=50,
            value=20,
            help="그래프에 표시할 최대 노드 수를 설정합니다."
        )

        st.markdown("---")
        st.markdown("## 🎨 범례")
        st.markdown(f"""
        <div style="display: flex; align-items: center; margin-bottom: 0.5rem;">
            <span style="display: inline-block; width: 16px; height: 16px;
                         background-color: {COLORS['etf_primary']};
                         border-radius: 50%; margin-right: 8px;"></span>
            <span style="color: #475569;">ETF</span>
        </div>
        <div style="display: flex; align-items: center;">
            <span style="display: inline-block; width: 16px; height: 16px;
                         background-color: {COLORS['stock_primary']};
                         border-radius: 50%; margin-right: 8px;"></span>
            <span style="color: #475569;">종목</span>
        </div>
        """, unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2, tab3 = st.tabs(["🔍 ETF 탐색", "🔄 종목 역추적", "📋 데이터 조회"])

    with tab1:
        st.markdown("### ETF 구성종목 그래프")
        st.caption("ETF를 선택하면 해당 ETF의 구성종목을 그래프로 시각화합니다.")

        # ETF 목록 조회
        with st.spinner("ETF 목록 조회 중..."):
            etf_df = get_etf_list(cur, limit=1000)

        if etf_df.empty:
            st.warning("⚠️ ETF 데이터가 없습니다.")
        else:
            # ETF 선택
            col1, col2 = st.columns([3, 1])
            with col1:
                etf_options = [f"{row['code']} - {row['name']}" for _, row in etf_df.iterrows()]
                selected_etf = st.selectbox(
                    "ETF 선택",
                    etf_options,
                    label_visibility="collapsed",
                    placeholder="ETF를 선택하세요..."
                )

            if selected_etf:
                etf_code = selected_etf.split(" - ")[0]
                etf_name = selected_etf.split(" - ")[1] if " - " in selected_etf else ""

                # 그래프 생성 및 표시
                with st.spinner("그래프 생성 중..."):
                    G = create_etf_graph(cur, etf_code, etf_name, limit=node_limit)
                    render_graph(G, height="550px")

                # 구성종목 테이블
                st.markdown("### 📋 구성종목 목록")
                holdings_df = get_etf_holdings(cur, etf_code)
                if not holdings_df.empty:
                    styled_df = style_dataframe(holdings_df)
                    st.dataframe(
                        styled_df,
                        use_container_width=True,
                        height=400
                    )

                    # 다운로드 버튼
                    col1, col2, col3 = st.columns([1, 1, 2])
                    with col1:
                        st.download_button(
                            "📥 CSV 다운로드",
                            holdings_df.to_csv(index=False, encoding='utf-8-sig'),
                            f"{etf_code}_holdings.csv",
                            "text/csv"
                        )
                else:
                    st.info("ℹ️ 구성종목 데이터가 없습니다.")

    with tab2:
        st.markdown("### 종목 → ETF 역추적")
        st.caption("특정 종목을 입력하면 해당 종목을 보유한 ETF들을 찾아 그래프로 시각화합니다.")

        col1, col2 = st.columns([3, 1])
        with col1:
            stock_code = st.text_input(
                "종목 코드",
                value="005930",
                placeholder="종목 코드 입력 (예: 005930)",
                label_visibility="collapsed"
            )
        with col2:
            search_clicked = st.button("🔍 검색", use_container_width=True)

        if stock_code:
            # 그래프 생성 및 표시
            with st.spinner("그래프 생성 중..."):
                G = create_stock_graph(cur, stock_code, limit=node_limit)
                render_graph(G, height="550px")

            # ETF 목록 테이블
            st.markdown(f"### 📋 {stock_code}을(를) 보유한 ETF 목록")
            etf_list_df = get_stock_etfs(cur, stock_code)
            if not etf_list_df.empty:
                styled_df = style_dataframe(etf_list_df)
                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    height=400
                )

                # 다운로드 버튼
                col1, col2, col3 = st.columns([1, 1, 2])
                with col1:
                    st.download_button(
                        "📥 CSV 다운로드",
                        etf_list_df.to_csv(index=False, encoding='utf-8-sig'),
                        f"{stock_code}_etfs.csv",
                        "text/csv"
                    )
            else:
                st.info("ℹ️ 해당 종목을 보유한 ETF가 없습니다.")

    with tab3:
        st.markdown("### 데이터 조회")

        query_type = st.radio(
            "조회 유형",
            ["ETF 목록", "종목 목록", "커스텀 Cypher"],
            horizontal=True
        )

        if query_type == "ETF 목록":
            with st.spinner("ETF 목록 조회 중..."):
                df = get_etf_list(cur, limit=500)

            st.markdown(f"**총 {len(df)}개의 ETF**")
            st.dataframe(df, use_container_width=True, height=500)

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                st.download_button(
                    "📥 CSV 다운로드",
                    df.to_csv(index=False, encoding='utf-8-sig'),
                    "etf_list.csv",
                    "text/csv"
                )

        elif query_type == "종목 목록":
            with st.spinner("종목 목록 조회 중..."):
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

            st.markdown(f"**총 {len(df)}개의 종목**")
            st.dataframe(df, use_container_width=True, height=500)

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                st.download_button(
                    "📥 CSV 다운로드",
                    df.to_csv(index=False, encoding='utf-8-sig'),
                    "stock_list.csv",
                    "text/csv"
                )

        else:
            st.warning("⚠️ **주의:** Cypher 쿼리는 읽기 전용으로 사용하세요.")

            custom_query = st.text_area(
                "Cypher 쿼리",
                value="MATCH (e:ETF) RETURN e.code, e.name LIMIT 10",
                height=120,
                help="Cypher 쿼리를 입력하세요. MATCH, RETURN 등의 구문을 사용할 수 있습니다."
            )

            if st.button("▶️ 실행", type="primary"):
                try:
                    with st.spinner("쿼리 실행 중..."):
                        sql = f"""
                            SELECT * FROM cypher('etf_graph', $$
                                {custom_query}
                            $$) as (result agtype);
                        """
                        cur.execute(sql)
                        results = cur.fetchall()

                    st.success(f"✅ {len(results)}개의 결과")
                    st.json([str(r[0]) for r in results])
                except Exception as e:
                    st.error(f"❌ 쿼리 실행 오류: {e}")


if __name__ == "__main__":
    main()
