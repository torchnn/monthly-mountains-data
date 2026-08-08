#!/usr/bin/env python3
"""전국등산로표준데이터 → `pipeline/trails.json` (산별 코스·들머리 요약).

**로컬에서 한 번만 돌리고 결과를 커밋한다.** 원본(mountain.zip, 265MB)은 다운로드에
로그인이 필요해 CI 가 받아올 수 없고, 그대로 커밋하기엔 너무 크다. 여기서 앱이 쓰는
모양(코스명·거리·소요시간·난이도·들머리 좌표)만 남긴 2MB 남짓의 JSON 으로 줄인다.

    # 원본 배치 (data/raw/ 는 gitignore 대상)
    unzip mountain.zip -d data/raw/trails      # → data/raw/trails/mountain/*.zip

    python3 pipeline/build_trail_index.py

⚠️ **누적상승고도(`ascentM`)는 이 원본으로 채울 수 없다.**
   GPX 에 `<ele>` 가 있지만 값이 전부 0 이다(표본 40개 산 263,509개 트랙포인트 전수 0).
   SHP/esri json 쪽에도 고도 필드가 없다. 앱 모델의 `Course.ascentM` 이 옵셔널이라
   화면은 깨지지 않는다 — 별도 DEM(수치표고모델)을 붙이기 전까지는 null 로 둔다.

원본 구조: 산 하나에 아카이브 3개(`<코드>.zip` SHP · `_geojson.zip` esri json · `_gpx.zip`).
여기서는 속성이 온전한 `_geojson.zip` 만 읽는다. 좌표계는 EPSG:5186(중부원점 2010)이라
`geo.to_wgs84` 로 바꾼다(GPX 정답 대비 오차 0.01cm 검증 — `python3 pipeline/geo.py`).
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from geo import KOREA_CENTRAL, haversine_m, to_wgs84

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "trails" / "mountain"
OUT = ROOT / "pipeline" / "trails.json"

PRECISION = 5   # 약 1.1m

# 원본 난이도 → 앱 difficulty(1 매우 쉬움 ~ 5 매우 어려움).
# 원본은 3단계뿐이고 실제로 98%가 '쉬움'이라, 양 끝(1·5)은 비워 두고 가운데에 눕힌다.
DIFFICULTY = {"쉬움": 2, "중간": 3, "보통": 3, "어려움": 4}

# 들머리로 쓸 지점 종류. '정상'은 별도로 뽑아 산 대표 좌표에 쓴다.
TRAILHEAD_KINDS = {"시종점"}


def members(path: Path) -> dict[str, bytes]:
    """zip 내부 이름이 CP949 라 그대로 읽으면 깨진다."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            try:
                name = info.filename.encode("cp437").decode("cp949")
            except Exception:  # noqa: BLE001 — 추정 실패 시 원본 이름 유지
                name = info.filename
            out[name] = z.read(info)
    return out


def _wgs(x, y) -> tuple[float, float] | None:
    """투영좌표 → (위도, 경도). 좌표가 숫자가 아니거나 한반도 밖이면 None.

    원본에 x·y 가 문자열이거나 비어 있는 레코드가 섞여 있다(2,933개 중 소수).
    한 건 때문에 전체 빌드가 죽지 않도록 여기서 걸러낸다.
    """
    try:
        lat, lon = to_wgs84(float(x), float(y), KOREA_CENTRAL)
    except (TypeError, ValueError):
        return None
    if not (32.0 <= lat <= 39.5 and 124.0 <= lon <= 132.0):
        return None
    return round(lat, PRECISION), round(lon, PRECISION)


