"""3개 사이트(커넥트디아이/플러스/길병원) 검색 로그 통합 로드.

Drive에 있는 **모든 CSV 파일을 합쳐서** 전체 데이터 구성.
중복은 각 CSV의 Id/id 컬럼 기준으로 제거.
"""
from __future__ import annotations

import io
import os
import re
from datetime import date
from functools import lru_cache

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def _drive_client():
    """Streamlit secrets 또는 환경변수에서 SA 자격증명 로드."""
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                dict(st.secrets['gcp_service_account']), scopes=SCOPES
            )
            return build('drive', 'v3', credentials=creds)
    except Exception:
        pass

    sa_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')
    if not sa_file or not os.path.exists(sa_file):
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE 환경변수가 없거나 파일 없음")
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def _list_files(drive, folder_id: str, name_contains: str = "") -> list[dict]:
    # gzip으로 저장된 CSV도 포함 (stat routine이 일부 파일을 gzip으로 업로드)
    q = (
        f"'{folder_id}' in parents and trashed=false "
        f"and (mimeType='text/csv' or mimeType='application/gzip' "
        f"or mimeType='application/x-gzip')"
    )
    if name_contains:
        q += f" and name contains '{name_contains}'"
    r = drive.files().list(
        q=q, fields="files(id,name,modifiedTime)",
        orderBy="modifiedTime desc", pageSize=500,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return r.get('files', [])


def _download_csv(drive, file_id: str) -> str:
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    raw = buf.getvalue()
    # gzip 매직 바이트 자동 감지 → 압축 해제
    if raw[:2] == b'\x1f\x8b':
        import gzip
        try:
            raw = gzip.decompress(raw)
        except Exception:
            # CRC 실패 등 손상된 gzip은 raw deflate로 관대하게 파싱 (뒷부분 손실 감수)
            import zlib, struct
            flg = raw[3]
            pos = 10
            if flg & 4:  # FEXTRA
                xlen = struct.unpack('<H', raw[pos:pos+2])[0]
                pos += 2 + xlen
            if flg & 8:  # FNAME (null-terminated)
                while pos < len(raw) and raw[pos] != 0:
                    pos += 1
                pos += 1
            if flg & 16:  # FCOMMENT
                while pos < len(raw) and raw[pos] != 0:
                    pos += 1
                pos += 1
            if flg & 2:  # FHCRC
                pos += 2
            decomp = zlib.decompressobj(-zlib.MAX_WBITS)
            raw = decomp.decompress(raw[pos:-8]) + decomp.flush()
    for encoding in ('utf-8-sig', 'utf-8', 'cp949'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


@lru_cache(maxsize=4)
def load_connectdi_main(folder_id: str) -> pd.DataFrame:
    """커넥트디아이 메인 사이트 검색 로그 — Drive 폴더 안 모든 ConnectDI_search-stats CSV 합침.

    누적 CSV들이라 같은 Id가 여러 파일에 등장 → Id 컬럼 기준 dedup.
    """
    drive = _drive_client()
    files = _list_files(drive, folder_id, "ConnectDI_search-stats")
    if not files:
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            csv_text = _download_csv(drive, f['id'])
            df = pd.read_csv(io.StringIO(csv_text))
        except Exception as e:
            print(f"  [skip] {f['name']}: {e}")
            continue
        df.columns = [c.strip() for c in df.columns]
        if 'Id' not in df.columns or 'Search terms' not in df.columns:
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    df_all = pd.concat(frames, ignore_index=True)
    # Id 기준 dedup (누적 CSV라 중복 많음)
    df_all = df_all.drop_duplicates(subset=['Id'], keep='last')

    # 파일마다 timestamp 형식이 다름 (구형 `+0900`, 신형 `UTC`) → format='mixed'로 두 형식 모두 파싱
    df_all['Created at'] = pd.to_datetime(df_all['Created at'], format='mixed', errors='coerce', utc=True)
    df_all['date'] = df_all['Created at'].dt.tz_convert('Asia/Seoul').dt.date
    df_all['site'] = '커넥트디아이'
    df_all = df_all.rename(columns={'Search terms': 'keyword', 'Search hit': 'hits'})
    return df_all[['site', 'date', 'keyword', 'hits']].dropna(subset=['date', 'keyword'])


_PLUS_FILENAME_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})(?:_\d{4}-\d{2}-\d{2})?_(플러스|길병원)_')
# 1회성 풀-히스토리 덤프: 플러스베타_YYYYMM_YYYYMM.csv, 플러스_YYYYMM_YYYYMM.csv,
# 길병원_YYYYMM_YYYYMM.csv — 시작/종료 월 표기. 플러스베타가 플러스를 prefix로
# 갖기 때문에 alternation 순서 주의 (긴 토큰 먼저).
_PLUS_FULLDUMP = re.compile(r'^(플러스베타|플러스|길병원)_\d{6}_\d{6}\.csv$')


