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
