"""ConnectDI 검색 키워드 인사이트 대시보드 (Sometrend 스타일).

st.container(border=True) 활용해 카드 안에 차트가 정상 들어가도록.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from urllib.parse import quote as _urlquote

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

import data_loader

load_dotenv()

PRIMARY = "#5B43C9"
PRIMARY_DARK = "#4A35B0"
PRIMARY_LIGHT = "#F1EEFB"
SITE_COLORS = {
    "커넥트디아이": "#5B43C9",
    "커넥트디아이플러스": "#10B981",
    "길병원": "#F59E0B",
}

st.set_page_config(
    page_title="ConnectDI Insights",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============== CSS ==============
st.markdown(
    f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

    html, body, *, [class*="css"], button, input, select, textarea {{
        font-family: 'Pretendard', 'Malgun Gothic', '맑은 고딕', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }}

    .stApp {{ background: white; padding-top: 64px; padding-bottom: 0 !important; }}
    [data-testid="stAppViewContainer"] {{ background: white !important; }}
    body, html {{ background: white !important; }}

    /* Streamlit 기본 4방향 패딩 제거 */
    [data-testid="stMainBlockContainer"] {{
        padding-top: 0 !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        padding-bottom: 0 !important;
    }}
    section.main > div:first-child {{ padding-bottom: 0 !important; }}
    section.main {{ padding-bottom: 0 !important; }}

    /* Streamlit footer 숨김 */
    footer {{ display: none !important; }}
    [data-testid="stFooter"] {{ display: none !important; }}

    /* Streamlit 기본 헤더 숨김 */
    header[data-testid="stHeader"] {{ display: none !important; }}

    /* 메인 영역 전체 너비 사용 */
    .main .block-container {{
        padding: 0 !important;
        max-width: 100% !important;
    }}
    section.main {{ padding: 0 !important; }}

    /* 사이드바도 헤더 아래로 */
    section[data-testid="stSidebar"] {{ top: 64px !important; }}

    /* 사이드바 collapse 후 다시 여는 버튼 — 헤더 아래에 항상 보이게 (모든 testid 변형 매치) */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="baseButton-headerNoPadding"],
    button[data-testid="stBaseButton-headerNoPadding"],
    button[kind="headerNoPadding"],
    div[data-testid="stSidebarHeader"] ~ button,
    .stApp > button[kind="header"] {{
        position: fixed !important;
        top: 72px !important;
        left: 12px !important;
        z-index: 9999 !important;
        background: white !important;
        border: 1px solid #EDECF1 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 6px rgba(91, 67, 201, 0.12) !important;
        padding: 6px !important;
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }}
    [data-testid="stSidebarCollapsedControl"] svg,
    [data-testid="collapsedControl"] svg,
    [data-testid="stSidebarCollapseButton"] svg {{
        color: {PRIMARY} !important; fill: {PRIMARY} !important;
    }}

    /* 상단 진보라 헤더 — 전체 너비 fixed */
    .top-header {{
        background: linear-gradient(90deg, {PRIMARY} 0%, {PRIMARY_DARK} 100%);
        padding: 0 32px;
        display: flex; align-items: center; gap: 20px;
        color: white;
        position: fixed;
        top: 0; left: 0;
        width: 100vw;
        height: 64px;
        z-index: 999;
        box-shadow: 0 1px 4px rgba(91, 67, 201, 0.15);
    }}
    .top-logo {{
        color: white; font-size: 1.2rem; font-weight: 800;
        display: flex; align-items: center; gap: 8px;
    }}
    .top-tag {{
        background: rgba(255,255,255,0.2); color: white;
        padding: 4px 10px; border-radius: 4px;
        font-size: 0.7rem; font-weight: 500;
    }}

    /* 페이지 패딩 (4방향 모두 제거 — 카드들이 화면 끝까지 닿음) */
    .page-pad {{ padding: 0 !important; margin: 0 !important; }}

    /* stColumn 자체만 transparent (자식 위젯들은 보호) */
    div[data-testid="stColumn"] {{
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
    }}
    /* stColumn 자체도 명시 (emotion CSS 덮기) */
    div[data-testid="stColumn"], .stColumn {{
        background: none !important;
        background-color: transparent !important;
        box-shadow: none !important;
        border: 0 !important;
        border-radius: 0 !important;
    }}
    /* 화이트리스트 — 의도된 박스 시각은 유지 */
    .page-pad div[data-testid="stVerticalBlockBorderWrapper"],
    .page-pad .kpi-box,
    .page-pad .kw-rank-card,
    .page-pad .empty-state {{
        background: white !important;
        background-color: white !important;
    }}
    .page-pad div[data-testid="stVerticalBlockBorderWrapper"] {{
        box-shadow: 0 2px 8px rgba(91, 67, 201, 0.06) !important;
        border: 0 !important;
    }}
    .page-pad div[role="radiogroup"] > label {{
        background: white !important;
    }}
    .page-pad div[role="radiogroup"] > label:has(input:checked) {{
        background: {PRIMARY_LIGHT} !important;
    }}
    /* 단, st.container(border=True) 명시적 카드는 흰색 시각 유지 */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: white !important;
        border: 1px solid #EDECF1 !important;
        box-shadow: 0 2px 8px rgba(91, 67, 201, 0.06) !important;
    }}
    /* date/text input — 박스 완전 제거, underline만 */
    [data-testid="stDateInput"] input,
    [data-testid="stTextInput"] input {{
        background: transparent !important;
        border: 0 !important;
        border-bottom: 1px solid #EDECF1 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }}
    /* input wrapper(baseweb)도 박스 시각 제거 */
    [data-baseweb="input"], [data-baseweb="select"], [data-baseweb="base-input"] {{
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
    }}
    /* baseweb 컴포넌트 wrapper도 transparent */
    [data-baseweb="input"],
    [data-baseweb="select"],
    [data-baseweb="base-input"] {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }}

    /* 메인 영역 전체에 흰색 배경 (사이드바 옆 모든 영역) — 카드 뒤에 위치 */
    section[data-testid="stMain"] {{
        background: white !important;
        position: relative;
    }}
    section[data-testid="stMain"]::before {{
        content: "";
        position: absolute;
        inset: 0;
        background: white;
        z-index: 0;
    }}
    section[data-testid="stMain"] > * {{ position: relative; z-index: 1; }}

    /* 페이지 안 첫·마지막 요소 마진 제거 */
    .page-pad > div:first-child,
    .page-pad [data-testid="stVerticalBlock"] > div:first-child {{ margin-top: 0 !important; padding-top: 0 !important; }}
    .page-pad > div:last-child,
    .page-pad [data-testid="stVerticalBlock"] > div:last-child {{ margin-bottom: 0 !important; padding-bottom: 0 !important; }}

    /* st.write("") 빈 줄 높이 제거 */
    [data-testid="stMarkdownContainer"]:has(> p:empty),
    [data-testid="stMarkdown"]:has(> div > p:empty) {{ height: 0 !important; margin: 0 !important; padding: 0 !important; }}

    /* 페이지 내 columns gap 줄임 */
    [data-testid="stHorizontalBlock"] {{ gap: 8px !important; }}

    /* 카드(stVerticalBlockBorderWrapper) 간 간격 최소화 */
    div[data-testid="stVerticalBlockBorderWrapper"] + div[data-testid="stVerticalBlockBorderWrapper"] {{
        margin-top: 8px !important;
    }}

    /* 사이드바 */
    section[data-testid="stSidebar"] {{ background: white !important; border-right: 1px solid #EDECF1; }}

    /* st.container(border=True) 카드 — 박스 시각 완전 제거 (배경 시각도 X) */
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        padding: 0 !important;
        margin-bottom: 16px !important;
        box-shadow: none !important;
    }}

    /* KPI 박스 */
    .kpi-box {{
        background: white; padding: 18px 22px;
        border-radius: 10px; height: 100%;
    }}
    .kpi-label {{ font-size: 0.78rem; color: #8B8A95; font-weight: 500; }}
    .kpi-value {{ font-size: 1.7rem; font-weight: 800; color: {PRIMARY}; margin-top: 6px; line-height: 1; }}
    .kpi-sub {{ font-size: 0.72rem; color: #B0AFB8; margin-top: 4px; }}

    /* 키워드 랭킹 카드 */
    .kw-rank-card {{
        background: #FAFAFC; padding: 9px 14px; margin-bottom: 5px;
        border-radius: 6px;
        display: flex; align-items: center; gap: 12px;
    }}
    .kw-rank-num {{
        background: {PRIMARY_LIGHT}; color: {PRIMARY}; font-weight: 800;
        font-size: 0.75rem; padding: 4px 8px; border-radius: 4px;
        min-width: 34px; text-align: center;
    }}
    .kw-rank-name {{ flex: 1; font-size: 0.9rem; color: #1E1B2E; }}
    .kw-rank-count {{ font-size: 0.85rem; color: {PRIMARY}; font-weight: 700; }}

    /* TOP 키워드 클릭 anchor — 기본 시각 제거 + hover 효과 */
    .kw-rank-link {{ text-decoration: none !important; color: inherit !important; display: block; }}
    .kw-rank-link:hover .kw-rank-card {{ background: {PRIMARY_LIGHT} !important; }}
    .kw-rank-link:hover .kw-rank-name {{ color: {PRIMARY} !important; font-weight: 600; }}

    /* 위젯 제목 */
    .w-title {{
        font-size: 0.95rem; font-weight: 700; color: #1E1B2E;
        margin-bottom: 12px;
    }}

    /* 빠른 기간 라디오 — 회색 알약 컨테이너 + 선택된 옵션만 흰색 박스 */
    div[role="radiogroup"] {{
        background: #F0F0F4 !important;
        border-radius: 999px !important;
        padding: 4px !important;
        gap: 0 !important;
        display: inline-flex !important;
        width: fit-content !important;
    }}
    div[role="radiogroup"] > label {{
        background: transparent !important; border: 0 !important;
        padding: 6px 16px !important; border-radius: 999px !important;
        font-size: 0.85rem !important; color: #8B8A95 !important;
        box-shadow: none !important;
        transition: all 0.15s;
    }}
    div[role="radiogroup"] > label:has(input:checked) {{
        background: white !important;
        color: {PRIMARY} !important; font-weight: 700 !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
    }}
    div[role="radiogroup"] > label > div:first-child {{ display: none !important; }}

    /* 사이드바 라디오 메뉴 — 알약 컨테이너/선택 배경 모두 제거 */
    section[data-testid="stSidebar"] div[role="radiogroup"] {{
        flex-direction: column !important; gap: 4px !important;
        background: transparent !important;
        padding: 0 !important;
        border-radius: 0 !important;
        display: flex !important;
        width: 100% !important;
    }}
    section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
        background: transparent !important; border: none !important;
        padding: 10px 14px !important; border-radius: 0 !important;
        color: #6B6A73 !important; font-size: 0.92rem !important;
        width: 100%;
        box-shadow: none !important;
    }}
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
        background: transparent !important;
        color: {PRIMARY} !important;
        font-weight: 700 !important;
        box-shadow: none !important;
    }}

    /* 빈 상태 */
    .empty-state {{
        background: white; padding: 60px 30px;
        border-radius: 10px; text-align: center;
    }}
    .empty-state h3 {{ color: #1E1B2E; font-weight: 700; margin: 12px 0 8px 0; }}
    .empty-state p {{ color: #8B8A95; }}
    .reco-row {{ margin-top: 24px; display: flex; gap: 18px; justify-content: center; flex-wrap: wrap; }}
    .reco-kw {{ color: {PRIMARY}; font-weight: 600; padding: 4px 10px; border-bottom: 1px solid {PRIMARY}; }}

    /* 체크박스 라벨 한 줄 */
    div[data-testid="stCheckbox"] label {{
        white-space: nowrap !important; font-size: 0.85rem !important;
    }}

    /* 토글 스위치 (Sometrend 스타일) */
    div[data-testid="stToggle"] label {{
        font-size: 0.82rem !important;
        white-space: nowrap !important;
        color: #1E1B2E !important;
        font-weight: 500 !important;
    }}
    /* 토글 라벨 위치 (스위치 왼쪽) */
    div[data-testid="stToggle"] {{ display: flex; align-items: center; }}

    /* 적용 버튼 (primary 보라 강조) */
    button[kind="primary"],
    button[data-testid="baseButton-primary"] {{
        background: {PRIMARY} !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        padding: 10px 20px !important;
        white-space: nowrap !important;
        min-width: 80px !important;
        box-shadow: 0 2px 6px rgba(91, 67, 201, 0.25);
        transition: background 0.15s;
    }}
    button[kind="primary"]:hover,
    button[data-testid="baseButton-primary"]:hover {{
        background: {PRIMARY_DARK} !important;
        box-shadow: 0 4px 10px rgba(91, 67, 201, 0.35);
    }}

    /* 메인 영역 너비를 사이드바 옆 전체 폭으로 강제 */
    [data-testid="stAppViewContainer"] > section[data-testid="stMain"],
    section.main,
    .main {{
        max-width: 100% !important;
        width: 100% !important;
    }}
    [data-testid="stMainBlockContainer"] {{
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 24px !important;
        padding-right: 24px !important;
        padding-top: 32px !important;
        margin: 0 !important;
    }}
    [data-testid="stAppViewContainer"] {{ max-width: 100vw !important; overflow-x: hidden; }}

    /* 빠른 기간 라디오 버튼 — Sometrend 스타일 정밀 조정 */
    div[role="radiogroup"] > label {{
        min-width: 60px !important;
        text-align: center;
    }}

    /* 날짜 입력 박스 (Sometrend처럼 큰 폰트 + 라벨 위) */
    div[data-testid="stDateInput"] label {{
        font-size: 0.78rem !important;
        color: #6B6A73 !important;
        font-weight: 500 !important;
    }}
    div[data-testid="stDateInput"] input {{
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: #1E1B2E !important;
        border: 1px solid #EDECF1 !important;
        border-radius: 6px !important;
    }}

    /* 시작일·종료일 사이 ~ 구분자 (날짜 input 박스와 수직 가운데 정렬) */
    .dash-sep {{
        text-align: center;
        color: #8B8A95;
        font-size: 1.3rem;
        font-weight: 500;
        line-height: 40px;
        margin-top: 28px;
    }}

    /* 빠른 기간 라디오 버튼 크기 조정 — 7개 옵션 한 줄에 */
    div[role="radiogroup"] > label {{
        min-width: 50px !important;
        padding: 7px 10px !important;
        font-size: 0.82rem !important;
    }}

    /* 메트릭 색상 */
    div[data-testid="stMetricValue"] {{ color: {PRIMARY} !important; font-weight: 800 !important; }}
    div[data-testid="stMetricLabel"] {{ color: #6B6A73 !important; }}

    /* 헤더 */
    h1, h2, h3, h4, h5, h6 {{ color: #1E1B2E; }}
    </style>
    """,
    unsafe_allow_html=True,
)