def _identify_plus_site(filename: str) -> str | None:
    """파일명에서 사이트 식별. 일별 CSV + 마스터 누적 CSV + 1회성 풀-덤프 모두 처리.
    플러스베타는 커넥트디아이플러스의 베타 환경 데이터로 동일 사이트로 통합."""
    # 일별 CSV: YYYY-MM-DD_플러스_... or YYYY-MM-DD_길병원_...
    m = _PLUS_FILENAME_DATE.match(filename)
    if m:
        return '커넥트디아이플러스' if m.group(2) == '플러스' else '길병원'
    # 1회성 풀-덤프: 플러스/플러스베타/길병원_YYYYMM_YYYYMM.csv
    m = _PLUS_FULLDUMP.match(filename)
    if m:
        return '길병원' if m.group(1) == '길병원' else '커넥트디아이플러스'
    # 마스터 누적 CSV
    if '커넥트디아이플러스 키워드 검색결과' in filename or '커넥트디아이플러스_키워드_검색결과' in filename:
        return '커넥트디아이플러스'
    if '길병원 키워드 검색결과' in filename or '길병원_키워드_검색결과' in filename:
        return '길병원'
    return None


@lru_cache(maxsize=4)
def load_plus_gilbyeong(folder_id: str) -> pd.DataFrame:
    """커넥트디아이플러스 + 길병원 전체 검색 로그.

    일별 CSV (YYYY-MM-DD_플러스/길병원_*.csv) + 누적 마스터 CSV (커넥트디아이플러스 키워드 검색결과.csv,
    길병원 키워드 검색결과.csv) 모두 합침. id 컬럼 기준 dedup.
    """
    drive = _drive_client()
    files = _list_files(drive, folder_id)
    frames = []
    for f in files:
        site = _identify_plus_site(f['name'])
        if not site:
            continue
        try:
            csv_text = _download_csv(drive, f['id'])
            # 손상된 CSV(gzip 파일 뒷부분 이슈 등)도 앞부분은 파싱 시도
            df = pd.read_csv(io.StringIO(csv_text), on_bad_lines='skip')
        except Exception as e:
            print(f"  [skip] {f['name']}: {e}")
            continue
        if df.empty or 'search_keyword' not in df.columns:
            continue
        df['site'] = site
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=['site', 'date', 'keyword', 'hits'])

    df_all = pd.concat(frames, ignore_index=True)
    # id 컬럼 기준 dedup (각 행이 1회 검색 이벤트, id가 unique)
    if 'id' in df_all.columns:
        df_all = df_all.drop_duplicates(subset=['id'], keep='last')

    # 날짜는 created_at에서 추출 (KST 변환)
    df_all['created_at_dt'] = pd.to_datetime(df_all['created_at'], errors='coerce', utc=True)
    df_all['date'] = df_all['created_at_dt'].dt.tz_convert('Asia/Seoul').dt.date
    df_all = df_all.rename(columns={'search_keyword': 'keyword'})
    df_all['hits'] = 1
    return df_all[['site', 'date', 'keyword', 'hits']].dropna(subset=['date', 'keyword'])


CONSOLIDATED_FOLDER_ID = os.environ.get(
    'DRIVE_FOLDER_CONSOLIDATED', '12Sq6BElubCNMClsBU3R6CxqJ0VcnprEr'
)
CONSOLIDATED_FILENAME = 'connectdi_consolidated.csv'


