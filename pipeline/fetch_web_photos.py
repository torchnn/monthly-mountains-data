#!/usr/bin/env python3
"""사진이 없는 산의 대표 이미지를 웹에서 한 장씩 받아 온다.

    python3 pipeline/fetch_web_photos.py            # 사진 없는 산 전부
    python3 pipeline/fetch_web_photos.py --limit 5  # 시험
    python3 pipeline/fetch_web_photos.py --review   # 받은 것 목록만 출력

⚠️ **저작권은 자동으로 해결되지 않는다.** 여기서 받는 이미지는 제3자 저작물이고,
   관광공사(공공누리 1유형)와 달리 재배포 권리가 보장되지 않는다.
   그래서 출처 페이지·제목·크기를 `pipeline/web_photos.json` 에 전부 남긴다 —
   **출시 전에 사람이 이 목록을 훑어 판단해야 한다.** `--review` 가 그 목록을 뽑아 준다.

왜 이 경로인가: 관광공사는 `firstimage` 도 `detailImage2` 도 없는 산이 130개고,
호출을 몰아 하면 HTTP 429 로 막힌다. 위키미디어 Commons·Openverse 는 국내 무명 산 수율이
2~4% 로 사실상 없다. 구글 이미지는 결과가 JS 로 렌더링돼 스크립트로 못 읽는다.
DuckDuckGo 는 같은 웹 이미지를 색인하면서 JSON 으로 돌려주므로 이걸 쓴다.

**산당 질의는 한 번뿐이다.** 여러 번 시도해 억지로 채우면 엉뚱한 사진이 붙는다.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "v1" / "mountains.json"
PHOTO_DIR = ROOT / "data" / "v1" / "photos"
LEDGER = ROOT / "pipeline" / "web_photos.json"

PAGES_BASE = "https://torchnn.github.io/monthly-mountains-data/data/v1/photos"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# 산 사진이 아닌 것들. 등산 질의는 **등산지도**가 먼저 오므로 반드시 걸러야 한다.
REJECT = re.compile(r"지도|코스|안내도|등산로|주차|맛집|숙박|펜션|호텔|리조트|"
                    r"map|thumb|썸네일|로고|logo|현수막|포스터", re.I)

MIN_WIDTH = 800          # 상세 화면 히어로에 쓰려면 이 정도는 돼야 한다
MAX_EDGE = 1400          # 저장할 때 긴 변 상한 — 레포가 커지는 걸 막는다
JPEG_QUALITY = 82


def ddg_images(session: requests.Session, query: str) -> list[dict]:
    """DuckDuckGo 이미지 검색. 토큰(vqd)을 먼저 받아야 JSON 엔드포인트가 열린다."""
    try:
        first = session.post("https://duckduckgo.com/", data={"q": query}, timeout=25)
        token = re.search(r'vqd=["\']?([\d-]+)', first.text)
        if not token:
            return []
        res = session.get(
            "https://duckduckgo.com/i.js",
            params={"l": "kr-kr", "o": "json", "q": query, "vqd": token.group(1),
                    "f": ",,,", "p": "1"},
            headers={"Referer": "https://duckduckgo.com/"}, timeout=25,
        )
        return res.json().get("results", [])
    except Exception as exc:  # noqa: BLE001 — 한 산이 실패해도 전체를 멈추지 않는다
        print(f"    ! 검색 실패: {exc}", file=sys.stderr)
        return []


def pick(results: list[dict], name: str) -> dict | None:
    """가장 그럴듯한 한 장. **제목에 산 이름이 있는 것**을 크게 우대한다."""
    best, best_score = None, 0.0
    for r in results:
        title = r.get("title") or ""
        if REJECT.search(title):
            continue
        try:
            width, height = int(r.get("width") or 0), int(r.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if width < MIN_WIDTH or height <= 0:
            continue
        if "ytimg.com" in (r.get("image") or ""):     # 유튜브 썸네일은 산 사진이 아니다
            continue

        score = 1.0
        if name in title:
            score += 3.0
        if 1.2 <= width / height <= 2.2:             # 가로로 긴 풍경 비율을 선호
            score += 1.0
        if width >= 1200:
            score += 0.5
        if score > best_score:
            best, best_score = r, score
    return best


def download(session: requests.Session, url: str) -> bytes | None:
    """받아서 긴 변 1400px JPEG 로 줄인다. 원본 그대로면 레포가 수십 MB 늘어난다."""
    try:
        res = session.get(url, timeout=30, headers={"Referer": "https://duckduckgo.com/"})
        res.raise_for_status()
        image = Image.open(io.BytesIO(res.content))
        image = image.convert("RGB")
        if max(image.size) > MAX_EDGE:
            ratio = MAX_EDGE / max(image.size)
            image = image.resize((round(image.width * ratio), round(image.height * ratio)),
                                 Image.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        print(f"    ! 내려받기 실패: {exc}", file=sys.stderr)
        return None


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {"note": "", "photos": {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--review", action="store_true", help="받은 목록만 출력(저작권 검토용)")
    ap.add_argument("--apply-only", action="store_true",
                    help="검색·내려받기 없이 대장을 마스터에 반영만 한다"
                         " (마스터가 다른 빌드로 덮인 뒤 복구용)")
    args = ap.parse_args()

    ledger = load_ledger()
    if args.review:
        rows = ledger.get("photos", {})
        print(f"웹에서 받은 사진 {len(rows)}장 — 출시 전 저작권 검토 대상\n")
        for mid, meta in sorted(rows.items()):
            print(f"  {meta['name']:<12} {meta['title'][:38]:<40} {meta['source']}")
        return 0

    catalog = json.loads(MASTER.read_text())
    missing = [m for m in catalog["mountains"] if not m["photoURL"]]
    if args.limit:
        missing = missing[: args.limit]
    if not missing:
        print("사진 없는 산이 없습니다.")
        return 0

    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(UA)

    filled = 0
    if args.apply_only:
        missing = []          # 네트워크를 타지 않고 아래 반영 단계로 바로 간다
    for i, mountain in enumerate(missing, 1):
        name = mountain["name"].split("(")[0]
        if mountain["id"] in ledger["photos"]:
            continue
        print(f"  [{i}/{len(missing)}] {name}")
        chosen = pick(ddg_images(session, f"{name} 풍경"), name)   # 질의는 한 번뿐
        if not chosen:
            time.sleep(1.0)
            continue
        blob = download(session, chosen["image"])
        if not blob:
            time.sleep(1.0)
            continue

        (PHOTO_DIR / f"{mountain['id']}.jpg").write_bytes(blob)
        ledger["photos"][mountain["id"]] = {
            "name": name,
            "title": chosen.get("title", ""),
            "source": chosen.get("url", ""),      # 이미지가 실린 페이지
            "image": chosen.get("image", ""),
            "size": f"{chosen.get('width')}x{chosen.get('height')}",
            "bytes": len(blob),
        }
        filled += 1
        print(f"      ✅ {chosen.get('title','')[:40]} ({len(blob)//1024}KB)")
        time.sleep(1.0)                            # 예의상 간격

    ledger["note"] = ("웹에서 받은 제3자 저작물이다. 공공누리가 아니므로 "
                      "출시 전 사람이 출처를 확인해야 한다. `--review` 로 목록을 뽑는다.")
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1))

    # 마스터에 반영 — 앱은 Pages 로 서빙되는 이 경로를 읽는다.
    for m in catalog["mountains"]:
        meta = ledger["photos"].get(m["id"])
        if meta and not m["photoURL"]:
            m["photoURL"] = f"{PAGES_BASE}/{m['id']}.jpg"
            m["photoCredit"] = f"출처: {meta['source']}"
    MASTER.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")

    total = sum(1 for m in catalog["mountains"] if m["photoURL"])
    print(f"\n새로 채운 사진 {filled}장 · 마스터 사진 보유 {total}/{len(catalog['mountains'])}")
    print(f"저작권 검토 목록: python3 pipeline/fetch_web_photos.py --review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