import re as _re

EN_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'is', 'are', 'was', 'were',
    'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'should', 'could', 'can', 'may', 'might', 'must',
    'shall', 'to', 'of', 'in', 'on', 'at', 'for', 'with', 'by', 'from',
    'as', 'about', 'against', 'between', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'up', 'down', 'out', 'over', 'under',
    'this', 'that', 'these', 'those', 'i', 'me', 'my', 'we', 'us', 'our',
    'you', 'your', 'yours', 'he', 'him', 'his', 'she', 'her', 'hers',
    'it', 'its', 'they', 'them', 'their', 'theirs',
    'what', 'which', 'who', 'whom', 'where', 'when', 'why', 'how',
    'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
    'so', 'than', 'too', 'very', 'just', 'now', 'here', 'there',
    'then', 'once', 'also', 'because', 'while', 'until',
    'list', 'detail', 'page', 'home', 'main', 'search', 'view', 'item',
    'show', 'index', 'menu', 'login', 'logout',
}

KR_STOPWORDS = {
    '의', '가', '이', '은', '는', '을', '를', '에', '와', '과', '도', '만', '에서', '에게', '한테',
    '그', '저', '그것', '이것', '저것', '나', '너', '우리', '여기', '거기',
    '무엇', '어떤', '무슨', '어느', '어디', '언제', '왜', '어떻게',
    '정말', '너무', '매우', '아주', '많이', '조금', '거의', '대충', '좀', '잘', '안', '못',
    '더', '덜', '또', '또한', '항상', '늘',
    '그리고', '그러나', '하지만', '그래서', '따라서', '그러므로', '그래도', '그러면',
    '있다', '없다', '한다', '된다', '했다', '됐다', '있어', '없어',
    '하다', '되다', '이다', '아니다',
}