@lru_cache(maxsize=2)
def load_consolidated(folder_id: str) -> pd.DataFrame:
    """주 1회 갱신되는 통합 CSV를 Drive에서 다운로드."""
    drive = _drive_client()
    q = (
        f"'{folder_id}' in parents and trashed=false "
        f"and name='{CONSOLIDATED_FILENAME}'"
    )
    r = drive.files().list(
        q=q, fields="files(id,name,modifiedTime)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = r.get('files', [])
    if not files:
        return pd.DataFrame()
    csv_text = _download_csv(drive, files[0]['id'])
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
    return df


def load_all() -> pd.DataFrame:
    """검색 로그 통합 로드.

    우선순위:
    1. Drive의 통합 CSV (주 1회 갱신) — 매우 빠름
    2. fallback: 3개 사이트 raw CSV 통합 (느림)
    """
    # 1. 통합 CSV 우선 시도
    try:
        df = load_consolidated(CONSOLIDATED_FOLDER_ID)
        if not df.empty:
            return df
    except Exception as e:
        print(f"[warn] consolidated load failed: {e}")

    # 2. fallback — 기존 통합 로직
    di_folder = os.environ.get('DRIVE_FOLDER_DI_KEYWORD', '1tsEwHFoQWIIBCVNtCeNKrVjbXAiFGtXK')
    plus_folder = os.environ.get('DRIVE_FOLDER_PLUS_KEYWORD', '1rYLAKFUNYp7uAf3bNqx4bafZuf3jQDQ7')

    df_di = load_connectdi_main(di_folder)
    df_plus = load_plus_gilbyeong(plus_folder)

    parts = [df for df in [df_di, df_plus] if not df.empty]
    if not parts:
        return pd.DataFrame(columns=['site', 'date', 'keyword', 'hits'])
    return pd.concat(parts, ignore_index=True)


GA_WEB_FOLDER_ID = '1PId0m0Koq-HC5JtmofyNyCCJ-fiporEP'   # ConnectDI 웹 GA
GA_APP_FOLDER_ID = '1-slUrf0Juh5P4QJofqC1nXwSvp7zJGaf'   # ConnectCare 앱 GA


@lru_cache(maxsize=4)
def _load_latest_ga_csv(folder_id: str) -> tuple[str, str]:
    """폴더에서 최신 보고서_개요_YYYYMMDD.csv 다운로드. (파일명, 텍스트) 반환."""
    drive = _drive_client()
    r = drive.files().list(
        q=f"'{folder_id}' in parents and name contains '보고서_개요_' and trashed=false",
        fields="files(id,name)",
        orderBy="name desc", pageSize=1,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = r.get('files', [])
    if not files:
        return '', ''
    return files[0]['name'], _download_csv(drive, files[0]['id'])


def _parse_ga_sections(csv_text: str) -> list[dict]:
    """GA CSV를 섹션별로 파싱. 각 섹션: {header: str, rows: list[list[str]]}."""
    sections = []
    current = None
    for line in csv_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            if current and current.get('header') and current.get('rows'):
                sections.append(current)
                current = None
            continue
        if current is None:
            current = {'header': line, 'rows': []}
        elif current['header'] is None:
            current['header'] = line
        else:
            current['rows'].append([c.strip() for c in line.split(',')])
    if current and current.get('header') and current.get('rows'):
        sections.append(current)
    return sections


def _find_section(sections: list[dict], header_starts: str) -> dict | None:
    for s in sections:
        if s['header'].startswith(header_starts):
            return s
    return None


def _find_all_sections(sections: list[dict], header_starts: str) -> list[dict]:
    return [s for s in sections if s['header'].startswith(header_starts)]


def _extract_period(csv_text: str) -> tuple:
    """CSV 헤더의 첫 `# 시작일`~`# 종료일` 추출.

    Why: 파일의 진짜 대상 기간은 항상 첫 섹션 헤더에 있음. min/max로 뽑으면
    정기 주간 파일 내부의 30일 rolling 섹션 헤더(예: 30일 전 시작일)까지 섞여서
    정기 파일이 bulk로 오탐지됨.
    """
    import re as _re
    s_match = _re.search(r'#\s*시작일:\s*(\d{8})', csv_text)
    e_match = _re.search(r'#\s*종료일:\s*(\d{8})', csv_text)
    if not s_match or not e_match:
        return None, None
    s, e = s_match.group(1), e_match.group(1)
    from datetime import date as _date
    return (_date(int(s[:4]), int(s[4:6]), int(s[6:])),
            _date(int(e[:4]), int(e[4:6]), int(e[6:])))


def parse_ga_bulk_weekly(csv_text: str) -> list:
    """넓은 기간(7일 초과) GA CSV → 주별 데이터 리스트 반환.

    `N일,30일,7일,1일` (활성 사용자 추이) 섹션의 하루 단위 값을 주간으로 그룹핑.
    다른 지표(신규 사용자 수, 참여 시간)도 하루 단위 섹션이 있으면 활용.
    채널/국가 등 기간 요약 지표는 시계열 breakdown 없으므로 0으로 채움.

    Returns: list of dict (각 원소 = 주간 row)
    """
    from datetime import timedelta as _td
    from collections import defaultdict as _dd
    start, end = _extract_period(csv_text)
    if not start:
        return []

    sections = _parse_ga_sections(csv_text)

    def _to_int(v: str) -> int:
        try: return int(float(v))
        except: return 0

    def _to_float(v: str) -> float:
        try: return float(v)
        except: return 0.0

    # 하루 단위 시계열 섹션들 (N일,... 형식)
    trend = _find_section(sections, 'N일,30일')  # 활성 사용자 추이
    daily_active = _find_section(sections, 'N일,활성 사용자')  # 단순 활성 사용자 (DAU 계열)
    daily_new = _find_section(sections, 'N일,새 사용자')
    daily_engage = _find_section(sections, 'N일,활성 사용자당 평균 참여')

    def _row_by_offset(sec, col_idx):
        if not sec: return {}
        out = {}
        for r in sec.get('rows', []):
            if len(r) <= col_idx: continue
            try: offset = int(r[0])
            except: continue
            out[offset] = r[col_idx]
        return out

    mau_by = _row_by_offset(trend, 1)   # 30일 rolling MAU
    wau_by = _row_by_offset(trend, 2)   # 7일 rolling WAU
    dau_by = _row_by_offset(trend, 3)   # 1일
    active_by = _row_by_offset(daily_active, 1)
    new_by = _row_by_offset(daily_new, 1)
    engage_by = _row_by_offset(daily_engage, 1)

    total_days = (end - start).days + 1
    weekly = _dd(list)  # week_start -> [ {date, mau, wau, dau, active, new, engage} ]
    for i in range(total_days):
        d = start + _td(days=i)
        ws = d - _td(days=d.weekday())
        weekly[ws].append({
            'mau': _to_int(mau_by.get(i, 0)),
            'wau': _to_int(wau_by.get(i, 0)),
            'dau': _to_int(dau_by.get(i, 0)),
            'active': _to_int(active_by.get(i, 0)),
            'new': _to_int(new_by.get(i, 0)),
            'engage': _to_float(engage_by.get(i, 0)),
        })

    rows = []
    for ws in sorted(weekly):
        recs = weekly[ws]
        n = len(recs)
        mau = recs[-1]['mau'] or max(r['mau'] for r in recs)
        avg_wau = int(sum(r['wau'] for r in recs) / n) if n else 0
        # DAU 시리즈: trend의 1일 컬럼이 있으면 그것, 없으면 daily_active
        dau_vals = [r['dau'] or r['active'] for r in recs]
        avg_dau = int(sum(dau_vals) / len(dau_vals)) if dau_vals else 0
        engage_vals = [r['engage'] for r in recs if r['engage']]
        engage = round(sum(engage_vals) / len(engage_vals), 1) if engage_vals else 0.0
        new_sum = sum(r['new'] for r in recs)
        stickiness = round(avg_dau / mau * 100, 1) if mau else 0.0
        rows.append({
            'week_start': ws,
            'file_name': f'bulk({start}~{end})',
            'mau': mau,
            'avg_dau': avg_dau,
            'avg_wau': avg_wau,
            'stickiness': stickiness,
            'engagement_sec': engage,
            'sessions_total': 0,
            'sessions_organic': 0, 'sessions_direct': 0, 'sessions_ai': 0,
            'new_total': new_sum,
            'new_organic': 0, 'new_direct': 0, 'new_ai': 0,
        })
    return rows


def parse_ga_report(csv_text: str) -> dict:
    """GA CSV → 지표 dict 반환. 웹/앱 공통."""
    sections = _parse_ga_sections(csv_text)
    result = {'raw_sections_count': len(sections)}

    # 활성 사용자 추이: N일,30일,7일,1일 (또는 유사)
    trend = _find_section(sections, 'N일,30일')
    if trend:
        rows = [[float(v) if v.replace('.','').replace('-','').isdigit() else 0 for v in r] for r in trend.get('rows', [])]
        if rows:
            # 마지막 유효 row의 30일 컬럼 (index 1)이 MAU
            result['mau'] = int(rows[-1][1]) if len(rows[-1]) > 1 else 0
            result['avg_wau'] = int(sum(r[2] for r in rows) / len(rows)) if len(rows[0]) > 2 else 0
            result['avg_dau'] = int(sum(r[3] for r in rows) / len(rows)) if len(rows[0]) > 3 else 0
            result['stickiness'] = round(result['avg_dau'] / result['mau'] * 100, 1) if result.get('mau') else 0.0

    # 활성 사용자당 평균 참여 시간: N일 별 값 평균
    engage = _find_section(sections, 'N일,활성 사용자당 평균 참여 시간')
    if engage:
        vals = [float(r[1]) for r in engage['rows'] if len(r) > 1 and r[1].replace('.','').replace('-','').isdigit()]
        result['avg_engagement_sec'] = round(sum(vals) / len(vals), 1) if vals else 0.0

    # 신규 사용자 채널 (기본 채널 그룹)
    new_ch = _find_section(sections, '신규 사용자 기본 채널 그룹')
    if new_ch:
        result['new_by_channel'] = [(r[0], int(r[1])) for r in new_ch['rows'] if len(r) > 1 and r[1].isdigit()]
        result['new_total'] = sum(n for _, n in result['new_by_channel'])

    # 세션 채널
    sess_ch = _find_section(sections, '세션 기본 채널 그룹')
    if sess_ch:
        result['sessions_by_channel'] = [(r[0], int(r[1])) for r in sess_ch['rows'] if len(r) > 1 and r[1].isdigit()]
        result['sessions_total'] = sum(n for _, n in result['sessions_by_channel'])

    # 국가 (활성 사용자, ID가 아닌 국가명)
    countries = _find_all_sections(sections, '국가,활성 사용자')
    if countries:
        result['top_countries'] = [(r[0], int(r[1])) for r in countries[0]['rows'][:10] if len(r) > 1 and r[1].isdigit()]

    # TOP 페이지/화면
    pages = _find_section(sections, '페이지 제목 및 화면 클래스')
    if pages:
        result['top_pages'] = [(r[0], int(r[1])) for r in pages['rows'][:9] if len(r) > 1 and r[1].isdigit()]

    # TOP 이벤트
    events = _find_section(sections, '이벤트 이름,이벤트 수')
    if events:
        result['top_events'] = [(r[0], int(r[1])) for r in events['rows'][:10] if len(r) > 1 and r[1].isdigit()]

    # 플랫폼 (앱만) — 플랫폼,주요 이벤트 또는 플랫폼,활성 사용자
    platforms = _find_section(sections, '플랫폼,')
    if platforms:
        result['platforms'] = [(r[0], int(r[1])) for r in platforms['rows'] if len(r) > 1 and r[1].isdigit()]

    return result


def load_ga_web_report() -> dict:
    """ConnectDI 웹 GA 최신 리포트 파싱."""
    name, text = _load_latest_ga_csv(GA_WEB_FOLDER_ID)
    if not text:
        return {}
    r = parse_ga_report(text)
    r['file_name'] = name
    return r


def load_ga_app_report() -> dict:
    """ConnectCare 앱 GA 최신 리포트 파싱."""
    name, text = _load_latest_ga_csv(GA_APP_FOLDER_ID)
    if not text:
        return {}
    r = parse_ga_report(text)
    r['file_name'] = name
    return r


@lru_cache(maxsize=4)
def load_ga_history(folder_id: str, limit: int = 200) -> pd.DataFrame:
    """최근 N주 GA CSV들을 로드해 주간 지표 시계열 DataFrame 반환.

    Returns: columns = [week_start, mau, avg_dau, avg_wau, stickiness, engagement_sec,
                        sessions_total, sessions_organic, sessions_direct, sessions_ai,
                        new_total, new_organic, new_direct, new_ai, file_name]
    """
    import re as _re
    drive = _drive_client()
    r = drive.files().list(
        q=f"'{folder_id}' in parents and name contains '보고서_개요_' and trashed=false",
        fields="files(id,name)",
        orderBy="name desc", pageSize=max(limit, 100),
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = r.get('files', [])[:limit]
    rows = []
    for f in files:
        try:
            text = _download_csv(drive, f['id'])
        except Exception:
            continue

        # 파일 내용의 시작일~종료일 기간으로 bulk 여부 판단 (7일 초과 = bulk)
        s_date, e_date = _extract_period(text)
        if s_date and e_date and (e_date - s_date).days > 7:
            # Bulk 파일: 하루 단위 시계열을 주간으로 그룹핑해 여러 row 반환
            rows.extend(parse_ga_bulk_weekly(text))
            continue

        # 정기 주간 파일: 파일명의 YYYYMMDD를 week_start로 사용
        m = _re.search(r'(\d{8})', f['name'])
        if not m:
            continue
        yyyymmdd = m.group(1)
        try:
            week_start = pd.Timestamp(f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}").date()
        except Exception:
            continue
        parsed = parse_ga_report(text)

        def _ch(name: str, source_key: str) -> int:
            return next((cnt for n, cnt in parsed.get(source_key, []) if n == name), 0)

        rows.append({
            'week_start': week_start,
            'file_name': f['name'],
            'mau': parsed.get('mau', 0),
            'avg_dau': parsed.get('avg_dau', 0),
            'avg_wau': parsed.get('avg_wau', 0),
            'stickiness': parsed.get('stickiness', 0.0),
            'engagement_sec': parsed.get('avg_engagement_sec', 0.0),
            'sessions_total': parsed.get('sessions_total', 0),
            'sessions_organic': _ch('Organic Search', 'sessions_by_channel'),
            'sessions_direct': _ch('Direct', 'sessions_by_channel'),
            'sessions_ai': _ch('AI Assistant', 'sessions_by_channel'),
            'new_total': parsed.get('new_total', 0),
            'new_organic': _ch('Organic Search', 'new_by_channel'),
            'new_direct': _ch('Direct', 'new_by_channel'),
            'new_ai': _ch('AI Assistant', 'new_by_channel'),
        })
    if not rows:
        return pd.DataFrame()
    # 같은 week_start가 여러 소스에 있으면 정기 파일(bulk 아닌 것) 우선
    df = pd.DataFrame(rows).sort_values(['week_start', 'file_name'])
    df['is_bulk'] = df['file_name'].str.startswith('bulk(')
    df = df.sort_values(['week_start', 'is_bulk']).drop_duplicates(
        subset='week_start', keep='first').drop(columns='is_bulk')
    return df.sort_values('week_start').reset_index(drop=True)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    df = load_all()
    print(f"총 행수: {len(df):,}")
    print(f"\n사이트별:")
    print(df['site'].value_counts().to_string())
    print(f"\n사이트별 날짜 범위:")
    for site in df['site'].unique():
        sub = df[df['site'] == site]
        print(f"  {site}: {sub['date'].min()} ~ {sub['date'].max()} ({len(sub):,}행)")
