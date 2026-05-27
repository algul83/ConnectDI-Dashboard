"""ConnectDI 숫자 키워드 → 약품명 매핑 생성.

데이터에서 6자리(dl_idx) / 9자리(di_edi_code) 숫자 키워드를 추출 →
www.connectdi.com에서 약품명 fetch → drug_id_mapping.json 에 저장.

한 번 실행해서 매핑 만들고, data_loader가 그 매핑을 적용해 키워드 치환.
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import data_loader  # noqa: E402

MAPPING_FILE = Path(__file__).parent / "drug_id_mapping.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
TIMEOUT = 15
MAX_WORKERS = 8


def _extract_drug_name(html: str) -> str | None:
    """약품 페이지 HTML에서 <a href="?pap=detail&dl_idx=…">약품명</a> 의 첫 번째 한글명 추출."""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select('a[href*="pap=detail&dl_idx="]')
    for a in links:
        parts = list(a.stripped_strings)
        if parts:
            return parts[0]
    # fallback: img alt 속성
    img = soup.select_one('img[alt][src*="medi-img"]')
    if img and img.get("alt"):
        return img["alt"].strip()
    return None


def _fetch_search(keyword: str, type_param: str) -> str | None:
    url = (
        "https://www.connectdi.com/cont/drug/?pap=search_result"
        f"&search_keyword_type={type_param}&search_keyword={keyword}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return _extract_drug_name(r.text)
    except Exception:
        return None


def _strip_dosage(name: str) -> str:
    """약품명에서 함량/규격 부분 제거. '소론도정 5mg' → '소론도정', '박티그라 (10x10㎠)' → '박티그라'."""
    s = (name or "").strip()
    # 첫 공백 + (숫자/괄호/대괄호) 등장 위치 이후 모두 제거
    m = re.match(r"^(.+?)\s+[\d(\[].*$", s)
    if m:
        return m.group(1).strip()
    return s


def fetch_by_idx(idx: str) -> dict | None:
    # 6자리 키워드 — 주성분코드 fallback (정확도 낮음 → 함량 제거)
    for type_param in ("di_custom_material_code", "dl_atc_code"):
        name = _fetch_search(idx, type_param)
        if name:
            return {"name": _strip_dosage(name), "via": type_param, "original": name}
    return None


def fetch_by_edi_code(code: str) -> dict | None:
    # 9자리 — 보험코드(1:1 정확) 우선, 실패 시 품목기준코드(여러 함량 결과 → 함량 제거)
    name = _fetch_search(code, "di_edi_code")
    if name:
        return {"name": name, "via": "edi", "original": name}
    name = _fetch_search(code, "di_item_seq")
    if name:
        return {"name": _strip_dosage(name), "via": "item_seq", "original": name}
    return None


def resolve_one(kw: str) -> tuple[str, dict | None]:
    if len(kw) == 9:
        return kw, fetch_by_edi_code(kw)
    if len(kw) == 6:
        return kw, fetch_by_idx(kw)
    return kw, None


def main():
    load_dotenv()

    # 기존 매핑 로드 (이어서 진행). 구 구조(value=str)는 무시하고 신규 진행.
    existing: dict[str, dict | None] = {}
    if MAPPING_FILE.exists():
        try:
            raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
            for k, v in raw.items():
                # 신구조(dict) 항목만 보존
                if isinstance(v, dict):
                    existing[k] = v
        except Exception:
            pass
        if existing:
            print(f"[load] 기존 신구조 매핑 {len(existing):,}개 보존")
        else:
            print("[load] 신구조 매핑 0개 (구 dict 파일은 폐기, 새로 매핑)")

    print("[load] Drive에서 검색 로그 다운로드 중…")
    df = data_loader.load_all()
    print(f"[load] 총 {len(df):,}행")

    # 6자리/9자리 숫자 키워드만 추출
    kws = df["keyword"].astype(str).str.strip().unique()
    target = [
        k for k in kws
        if re.fullmatch(r"\d+", k) and len(k) in (6, 9) and k not in existing
    ]
    print(f"[target] 신규 처리 대상: {len(target):,}개")

    if not target:
        print("매핑할 신규 키워드 없음. 종료.")
        return

    success = 0
    fail = 0
    t0 = time.time()
    results: dict[str, str | None] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(resolve_one, k): k for k in target}
        for i, fut in enumerate(as_completed(futures), 1):
            kw, name = fut.result()
            results[kw] = name
            if name:
                success += 1
            else:
                fail += 1
            if i % 50 == 0 or i == len(target):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                eta = (len(target) - i) / rate if rate else 0
                print(
                    f"[{i:>5}/{len(target)}] ok={success:,} fail={fail:,} "
                    f"({rate:.1f}/s, ETA {eta:.0f}s)"
                )
                # 중간 저장 (장시간 작업 안전 대비)
                merged = {**existing, **results}
                MAPPING_FILE.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

    merged = {**existing, **results}
    MAPPING_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n[done] 매핑 파일 저장: {MAPPING_FILE}")
    print(f"  총 {len(merged):,}개 (성공 {success:,}, 실패 {fail:,})")


if __name__ == "__main__":
    main()