def _is_valid_keyword(kw: str) -> bool:
    s = str(kw).strip()
    if not s or len(s) <= 1:
        return False
    if not _re.search(r'[가-힣A-Za-z0-9]', s):
        return False
    if s in KR_STOPWORDS or s.lower() in EN_STOPWORDS:
        return False
    return True


@st.cache_data(ttl=3600, show_spinner="Drive에서 검색 로그 로드 중...")
def load_data() -> pd.DataFrame:
    df = data_loader.load_all()
    df['date'] = pd.to_datetime(df['date'])
    # 정제 — 통합 CSV는 이미 적용되어 있지만, fallback 경로(3개 raw 통합)일 때 대비
    mask = df['keyword'].apply(_is_valid_keyword)
    df = df[mask].reset_index(drop=True)
    return df


def render_top_header():
    nav = f"window.parent.location.search='?page=home{_link_auth_suffix()}'"
    st.markdown(
        f'<div class="top-header">'
        f'<div class="top-logo" onclick="{nav}" style="cursor:pointer;">🔍 ConnectDI</div>'
        f'<div class="top-tag" onclick="{nav}" style="cursor:pointer;">검색 키워드 인사이트</div>'
        f'<div style="flex:1;"></div>'
        f'<div style="color:rgba(255,255,255,0.85);font-size:0.85rem;">통합 대시보드</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_filter_bar(df: pd.DataFrame):
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()

    st.markdown('<div class="filter-bar">', unsafe_allow_html=True)

    # ROW 1: 날짜 + 빠른 기간 + 적용
    c1 = st.columns([1.6, 0.3, 1.6, 0.3, 6.5, 0.7])

    with c1[0]:
        start_dt = st.date_input(
            "📅 시작일", value=max_date - timedelta(days=30),
            min_value=min_date, max_value=max_date,
            label_visibility="visible",
        )
    with c1[1]:
        st.markdown(
            '<div class="dash-sep">~</div>',
            unsafe_allow_html=True,
        )
    with c1[2]:
        end_dt = st.date_input(
            "📅 종료일", value=max_date,
            min_value=min_date, max_value=max_date,
            label_visibility="visible",
        )
    with c1[3]:
        st.write("")
    with c1[4]:
        st.markdown('<div style="margin-top:26px;"></div>', unsafe_allow_html=True)
        quick = st.radio(
            "빠른 기간",
            options=["1일", "1주일", "1개월", "3개월", "6개월", "12개월", "전체"],
            index=2, horizontal=True, label_visibility="collapsed",
            key="quick_period",
        )
    with c1[5]:
        st.markdown('<div style="margin-top:30px;"></div>', unsafe_allow_html=True)
        apply_btn = st.button(
            "적용", use_container_width=True,
            key="apply_channel", type="primary",
        )

    # ROW 2: 사이트 토글 + 키워드 검색
    c2 = st.columns([1.5, 1.5, 1.5, 5.5])
    with c2[0]:
        site_di = st.toggle("커넥트디아이", value=True, key="site_di")
    with c2[1]:
        site_plus = st.toggle("커넥트디아이플러스", value=True, key="site_plus")
    with c2[2]:
        site_gil = st.toggle("길병원", value=True, key="site_gil")
    with c2[3]:
        keyword_filter = st.text_input(
            "키워드 검색",
            placeholder="🔎 키워드 입력 (부분 일치, 비워두면 전체)",
            label_visibility="collapsed", key="kw_filter",
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # 적용 버튼을 눌렀을 때만 새 필터 저장
    if apply_btn:
        if quick == "전체":
            start_date, end_date = min_date, max_date
        else:
            days_map = {"1일": 1, "1주일": 7, "1개월": 30, "3개월": 90, "6개월": 180, "12개월": 365}
            end_date = max_date
            start_date = max(min_date, end_date - timedelta(days=days_map[quick]))
        # 날짜 입력이 변경됐으면 그걸 우선
        if start_dt != max_date - timedelta(days=30) or end_dt != max_date:
            start_date, end_date = start_dt, end_dt

        sites = []
        if site_di: sites.append("커넥트디아이")
        if site_plus: sites.append("커넥트디아이플러스")
        if site_gil: sites.append("길병원")
        if not sites:
            sites = ["커넥트디아이", "커넥트디아이플러스", "길병원"]

        st.session_state['applied_filter'] = {
            'start_date': start_date, 'end_date': end_date,
            'sites': sites, 'keyword': keyword_filter,
        }

    # 적용된 필터 (없으면 기본값 = 최근 1개월·전체 사이트)
    if 'applied_filter' not in st.session_state:
        days_map = {"1일": 1, "1주일": 7, "1개월": 30, "3개월": 90, "6개월": 180, "12개월": 365}
        st.session_state['applied_filter'] = {
            'start_date': max(min_date, max_date - timedelta(days=30)),
            'end_date': max_date,
            'sites': ["커넥트디아이", "커넥트디아이플러스", "길병원"],
            'keyword': "",
        }

    f = st.session_state['applied_filter']
    return f['start_date'], f['end_date'], f['sites'], f['keyword']


def filter_df(df, start_date, end_date, sites, keyword):
    mask = (df['site'].isin(sites)
            & (df['date'].dt.date >= start_date)
            & (df['date'].dt.date <= end_date))
    if keyword:
        mask &= df['keyword'].str.contains(keyword, case=False, na=False)
    return df[mask].copy()


def render_kpi_row(fdf, start_date, end_date):
    cols = st.columns(4)
    items = [
        ("총 검색량", f"{int(fdf['hits'].sum()):,}", "hits 합계"),
        ("Unique 키워드", f"{fdf['keyword'].nunique():,}", "표기 기준"),
        ("분석 사이트", f"{fdf['site'].nunique()}개", "선택됨"),
        ("분석 기간", f"{(end_date - start_date).days + 1}일", f"{start_date} ~ {end_date}"),
    ]
    for col, (label, value, sub) in zip(cols, items):
        col.markdown(
            f'<div class="kpi-box">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'<div class="kpi-sub">{sub}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def render_empty():
    st.markdown(
        f'<div class="empty-state">'
        f'<div style="font-size:3.5rem;">📊</div>'
        f'<h3>분석할 데이터가 없습니다</h3>'
        f'<p>채널·기간을 선택하고 키워드를 입력해 시작해 보세요.</p>'
        f'<div class="reco-row">'
        f'<span class="reco-kw">프로피베린</span>'
        f'<span class="reco-kw">세비카</span>'
        f'<span class="reco-kw">아세트아미노펜</span>'
        f'<span class="reco-kw">위고비</span>'
        f'<span class="reco-kw">Tirzepatide</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def plotly_layout(fig, height=300):
    """공통 plotly 레이아웃 설정 (Sometrend 스타일)."""
    fig.update_layout(
        height=height, hovermode='x unified',
        legend=dict(
            orientation='h', yanchor='top', y=-0.15,
            x=0.5, xanchor='center',
            bgcolor='rgba(0,0,0,0)',
            font=dict(size=12, family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif", color='#1E1B2E'),
            itemsizing='constant',
        ),
        plot_bgcolor='white', paper_bgcolor='white',
        margin=dict(l=10, r=10, t=20, b=60),
        font=dict(family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif", size=12, color='#1E1B2E'),
        hoverlabel=dict(
            bgcolor='white', font=dict(family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif", size=12),
            bordercolor='#E5E5E8',
        ),
    )
    fig.update_xaxes(
        showgrid=False, showline=False, zeroline=False,
        ticks='outside', ticklen=4, tickcolor='#E5E5E8',
        tickfont=dict(color='#8B8A95', size=11, family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif"),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor='#F3F4F6', showline=False, zeroline=False,
        ticks='', tickfont=dict(color='#8B8A95', size=11, family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif"),
        separatethousands=True,
    )
    return fig


def style_line(fig, n_points: int = 0):
    """라인 차트에 Sometrend 스타일 적용 — spline + 도넛 마커.

    n_points가 많으면 마커·spline 비활성화 (성능 보호).
    scattergl trace는 smoothing/spline 미지원이라 linear로 fallback.
    """
    use_marker = n_points <= 100
    use_spline_global = n_points <= 300
    for trace in fig.data:
        trace_type = (getattr(trace, 'type', '') or '')
        is_gl = 'gl' in trace_type
        use_spline = use_spline_global and not is_gl

        line_color = trace.line.color if trace.line.color else '#5B43C9'
        line_kwargs = {'width': 2.8, 'shape': 'spline' if use_spline else 'linear', 'color': line_color}
        if use_spline:
            line_kwargs['smoothing'] = 0.8
        trace_kwargs = {'mode': 'lines+markers' if use_marker else 'lines', 'line': line_kwargs}
        if use_marker:
            trace_kwargs['marker'] = dict(
                size=7, color='white', line=dict(width=2, color=line_color),
            )
        trace.update(**trace_kwargs)
    return fig


# ============== 페이지 0: 홈 화면 ==============
def _link_auth_suffix() -> str:
    """anchor href에 추가할 auth 토큰 query 부분. 인증 안 됐으면 빈 문자열."""
    token = _auth_token()
    return f"&auth={token}" if token else ""


def page_home(df):
    """ConnectDI 홈 화면 — 전체 검색 트렌드 개요."""
    start_date, end_date, sites, kw = render_filter_bar(df)
    fdf = filter_df(df, start_date, end_date, sites, kw)

    if fdf.empty:
        render_empty()
        return

    render_kpi_row(fdf, start_date, end_date)
    st.write("")

    # 일별 추이 (전체 너비)
    with st.container(border=True):
        st.markdown('<div class="w-title">📈 일별 검색량 추이</div>', unsafe_allow_html=True)
        daily = fdf.groupby(['date', 'site'])['hits'].sum().reset_index()
        fig = px.line(daily, x='date', y='hits', color='site',
                     color_discrete_map=SITE_COLORS,
                     labels={'date': '', 'hits': '검색 수', 'site': ''})
        style_line(fig)
        st.plotly_chart(plotly_layout(fig, 380), use_container_width=True,
                      config={'displayModeBar': False})

    # TOP 키워드
    top_n = 20
    pivot = fdf.pivot_table(index='keyword', columns='site', values='hits',
                            aggfunc='sum', fill_value=0)
    pivot['total'] = pivot.sum(axis=1)
    pivot = pivot.sort_values('total', ascending=False).head(top_n)

    with st.container(border=True):
        st.markdown(f'<div class="w-title">🏆 TOP {top_n} 키워드</div>', unsafe_allow_html=True)
        rank_cols = st.columns(2)
        items_top = list(pivot.index)
        mid = (len(items_top) + 1) // 2
        for col_idx, (start, end) in enumerate([(0, mid), (mid, len(items_top))]):
            with rank_cols[col_idx]:
                for i in range(start, end):
                    kw_name = items_top[i]
                    total = int(pivot.loc[kw_name, 'total'])
                    kw_url = _urlquote(str(kw_name))
                    st.markdown(
                        f'<a href="?page=mention&kw={kw_url}{_link_auth_suffix()}" target="_self" class="kw-rank-link">'
                        f'<div class="kw-rank-card">'
                        f'<span class="kw-rank-num">#{i + 1}</span>'
                        f'<span class="kw-rank-name">{kw_name}</span>'
                        f'<span class="kw-rank-count">{total:,}회</span>'
                        f'</div>'
                        f'</a>',
                        unsafe_allow_html=True,
                    )


# ============== 페이지 1: 언급량 분석 (키워드 중심) ==============
def page_mention(df):
    """언급량 분석 — 키워드 검색창 메인. 입력된 키워드 상세 분석."""
    # 메인 검색창 (중앙)
    st.markdown(
        '<div style="background:white;padding:32px 24px;border-radius:10px;margin-bottom:8px;">'
        '<div style="text-align:center;font-size:1.4rem;font-weight:700;color:#1E1B2E;margin-bottom:8px;">'
        '🔍 키워드 언급량 분석'
        '</div>'
        '<div style="text-align:center;color:#8B8A95;font-size:0.95rem;margin-bottom:24px;">'
        '분석하고 싶은 키워드를 입력하면 일별 추이·사이트별 분포·관련 표기 변형을 보여드립니다.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # 키워드 검색창 (큰 사이즈)
    search_col = st.columns([1, 4, 1])
    with search_col[1]:
        kw_input = st.text_input(
            "키워드 입력",
            placeholder="🔎 분석할 키워드를 입력하세요 (예: 프로피베린, 세비카, Tirzepatide)",
            label_visibility="collapsed",
            key="mention_kw",
        )

    if not kw_input:
        # 추천 키워드 표시
        st.markdown(
            '<div style="text-align:center;margin-top:16px;color:#8B8A95;font-size:0.9rem;">'
            '추천 키워드:'
            '</div>',
            unsafe_allow_html=True,
        )
        # TOP 5 키워드를 추천으로 (클릭 시 해당 키워드로 자동 검색)
        top5 = df.groupby('keyword')['hits'].sum().sort_values(ascending=False).head(5)
        st.markdown(
            f'<div style="text-align:center;margin-top:8px;">'
            + ' '.join([
                f'<a href="?page=mention&kw={_urlquote(str(k))}{_link_auth_suffix()}" target="_self" '
                f'style="color:{PRIMARY};font-weight:600;padding:4px 12px;border-bottom:1px solid {PRIMARY};margin:0 6px;text-decoration:none;display:inline-block;">'
                f'{k}</a>'
                for k in top5.index
            ])
            + '</div>',
            unsafe_allow_html=True,
        )
        return

    # 키워드 매칭 데이터
    kw_df = df[df['keyword'].str.contains(kw_input, case=False, na=False)].copy()

    if kw_df.empty:
        st.warning(f"'{kw_input}' 검색 결과 없음. 다른 키워드를 시도해보세요.")
        return

    # 전체 키워드별 검색 순위 (매칭 키워드 중 가장 인기 있는 것의 순위 표시)
    keyword_totals = df.groupby('keyword')['hits'].sum().sort_values(ascending=False)
    keyword_rank = {kw: i + 1 for i, kw in enumerate(keyword_totals.index)}
    matched_kws = kw_df['keyword'].unique()
    best_rank = min((keyword_rank[k] for k in matched_kws if k in keyword_rank), default=None)
    total_keywords = len(keyword_rank)

    # 핵심 지표
    st.write("")
    kpi_cols = st.columns(3)

    # 검색량이 가장 많았던 일자
    daily_hits = kw_df.groupby(kw_df['date'].dt.date)['hits'].sum()
    peak_date = daily_hits.idxmax()
    peak_hits = int(daily_hits.max())

    # 전년 동기간 대비 증감률 (데이터 최근 1년 vs 그 이전 1년)
    data_max = df['date'].max()
    cur_end = data_max
    cur_start = data_max - pd.Timedelta(days=364)
    prev_end = cur_start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=364)
    kw_mask = df['keyword'].str.contains(kw_input, case=False, na=False)
    cur_total_1y = int(df.loc[kw_mask & (df['date'] >= cur_start) & (df['date'] <= cur_end), 'hits'].sum())
    prev_total_1y = int(df.loc[kw_mask & (df['date'] >= prev_start) & (df['date'] <= prev_end), 'hits'].sum())
    if prev_total_1y > 0:
        yoy_pct = (cur_total_1y - prev_total_1y) / prev_total_1y * 100
        arrow = "▲" if yoy_pct >= 0 else "▼"
        yoy_color = "#E84C3D" if yoy_pct >= 0 else "#3498DB"
        yoy_value = f'<span style="color:{yoy_color};">{arrow} {abs(yoy_pct):.2f}%</span>'
        yoy_sub = f"{cur_start.date()} ~ {cur_end.date()} vs {prev_start.date()} ~ {prev_end.date()}"
    else:
        yoy_value = "—"
        yoy_sub = "전년 동기간 데이터 없음"

    if best_rank is not None:
        rank_sub = f"전체 {total_keywords:,}개 중 #{best_rank:,}위"
    else:
        rank_sub = "순위 정보 없음"

    items = [
        ("총 검색량", f"{int(kw_df['hits'].sum()):,}", rank_sub),
        ("검색량이 가장 많았던 일자", f"{peak_date}", f"{peak_hits:,}회"),
        ("전년 동기간 대비 증감률", yoy_value, yoy_sub),
    ]
    for col, (label, value, sub) in zip(kpi_cols, items):
        col.markdown(
            f'<div class="kpi-box"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # ============== 검색 추이 (전체 너비, 일/월/연 토글) ==============
    with st.container(border=True):
        # 헤더 + 토글
        hcol = st.columns([5, 3])
        with hcol[0]:
            st.markdown(
                f'<div class="w-title" style="margin-bottom:0;margin-top:6px;">📈 "{kw_input}" 검색 추이</div>',
                unsafe_allow_html=True,
            )
        with hcol[1]:
            period_unit = st.radio(
                "단위",
                options=["일별", "월별", "연별"],
                index=0, horizontal=True, label_visibility="collapsed",
                key="trend_unit",
            )

        # 단위별 집계
        kw_df_local = kw_df.copy()
        if period_unit == "일별":
            kw_df_local['period'] = kw_df_local['date'].dt.date
        elif period_unit == "월별":
            kw_df_local['period'] = kw_df_local['date'].dt.to_period('M').astype(str)
        else:  # 연별
            kw_df_local['period'] = kw_df_local['date'].dt.year.astype(str)

        trend = kw_df_local.groupby(['period', 'site'])['hits'].sum().reset_index()

        # 일별이면 라인, 월별·연별이면 막대로 보여주는 게 더 보기 좋음
        if period_unit == "일별":
            fig = px.line(trend, x='period', y='hits', color='site',
                         color_discrete_map=SITE_COLORS,
                         labels={'period': '', 'hits': '검색 수', 'site': ''})
            style_line(fig)
        else:
            fig = px.bar(trend, x='period', y='hits', color='site',
                        color_discrete_map=SITE_COLORS, barmode='stack',
                        labels={'period': '', 'hits': '검색 수', 'site': ''})

        st.plotly_chart(plotly_layout(fig, 380), use_container_width=True,
                       config={'displayModeBar': False})

    # ============== 관련 표기 변형 ==============
    with st.container(border=True):
        st.markdown(f'<div class="w-title">📝 "{kw_input}" 관련 표기 변형</div>', unsafe_allow_html=True)
        variants = kw_df.groupby('keyword')['hits'].sum().sort_values(ascending=False)
        # 2열로 배치
        vcols = st.columns(2)
        items = list(variants.items())
        mid = (len(items) + 1) // 2
        for i, (k, v) in enumerate(items[:mid], start=1):
            with vcols[0]:
                st.markdown(
                    f'<div class="kw-rank-card">'
                    f'<span class="kw-rank-num">#{i}</span>'
                    f'<span class="kw-rank-name">{k}</span>'
                    f'<span class="kw-rank-count">{int(v):,}회</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        for i, (k, v) in enumerate(items[mid:], start=mid + 1):
            with vcols[1]:
                st.markdown(
                    f'<div class="kw-rank-card">'
                    f'<span class="kw-rank-num">#{i}</span>'
                    f'<span class="kw-rank-name">{k}</span>'
                    f'<span class="kw-rank-count">{int(v):,}회</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ============== 페이지 2: 비교 분석 ==============
def page_compare(df):
    start_date, end_date, sites, kw = render_filter_bar(df)
    fdf = filter_df(df, start_date, end_date, sites, kw)

    if fdf.empty:
        render_empty()
        return

    render_kpi_row(fdf, start_date, end_date)
    st.write("")

    pivot = fdf.pivot_table(index='keyword', values='hits', aggfunc='sum').sort_values('hits', ascending=False)
    top_keywords = pivot.head(50).index.tolist()

    with st.container(border=True):
        st.markdown('<div class="w-title">🔀 키워드 비교 (최대 5개 선택)</div>', unsafe_allow_html=True)
        compare_kws = st.multiselect(
            "비교할 키워드 (TOP 50)",
            options=top_keywords,
            default=top_keywords[:3],
            max_selections=5,
            label_visibility="collapsed",
        )
        if compare_kws:
            cmp_df = fdf[fdf['keyword'].isin(compare_kws)].groupby(['date', 'keyword'])['hits'].sum().reset_index()
            fig_cmp = px.line(cmp_df, x='date', y='hits', color='keyword',
                             color_discrete_sequence=px.colors.qualitative.Set2)
            style_line(fig_cmp)
            st.plotly_chart(plotly_layout(fig_cmp, 400), use_container_width=True,
                          config={'displayModeBar': False})

    with st.container(border=True):
        st.markdown('<div class="w-title">🏅 사이트별 TOP 5 키워드</div>', unsafe_allow_html=True)
        site_cols = st.columns(len(sites))
        for i, site in enumerate(sites):
            with site_cols[i]:
                color = SITE_COLORS.get(site, PRIMARY)
                st.markdown(f'<div style="font-weight:700;color:{color};margin-bottom:10px;">{site}</div>',
                          unsafe_allow_html=True)
                top5 = fdf[fdf['site'] == site].groupby('keyword')['hits'].sum().sort_values(ascending=False).head(5)
                for j, (k, v) in enumerate(top5.items(), 1):
                    st.markdown(
                        f'<div class="kw-rank-card">'
                        f'<span class="kw-rank-num" style="background:{color}22;color:{color};">#{j}</span>'
                        f'<span class="kw-rank-name">{k}</span>'
                        f'<span class="kw-rank-count" style="color:{color};">{int(v):,}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )


# ============== 페이지 3: 기간 분석 ==============
def page_period(df):
    start_date, end_date, sites, kw = render_filter_bar(df)
    fdf = filter_df(df, start_date, end_date, sites, kw)

    if fdf.empty:
        render_empty()
        return

    render_kpi_row(fdf, start_date, end_date)
    st.write("")

    fdf['year_month'] = fdf['date'].dt.to_period('M').astype(str)
    fdf['week'] = fdf['date'].dt.to_period('W').astype(str)
    fdf['weekday'] = fdf['date'].dt.day_name()

    with st.container(border=True):
        st.markdown('<div class="w-title">📅 월별 검색량 추이</div>', unsafe_allow_html=True)
        monthly = fdf.groupby(['year_month', 'site'])['hits'].sum().reset_index()
        fig_m = px.bar(monthly, x='year_month', y='hits', color='site',
                      color_discrete_map=SITE_COLORS, barmode='group',
                      labels={'year_month': '', 'hits': '검색 수', 'site': ''})
        st.plotly_chart(plotly_layout(fig_m, 320), use_container_width=True,
                      config={'displayModeBar': False})

    r1 = st.columns([7, 3])
    with r1[0]:
        with st.container(border=True):
            st.markdown('<div class="w-title">📊 주별 검색량 추이</div>', unsafe_allow_html=True)
            weekly = fdf.groupby(['week', 'site'])['hits'].sum().reset_index()
            fig_w = px.line(weekly, x='week', y='hits', color='site',
                           color_discrete_map=SITE_COLORS,
                           labels={'week': '', 'hits': '검색 수', 'site': ''})
            style_line(fig_w)
            st.plotly_chart(plotly_layout(fig_w, 320), use_container_width=True,
                           config={'displayModeBar': False})

    with r1[1]:
        with st.container(border=True):
            st.markdown('<div class="w-title">📆 요일별 분포</div>', unsafe_allow_html=True)
            wday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            wday_ko = {'Monday':'월','Tuesday':'화','Wednesday':'수','Thursday':'목','Friday':'금','Saturday':'토','Sunday':'일'}
            wday = fdf.groupby('weekday')['hits'].sum().reindex(wday_order, fill_value=0).reset_index()
            wday['weekday'] = wday['weekday'].map(wday_ko)
            fig_d = px.bar(wday, x='weekday', y='hits',
                          color_discrete_sequence=[PRIMARY],
                          labels={'weekday': '', 'hits': '검색 수'})
            fig_d.update_layout(height=300, showlegend=False,
                              plot_bgcolor='white', paper_bgcolor='white',
                              margin=dict(l=0, r=0, t=10, b=40),
                              font=dict(family="Pretendard, Malgun Gothic, 맑은 고딕, sans-serif", size=11))
            fig_d.update_xaxes(gridcolor='#F3F4F6')
            fig_d.update_yaxes(gridcolor='#F3F4F6')
            st.plotly_chart(fig_d, use_container_width=True, config={'displayModeBar': False})

    with st.container(border=True):
        st.markdown('<div class="w-title">🆕 신규 등장 키워드 (이번 기간 처음 등장, 상위 30)</div>', unsafe_allow_html=True)
        first_appear = df.groupby('keyword')['date'].min().reset_index()
        first_appear.columns = ['keyword', 'first_date']
        new_kw = first_appear[
            (first_appear['first_date'].dt.date >= start_date)
            & (first_appear['first_date'].dt.date <= end_date)
        ]
        if not new_kw.empty:
            new_kw_with_hits = (
                fdf[fdf['keyword'].isin(new_kw['keyword'])]
                .groupby('keyword')['hits'].sum().reset_index()
                .merge(first_appear, on='keyword')
                .sort_values('hits', ascending=False).head(30)
            )
            new_kw_with_hits['first_date'] = new_kw_with_hits['first_date'].dt.date
            st.dataframe(
                new_kw_with_hits.rename(columns={'keyword': '키워드', 'hits': '검색 hits', 'first_date': '첫 등장일'}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("선택 기간 내 신규 키워드 없음")


# ============== Main ==============
def _auth_token() -> str:
    """app_password의 SHA-256 앞 16자리. anchor 링크 클릭으로 인한 session reset 우회용."""
    import hashlib as _hashlib
    try:
        app_pw = st.secrets.get("app_password", "")
    except Exception:
        app_pw = os.environ.get("APP_PASSWORD", "")
    if not app_pw:
        return ""
    return _hashlib.sha256(app_pw.encode()).hexdigest()[:16]


def check_password() -> bool:
    """Streamlit secrets의 app_password로 간단한 게이트.

    anchor 링크 클릭 시 streamlit session이 reset되는 문제를 회피하기 위해
    URL query param `auth=<token>`로도 인증 상태 유지.
    """
    if st.session_state.get('authenticated'):
        return True

    app_pw = ""
    try:
        app_pw = st.secrets.get("app_password", "")
    except Exception:
        app_pw = os.environ.get("APP_PASSWORD", "")

    if not app_pw:
        # 비밀번호 설정 안 됨 → 게이트 우회 (로컬 개발용)
        return True

    # URL query param에 유효한 auth 토큰이 있으면 자동 인증
    token = _auth_token()
    if token and st.query_params.get('auth') == token:
        st.session_state['authenticated'] = True
        return True

    st.markdown(
        f'<div style="max-width:420px;margin:80px auto;padding:36px 28px;background:white;'
        f'border-radius:14px;box-shadow:0 4px 18px rgba(91,67,201,0.12);text-align:center;">'
        f'<div style="font-size:1.6rem;font-weight:800;color:{PRIMARY};margin-bottom:6px;">🔍 ConnectDI Insights</div>'
        f'<div style="color:#8B8A95;font-size:0.9rem;margin-bottom:24px;">사내 직원 전용 — 비밀번호를 입력하세요</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    c = st.columns([1, 2, 1])
    with c[1]:
        pwd = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                            placeholder="비밀번호 입력", key="login_pwd")
        if st.button("로그인", use_container_width=True, type="primary"):
            if pwd == app_pw:
                st.session_state['authenticated'] = True
                # URL에 auth 토큰 추가 — anchor 링크 클릭 후에도 인증 유지
                st.query_params['auth'] = token
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    return False


def _load_secrets_to_env():
    """Streamlit Cloud의 st.secrets → 환경변수로 복사 (data_loader 호환)."""
    keys = ['DRIVE_FOLDER_DI_KEYWORD', 'DRIVE_FOLDER_PLUS_KEYWORD']
    try:
        for k in keys:
            if k in st.secrets and not os.environ.get(k):
                os.environ[k] = st.secrets[k]
    except Exception:
        pass


def main():
    _load_secrets_to_env()
    if not check_password():
        return

    df = load_data()
    if df.empty:
        st.error("데이터를 불러오지 못했습니다.")
        return

    # query param 처리 시 auth 토큰만 유지 (session reset 방지)
    auth_param = st.query_params.get('auth')

    # 헤더 클릭 시 홈으로 이동 (query param 감지)
    if st.query_params.get('page') == 'home':
        st.session_state['nav_radio'] = "홈 화면"
        st.query_params.clear()
        if auth_param:
            st.query_params['auth'] = auth_param
    # TOP 키워드 클릭 시 검색량 분석 페이지로 + 키워드 입력 자동 설정
    if st.query_params.get('page') == 'mention':
        kw_param = st.query_params.get('kw')
        if kw_param:
            st.session_state['mention_kw'] = kw_param
        st.session_state['nav_radio'] = "검색량 분석"
        st.query_params.clear()
        if auth_param:
            st.query_params['auth'] = auth_param

    # 사이드바
    with st.sidebar:
        page = st.radio(
            "메뉴",
            options=["홈 화면", "검색량 분석", "검색량 비교분석", "기간 검색량 분석"],
            label_visibility="collapsed",
            key="nav_radio",
        )
        st.divider()
        if st.button("🔄 데이터 새로고침", use_container_width=True):
            st.cache_data.clear()
            data_loader.load_connectdi_main.cache_clear()
            data_loader.load_plus_gilbyeong.cache_clear()
            st.rerun()
        st.caption(f"전체 데이터: {len(df):,}행")
        st.caption(f"기간: {df['date'].min().date()} ~ {df['date'].max().date()}")

    # 상단 헤더
    render_top_header()

    # 페이지 콘텐츠 (패딩 영역)
    st.markdown('<div class="page-pad">', unsafe_allow_html=True)
    if page == "홈 화면":
        page_home(df)
    elif page == "검색량 분석":
        page_mention(df)
    elif page == "검색량 비교분석":
        page_compare(df)
    else:
        page_period(df)
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
