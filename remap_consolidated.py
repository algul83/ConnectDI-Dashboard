"""매월 1회 실행 — 기존 connectdi_consolidated.csv에 수기 매핑만 재적용.

가벼운 workflow: raw 재통합 없이 unmapped_keywords.csv 의 최신 약품명을
기존 통합 CSV의 남은 코드(keyword)에 반영해 덮어쓴다.

처리:
1. Drive에서 connectdi_consolidated.csv 다운로드
2. Drive에서 unmapped_keywords.csv 다운로드 → rename/drop 매핑 추출
3. keyword 컬럼에 rename 적용 + drop 표시된 row 제거
4. Drive에 재업로드 (update)
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).parent))
from consolidate_weekly import (  # noqa: E402
    OUTPUT_FOLDER_ID,
    OUTPUT_FILENAME,
    DROP_MARKERS,
    _drive_client,
    download_manual_mapping,
    upload_or_update_csv,
)


def _download_consolidated(drive) -> pd.DataFrame:
    q = (
        f"'{OUTPUT_FOLDER_ID}' in parents and trashed=false "
        f"and name='{OUTPUT_FILENAME}'"
    )
    r = drive.files().list(
        q=q, fields="files(id,name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = r.get('files', [])
    if not files:
        raise RuntimeError(f"기존 {OUTPUT_FILENAME} 없음")
    req = drive.files().get_media(fileId=files[0]['id'], supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    text = buf.getvalue().decode('utf-8-sig', errors='replace')
    return pd.read_csv(io.StringIO(text))


def main():
    load_dotenv()

    from datetime import timezone, timedelta
    today_kst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).date()
    if today_kst.day != 1 and not os.environ.get('FORCE_REMAP'):
        print(f"[skip] 오늘 KST = {today_kst} (매월 1일에만 실행)")
        return

    print(f"[{datetime.now().isoformat(timespec='seconds')}] 재적용 시작")

    drive = _drive_client()

    print("[1/3] 기존 통합 CSV 다운로드…")
    df = _download_consolidated(drive)
    print(f"  → {len(df):,}행")

    print("[2/3] unmapped_keywords.csv 매핑 읽기…")
    rename_mapping, drop_keywords = download_manual_mapping(drive, OUTPUT_FOLDER_ID)
    if not rename_mapping and not drop_keywords:
        print("  → 반영할 매핑 없음. 종료.")
        return

    df['keyword'] = df['keyword'].astype(str).str.strip()

    if drop_keywords:
        before = len(df)
        df = df[~df['keyword'].isin(drop_keywords)].reset_index(drop=True)
        print(f"  → 삭제 표시 매치 row {before - len(df):,}개 제거")

    if rename_mapping:
        touched = df['keyword'].isin(rename_mapping).sum()
        df['keyword'] = df['keyword'].map(lambda k: rename_mapping.get(k, k))
        print(f"  → 약품명 치환 row {touched:,}개")

    # 매핑 결과가 삭제 마커 텍스트인 잔여 row도 정리
    drop_lower = {m.lower() for m in DROP_MARKERS}
    before2 = len(df)
    df = df[~df['keyword'].astype(str).str.strip().str.lower().isin(drop_lower)].reset_index(drop=True)
    if before2 != len(df):
        print(f"  → 마커 텍스트 row {before2 - len(df):,}개 추가 제거")

    print("[3/3] Drive 업로드…")
    upload_or_update_csv(drive, OUTPUT_FOLDER_ID, OUTPUT_FILENAME, df.to_csv(index=False))
    print(f"[{datetime.now().isoformat(timespec='seconds')}] 재적용 완료 ({len(df):,}행)")


if __name__ == "__main__":
    main()
