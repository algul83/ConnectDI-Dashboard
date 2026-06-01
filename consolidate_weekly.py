"""주 1회 실행 — 3개 사이트 검색 로그 통합 + 보험코드 매핑 적용 + Drive 업로드.

Routine으로 매주 월요일 새벽 5시 KST에 실행.

처리 흐름:
1. data_loader.load_all() — 3개 사이트 CSV 통합 (Drive에서 다운로드)
2. 영어 불용어 제거
3. drug_id_mapping.json 적용 (보험코드/품목기준코드 → 약품명)
4. 통합 CSV를 Drive "GA / ConnectDI Keyword" 폴더에 업로드
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# data_loader 위치
import sys
sys.path.insert(0, str(Path(__file__).parent))
import data_loader  # noqa: E402

OUTPUT_FOLDER_ID = "12Sq6BElubCNMClsBU3R6CxqJ0VcnprEr"  # GA / ConnectDI Keyword
OUTPUT_FILENAME = "connectdi_consolidated.csv"
MANUAL_MAPPING_FILENAME = "unmapped_keywords.csv"  # 사용자 수기 매핑 결과
MAPPING_FILE = Path(__file__).parent / "drug_id_mapping.json"

# 사용자가 수기 매핑 CSV에 입력할 수 있는 "삭제 표시" — 해당 키워드는 통합 CSV에서 제외됨
DROP_MARKERS = {'매칭불가', '삭제', 'delete', 'drop', '제거', '불가', 'N/A', 'na', '-'}

import re

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
    # ConnectDI 사이트 navigation 단어
    'list', 'detail', 'page', 'home', 'main', 'search', 'view', 'item',
    'show', 'index', 'menu', 'login', 'logout',
}

KR_STOPWORDS = {
    # 조사/접사
    '의', '가', '이', '은', '는', '을', '를', '에', '와', '과', '도', '만', '에서', '에게', '한테',
    # 대명사
    '그', '이', '저', '그것', '이것', '저것', '나', '너', '우리', '여기', '거기',
    '무엇', '어떤', '무슨', '어느', '어디', '언제', '왜', '어떻게',
    # 부사
    '정말', '너무', '매우', '아주', '많이', '조금', '거의', '대충', '좀', '잘', '안', '못',
    '더', '덜', '또', '또한', '항상', '늘',
    # 접속사
    '그리고', '그러나', '하지만', '그래서', '따라서', '그러므로', '그래도', '그러면',
    # 일반 동사·형용사 어간
    '있다', '없다', '한다', '된다', '했다', '됐다', '있어', '없어',
    '하다', '되다', '이다', '아니다',
}


def is_valid_keyword(kw: str) -> bool:
    """1글자/특수문자/공백/한글 불용어 등 제거. 5자리 이하 순수 숫자도 노이즈로 제거.
    내부 사용 키워드(K-*, DC*)도 제거.
    """
    s = str(kw).strip()
    if not s:
        return False
    if len(s) <= 1:
        return False
    # 한글/영문/숫자가 하나도 없으면 (특수문자만) 제거
    if not re.search(r'[가-힣A-Za-z0-9]', s):
        return False
    if s in KR_STOPWORDS:
        return False
    if s.lower() in EN_STOPWORDS:
        return False
    # 5자리 이하 순수 숫자는 노이즈로 간주 (의미 있는 코드는 6자리 이상)
    if s.isdigit() and len(s) <= 5:
        return False
    # 내부용 키워드 제외: K- 또는 DC로 시작 (대소문자 무관)
    sl = s.lower()
    if sl.startswith('k-') or sl.startswith('dc'):
        return False
    return True


def _drive_client():
    sa_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')
    if not sa_file or not os.path.exists(sa_file):
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE 환경변수 없거나 파일 없음")
    creds = service_account.Credentials.from_service_account_file(
        sa_file, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


def download_manual_mapping(drive, folder_id: str) -> tuple[dict[str, str], set[str]]:
    """수기 매핑 CSV (unmapped_keywords.csv)를 Drive에서 다운로드.

    Returns:
        (rename_mapping, drop_keywords)
        - rename_mapping: 약품명으로 치환할 매핑 {keyword: 약품명}
        - drop_keywords: '매칭불가' 등 삭제 표시된 키워드 set
    """
    q = (
        f"'{folder_id}' in parents and trashed=false "
        f"and name='{MANUAL_MAPPING_FILENAME}'"
    )
    r = drive.files().list(
        q=q, fields="files(id,name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = r.get('files', [])
    if not files:
        print(f"  → 수기 매핑 CSV 없음: {MANUAL_MAPPING_FILENAME}")
        return {}, set()

    file_id = files[0]['id']
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    csv_text = buf.getvalue().decode('utf-8-sig')

    df = pd.read_csv(io.StringIO(csv_text))
    df['keyword'] = df['keyword'].astype(str).str.strip()
    if '약품명' not in df.columns:
        print(f"  → '약품명' 컬럼 없음, skip")
        return {}, set()

    filled = df[df['약품명'].astype(str).str.strip().replace('nan', '').ne('')]
    rename_mapping: dict[str, str] = {}
    drop_keywords: set[str] = set()
    for _, row in filled.iterrows():
        name = str(row['약품명']).strip()
        if name.lower() in {m.lower() for m in DROP_MARKERS}:
            drop_keywords.add(row['keyword'])
        else:
            rename_mapping[row['keyword']] = name

    untouched = len(df) - len(rename_mapping) - len(drop_keywords)
    print(f"  → 수기 매핑 {len(rename_mapping):,}개 (약품명 치환)")
    print(f"  → 삭제 표시 {len(drop_keywords):,}개 (매칭불가 등 → 통합 CSV에서 제외)")
    print(f"  → 미채움 {untouched:,}개 (기존 키워드 그대로)")
    return rename_mapping, drop_keywords


def upload_or_update_csv(drive, folder_id: str, filename: str, csv_text: str) -> str:
    """Drive 폴더에 동일 이름 파일이 있으면 update, 없으면 새로 생성."""
    q = (
        f"'{folder_id}' in parents and trashed=false "
        f"and name='{filename}' and mimeType='text/csv'"
    )
    r = drive.files().list(
        q=q, fields="files(id,name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    existing = r.get('files', [])

    media = MediaIoBaseUpload(
        io.BytesIO(csv_text.encode('utf-8-sig')),
        mimetype='text/csv', resumable=False,
    )

    if existing:
        file_id = existing[0]['id']
        drive.files().update(
            fileId=file_id, media_body=media,
            supportsAllDrives=True,
        ).execute()
        print(f"  [update] {filename} (id={file_id})")
        return file_id
    else:
        file = drive.files().create(
            body={'name': filename, 'parents': [folder_id], 'mimeType': 'text/csv'},
            media_body=media, fields='id',
            supportsAllDrives=True,
        ).execute()
        print(f"  [create] {filename} (id={file['id']})")
        return file['id']


def main():
    load_dotenv()

    print(f"[{datetime.now().isoformat(timespec='seconds')}] 통합 시작")

    # 1. 3개 사이트 통합 (Drive에서 다운로드)
    print("[1/4] 3개 사이트 검색 로그 다운로드 + 통합…")
    df = data_loader.load_all()
    print(f"  → 통합 행수: {len(df):,}")

    # 2. 불용어/1글자/특수문자 등 정제
    print("[2/4] 키워드 정제 (불용어·1글자·특수문자·list/detail 등)…")
    before = len(df)
    mask = df['keyword'].apply(is_valid_keyword)
    df = df[mask].reset_index(drop=True)
    print(f"  → {before - len(df):,}행 제거, {len(df):,}행 남음")

    # 3. 보험코드/품목기준코드 → 약품명 매핑 적용 (자동 매핑 + 수기 매핑)
    print("[3/4] 약품명 매핑 적용…")
    drive = _drive_client()

    # 3-1. 자동 매핑 (drug_id_mapping.json)
    valid_mapping: dict[str, str] = {}
    if MAPPING_FILE.exists():
        raw_mapping = json.loads(MAPPING_FILE.read_text(encoding='utf-8'))
        for k, v in raw_mapping.items():
            if isinstance(v, dict) and v.get('name'):
                valid_mapping[k] = v['name']
            elif isinstance(v, str) and v:
                valid_mapping[k] = v
        print(f"  → 자동 매핑 사전 {len(valid_mapping):,}개")
    else:
        print(f"  → 자동 매핑 파일 없음: {MAPPING_FILE}")

    # 3-2. 수기 매핑 (Drive의 unmapped_keywords.csv) — 약품명 치환 + 삭제 표시
    manual_mapping, drop_keywords = download_manual_mapping(drive, OUTPUT_FOLDER_ID)
    if manual_mapping:
        valid_mapping.update(manual_mapping)  # 수기 매핑이 자동 매핑 덮어씀

    # 3-3. 매핑 적용 + 삭제 표시된 키워드 제거
    df['keyword'] = df['keyword'].astype(str).str.strip()
    if drop_keywords:
        before_rows = len(df)
        df = df[~df['keyword'].isin(drop_keywords)].reset_index(drop=True)
        print(f"  → 삭제 표시된 원본 키워드 → {before_rows - len(df):,}행 제거")
    before_kw_unique = df['keyword'].nunique()
    df['keyword'] = df['keyword'].map(lambda k: valid_mapping.get(k, k))
    # 매핑 결과가 DROP_MARKERS 텍스트인 row도 제거 (이전 통합 CSV의 잔여 처리)
    drop_lower = {m.lower() for m in DROP_MARKERS}
    before_rows2 = len(df)
    df = df[~df['keyword'].astype(str).str.strip().str.lower().isin(drop_lower)].reset_index(drop=True)
    if before_rows2 != len(df):
        print(f"  → 매핑 결과가 삭제 마커({len(DROP_MARKERS)}종)인 row {before_rows2 - len(df):,}행 추가 제거")
    after_kw_unique = df['keyword'].nunique()
    print(f"  → 매핑 적용 후 distinct keyword: {before_kw_unique:,} → {after_kw_unique:,}")

    # 4. Drive 업로드
    print("[4/4] Drive 업로드…")
    csv_text = df.to_csv(index=False)
    print(f"  → CSV 크기: {len(csv_text) / 1024 / 1024:.2f} MB")

    drive = _drive_client()
    upload_or_update_csv(drive, OUTPUT_FOLDER_ID, OUTPUT_FILENAME, csv_text)

    print(f"[{datetime.now().isoformat(timespec='seconds')}] 통합 완료")


if __name__ == "__main__":
    main()
