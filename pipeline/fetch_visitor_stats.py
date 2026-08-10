#!/usr/bin/env python3
"""국립공원 실측 탐방객 통계 CSV 를 내려받는다 — `train_crowd.py` 의 입력.

    python3 pipeline/fetch_visitor_stats.py
    python3 pipeline/fetch_visitor_stats.py --check   # 이미 받은 파일만 검사

원본: 공공데이터포털 「국립공원공단_국립공원 시간별 일별 탐방객 통계」(15107577)
      → `data/raw/seoraksan_visitors.csv`

**인증키가 필요 없다.** 오픈API 가 아니라 파일데이터인데, 이 데이터셋은 첨부파일
직링크가 로그인 없이 열린다(확인함 — HTTP 200, 2.4MB). 그래서 CI 가 받아올 수 있다.
같은 포털의 다른 파일데이터(전국등산로표준데이터·공원경계)는 세션이 필요해 사람이 받아야
하는 것과 다르다 — 파일데이터라고 다 같지 않다.

⚠️ 첨부파일 ID(`atchFileId`)는 데이터셋이 갱신되면 바뀐다. 그래서 상세 페이지를 먼저 긁어
   현재 링크를 찾고, 못 찾으면 마지막으로 확인된 ID 로 폴백한다.

⚠️ 제목에 '시간별'이 있지만 **시간 컬럼은 없고 설악산 한 곳**만 들어 있다.
   그래서 이걸로 학습하는 건 요일·월·공휴일 계수뿐이다(`train_crowd.py` 주석 참고).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "seoraksan_visitors.csv"

DATASET = "https://www.data.go.kr/data/15107577/fileData.do"
DOWNLOAD = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
FALLBACK_FILE_ID = "FILE_000000003643932"      # 2026-08-09 확인분

UA = {"User-Agent": "Mozilla/5.0 (monthly-mountains data pipeline)"}
TIMEOUT = 90

REQUIRED_COLUMNS = {"국립공원", "탐방지역", "일자", "전체 탐방객수"}
MIN_ROWS = 10_000       # 8년 × 23개 탐방지역이면 5만 행대. 크게 모자라면 원본이 바뀐 것이다.


def find_file_id() -> str:
    """상세 페이지에서 현재 첨부파일 ID 를 찾는다. 실패하면 마지막 확인분을 쓴다."""
    try:
        r = requests.get(DATASET, headers=UA, timeout=TIMEOUT)
        m = re.search(r"fileDownload\.do\?atchFileId=(FILE_\w+)", r.text)
        if m:
            if m.group(1) != FALLBACK_FILE_ID:
                print(f"  첨부파일 ID 가 바뀌었습니다: {m.group(1)} (기록된 값 {FALLBACK_FILE_ID})")
            return m.group(1)
        print("  ! 상세 페이지에서 링크를 못 찾아 마지막 확인분을 씁니다.", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"  ! 상세 페이지 조회 실패({exc}) — 마지막 확인분을 씁니다.", file=sys.stderr)
    return FALLBACK_FILE_ID


def download(file_id: str) -> bytes:
    r = requests.get(
        DOWNLOAD,
        params={"atchFileId": file_id, "fileDetailSn": 1, "insertDataPrcus": "N"},
        headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    # 로그인 페이지로 튕기면 HTML 이 온다 — CSV 인지 내용으로 확인한다.
    if b"<html" in r.content[:400].lower():
        sys.exit("CSV 가 아니라 HTML 이 왔습니다 — 링크가 바뀌었거나 로그인이 필요해졌습니다.")
    return r.content


def check(raw: bytes) -> tuple[int, str, str]:
    """행 수와 기간을 확인한다. 스키마가 바뀌면 여기서 멈춰야 train_crowd 가 헛돌지 않는다."""
    text = raw.decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        sys.exit("빈 CSV 입니다.")

    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        sys.exit(f"필수 컬럼 없음: {sorted(missing)}\n실제 컬럼: {list(rows[0])}")
    if len(rows) < MIN_ROWS:
        sys.exit(f"행이 {len(rows):,}개뿐입니다(최소 {MIN_ROWS:,}) — 원본이 잘렸는지 확인하세요.")

    dates = sorted(r["일자"] for r in rows if r.get("일자"))
    parks = {r["국립공원"] for r in rows}
    print(f"  {len(rows):,}행 · {dates[0]} ~ {dates[-1]} · 공원 {len(parks)}곳 {sorted(parks)[:3]}")
    return len(rows), dates[0], dates[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="내려받지 않고 기존 파일만 검사")
    args = ap.parse_args()

    if args.check:
        if not OUT.exists():
            sys.exit(f"{OUT} 가 없습니다.")
        print(f"기존 파일 검사 — {OUT.relative_to(ROOT)}")
        check(OUT.read_bytes())
        return 0

    print("국립공원 탐방객 통계 내려받기")
    raw = download(find_file_id())
    check(raw)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(raw)
    print(f"\n{OUT.relative_to(ROOT)} — {len(raw)/1024/1024:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
