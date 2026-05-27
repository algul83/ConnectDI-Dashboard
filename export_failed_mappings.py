"""매핑 실패한 키워드만 Drive에 CSV로 export — 사용자 수기 매핑용.

매핑 완료 후 한 번 실행. 결과 파일을 사용자가 ConnectDI에서 검색해 약품명 채움 →
같은 위치에 다시 업로드 → consolidate_weekly가 자동으로 반영.

출력 CSV:
- keyword: 매핑 실패 키워드 (9자리 보험코드, 6자리 idx 등)
- length: 자릿수
- total_hits: 전체 기간 검색량
- 커넥트디아이 / 커넥트디아이플러스 / 길병원: 사이트별 검색량
- 약품명: 빈 칸 (사용자가 채움)
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import data_loader  # noqa: E402
from consolidate_weekly import (  # noqa: E402
    OUTPUT_FOLDER_ID, _drive_client, upload_or_update_csv,
)

MAPPING_FILE = Path(__file__).parent / "drug_id_mapping.json"
OUTPUT_FILENAME = "unmapped_keywords.csv"


def main():
    load_dotenv()
    import re

    # 1. 자동 매핑 성공 키워드 셋 (이건 export에서 제외)
    auto_mapped: set[str] = set()
    if MAPPING_FILE.exists():
        raw_mapping = json.loads(MAPPING_FILE.read_text(encoding='utf-8'))
        for k, v in raw_mapping.items():
            if isinstance(v, dict) and v.get('name'):
                auto_mapped.add(k)
            elif isinstance(v, str) and v:
                auto_mapped.add(k)
        print(f"[load] 자동 매핑 성공: {len(auto_mapped):,}개 (export에서 제외)")

    # 2. 데이터 로드 + 순수 숫자 키워드 중 매핑 안 된 것 모두 추출
    print("[load] Drive에서 검색 로그 다운로드…")
    df = data_loader.load_all()
    df['keyword'] = df['keyword'].astype(str).str.strip()

    # 순수 숫자 키워드만 (자릿수 무관: 4~16자리 등)
    is_numeric = df['keyword'].str.fullmatch(r'\d+')
    numeric_df = df[is_numeric].copy()
    print(f"  → 순수 숫자 키워드 row: {len(numeric_df):,}")
    print(f"  → 자릿수별 distinct: {numeric_df['keyword'].drop_duplicates().str.len().value_counts().sort_index().to_dict()}")

    # 자동 매핑 안 된 것만
    sub = numeric_df[~numeric_df['keyword'].isin(auto_mapped)].copy()
    distinct_failed = sub['keyword'].nunique()
    print(f"  → 매핑 안 된 distinct 키워드: {distinct_failed:,}개 (모든 자릿수 포함)")

    if sub.empty:
        print("매핑 안 된 숫자 키워드 없음. 종료.")
        return

    # 사이트별 pivot
    pivot = sub.pivot_table(
        index='keyword', columns='site', values='hits',
        aggfunc='sum', fill_value=0
    ).reset_index()

    # total + length 컬럼
    site_cols = [c for c in pivot.columns if c != 'keyword']
    pivot['total_hits'] = pivot[site_cols].sum(axis=1)
    pivot['length'] = pivot['keyword'].str.len()
    pivot['약품명'] = ""  # 사용자가 채울 빈 컬럼

    # 정렬: 자릿수 → 검색량 내림차순
    ordered_cols = ['keyword', 'length', 'total_hits'] + site_cols + ['약품명']
    pivot = pivot[ordered_cols].sort_values(
        ['length', 'total_hits'], ascending=[True, False]
    )

    print(f"[export] {len(pivot):,}개 키워드 export 준비")
    print(f"  자릿수별: {pivot['length'].value_counts().sort_index().to_dict()}")

    # 3. Drive 업로드
    csv_text = pivot.to_csv(index=False)
    print(f"  CSV 크기: {len(csv_text) / 1024:.1f} KB")

    drive = _drive_client()
    upload_or_update_csv(drive, OUTPUT_FOLDER_ID, OUTPUT_FILENAME, csv_text)
    print("\n[done] Drive 업로드 완료. 사용자가 약품명 채워서 같은 위치에 재업로드하면")
    print("       consolidate_weekly 다음 실행 시 자동 반영됩니다.")


if __name__ == "__main__":
    main()