def parse_mountain(archive: Path) -> dict | None:
    """아카이브 하나(= 산 하나) → 요약 딕셔너리."""
    try:
        files = members(archive)
    except zipfile.BadZipFile:
        print(f"  ! 깨진 아카이브: {archive.name}", file=sys.stderr)
        return None

    line_raw = next((v for k, v in files.items() if k.endswith(".json") and "SPOT" not in k), None)
    spot_raw = next((v for k, v in files.items() if k.endswith(".json") and "SPOT" in k), None)
    if not line_raw:
        return None

    line = json.loads(line_raw.decode("utf-8", "replace"))
    feats = line.get("features", [])
    if not feats:
        return None

    code = str(feats[0]["attributes"].get("MNTN_CODE") or "").strip()
    name = str(feats[0]["attributes"].get("MNTN_NM") or "").strip()
    if not code:
        return None

    # ── 구간을 이름으로 묶어 코스로 만든다 ──────────────────────────────
    groups: dict[str, dict] = defaultdict(lambda: {"km": 0.0, "min": 0, "diff": []})
    unnamed = {"km": 0.0, "min": 0}
    for f in feats:
        a = f["attributes"]
        km = float(a.get("PMNTN_LT") or 0)
        # PMNTN_UPPL = 상행 소요시간(분), PMNTN_GODN = 하행. 등산 시간이므로 상행을 쓴다.
        minutes = int(a.get("PMNTN_UPPL") or 0)
        label = str(a.get("PMNTN_NM") or "").strip()
        if not label:
            unnamed["km"] += km
            unnamed["min"] += minutes
            continue
        g = groups[label]
        g["km"] += km
        g["min"] += minutes
        d = DIFFICULTY.get(str(a.get("PMNTN_DFFL") or "").strip())
        if d:
            g["diff"].append(d)

    courses = [
        {
            "name": label,
            "distanceKm": round(g["km"], 2),
            "durationMin": g["min"],
            # 한 코스 안에서 가장 어려운 구간이 그 코스의 체감 난이도를 정한다.
            "difficulty": max(g["diff"]) if g["diff"] else None,
            "ascentM": None,   # 원본에 고도가 없다 — 파일 상단 주석 참고
        }
        for label, g in groups.items()
        if g["km"] > 0
    ]
    courses.sort(key=lambda c: -c["distanceKm"])

    # ── 지점 레이어에서 들머리와 정상 ────────────────────────────────
    trailheads, summit = [], None
    if spot_raw:
        seen = set()
        for f in json.loads(spot_raw.decode("utf-8", "replace")).get("features", []):
            a, g = f["attributes"], f["geometry"]
            if "x" not in g:
                continue
            kind = str(a.get("MANAGE_SP2") or "").strip()
            point = _wgs(g["x"], g["y"])
            if point is None:
                continue
            lat, lon = point
            if kind == "정상" and summit is None:
                summit = [lat, lon]
            if kind in TRAILHEAD_KINDS:
                key = (lat, lon)
                if key in seen:
                    continue
                seen.add(key)
                trailheads.append({"label": str(a.get("DETAIL_SPO") or kind).strip(), "lat": lat, "lon": lon})

    # 대표 좌표: 정상 > 들머리 평균 > 첫 구간 시작점
    if summit:
        lat, lon = summit
    elif trailheads:
        lat = round(sum(t["lat"] for t in trailheads) / len(trailheads), PRECISION)
        lon = round(sum(t["lon"] for t in trailheads) / len(trailheads), PRECISION)
    else:
        point = None
        for f in feats:                       # 첫 구간의 좌표가 깨져 있을 수 있다
            path = f["geometry"].get("paths") or []
            if path and path[0]:
                point = _wgs(path[0][0][0], path[0][0][1])
                if point:
                    break
        if point is None:
            return None
        lat, lon = point

    return {
        "code": code,
        "name": name,
        "lat": lat,
        "lon": lon,
        "summit": bool(summit),
        "segments": len(feats),
        "totalKm": round(sum(c["distanceKm"] for c in courses) + unnamed["km"], 2),
        "totalMin": sum(c["durationMin"] for c in courses) + unnamed["min"],
        # 이름 없는 구간이 35% 라 코스 목록에는 못 넣지만 총계에서 빼면 거리가 줄어 보인다.
        "unnamedKm": round(unnamed["km"], 2),
        "courses": courses,
        "trailheads": trailheads,
    }


def build(limit: int | None = None) -> dict:
    if not SRC.exists():
        sys.exit(f"원본 없음: {SRC}\nmountain.zip 을 data/raw/trails 로 풀어 두세요.")

    archives = sorted(SRC.glob("*_geojson.zip"))
    if limit:
        archives = archives[:limit]
    if not archives:
        sys.exit(f"{SRC} 에 *_geojson.zip 이 없습니다.")

    mountains, skipped = [], 0
    for i, arc in enumerate(archives, 1):
        m = parse_mountain(arc)
        if m:
            mountains.append(m)
        else:
            skipped += 1
        if i % 500 == 0:
            print(f"  {i}/{len(archives)} …", flush=True)

    mountains.sort(key=lambda m: -m["totalKm"])
    return {
        "source": "산림청_전국등산로표준데이터 (공공누리 1유형)",
        "note": "ascentM 은 원본에 고도가 없어 전부 null. DEM 을 붙이기 전까지 채울 수 없다.",
        "crs": "WGS84",
        "skipped": skipped,
        "mountains": mountains,
    }


def find_for(name: str, lat: float, lon: float, index: dict, max_km: float = 15.0) -> dict | None:
    """앱의 산 하나에 대응하는 등산로 항목을 고른다. `build_mountains.py` 가 쓴다.

    ⚠️ **이름만으로 맞추면 안 된다.** 원본에는 동명이산이 그대로 들어 있다 —
       '계룡산' 은 시드 좌표에서 207km, '무등산' 은 254km, '가야산' 은 103·159·167km
       떨어진 항목이 각각 존재한다. 이름만 보면 전부 오매칭된다.

    ⚠️ **가장 긴 것을 고르면 안 된다.** 덕유산 주변에는 '덕유산_향적봉'(1.4km, 5.7km)과
       '남덕유산'(13.2km, 22.1km)이 있는데, 길이로 고르면 남덕유산이 잡힌다.

    ⚠️ **가장 가까운 것만 골라도 안 된다.** 관악산에는 '관악산'(2.2km, 43.7km)과
       '관악산학바위능선'(1.0km, 11.4km)이 있어, 거리만 보면 능선 하나가 산 전체를 대신한다.

    → 규칙: 봉우리 접미사를 뗀 이름이 **정확히 같은 것**을 먼저 찾고, 그중 가장 가까운 것.
      정확히 같은 게 없을 때만 느슨한 포함 매칭으로 내려간다.
      (원본 이름은 '북한산_백운대'처럼 봉우리가 붙어 있어 완전일치는 기대할 수 없다.)
    """
    def within(pred) -> list[tuple[float, dict]]:
        out = []
        for t in index["mountains"]:
            if not pred(t["name"]):
                continue
            d = haversine_m(lat, lon, t["lat"], t["lon"])
            if d <= max_km * 1000:
                out.append((d, t))
        return out

    exact = within(lambda n: n.split("_")[0] == name)
    loose = exact or within(lambda n: name in n or n.split("_")[0] in name)
    if not loose:
        return None
    return min(loose, key=lambda p: p[0])[1]


def report_match(index: dict) -> int:
    """앱 시드 24개 산이 실제로 몇 개나 붙는지 본다."""
    seed = json.loads((ROOT / "data" / "v1" / "mountains.json").read_text())["mountains"]
    hit = 0
    print(f"{'산':<8}{'등산로 항목':<18}{'거리':>8}{'코스':>5}{'들머리':>7}{'총km':>9}")
    for m in seed:
        t = find_for(m["name"], m["lat"], m["lon"], index)
        if not t:
            print(f"{m['name']:<8}{'— 원본에 없음':<18}")
            continue
        hit += 1
        d = haversine_m(m["lat"], m["lon"], t["lat"], t["lon"]) / 1000
        print(f"{m['name']:<8}{t['name']:<18}{d:>7.1f}km{len(t['courses']):>5}{len(t['trailheads']):>7}{t['totalKm']:>9.1f}")
    print(f"\n시드 {len(seed)}개 중 {hit}개 매칭 ({hit/len(seed):.0%})")
    return 0


def summarize(index: dict) -> None:
    ms = index["mountains"]
    with_course = [m for m in ms if m["courses"]]
    with_th = [m for m in ms if m["trailheads"]]
    with_summit = [m for m in ms if m["summit"]]
    print(f"\n산 {len(ms):,}개 (건너뜀 {index['skipped']})")
    print(f"  코스 있음   {len(with_course):,} ({len(with_course)/len(ms):.0%})")
    print(f"  들머리 있음 {len(with_th):,} ({len(with_th)/len(ms):.0%})")
    print(f"  정상 지점   {len(with_summit):,} ({len(with_summit)/len(ms):.0%})")
    print(f"  총 등산로   {sum(m['totalKm'] for m in ms):,.0f} km · 코스 {sum(len(m['courses']) for m in ms):,}개")
    print("\n등산로가 긴 산 10개:")
    for m in ms[:10]:
        print(f"  {m['name']:<12} {m['totalKm']:>7.1f}km  코스 {len(m['courses']):>2}개  들머리 {len(m['trailheads']):>2}개")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="앞에서 N개 산만 (시험용)")
    ap.add_argument("--dry-run", action="store_true", help="요약만 출력하고 파일은 쓰지 않는다")
    ap.add_argument("--match", action="store_true", help="이미 만든 trails.json 으로 시드 매칭률만 확인")
    args = ap.parse_args()

    if args.match:
        if not OUT.exists():
            sys.exit(f"{OUT} 가 없습니다 — 먼저 인자 없이 한 번 돌리세요.")
        return report_match(json.loads(OUT.read_text()))

    index = build(args.limit)
    summarize(index)
    if args.dry_run:
        return 0

    OUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    print(f"\n{OUT.relative_to(ROOT)} — {OUT.stat().st_size/1024/1024:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
