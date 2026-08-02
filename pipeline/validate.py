#!/usr/bin/env python3
"""배포 산출물이 **앱의 Swift 디코더가 받아들이는 모양인지** 검사한다.

이게 필요한 이유: Swift `Codable` 은 필수 키가 없거나 타입이 다르면 디코딩 전체를 실패시킨다.
그러면 앱은 크래시하지 않고 **조용히 빈 화면**을 보여준다 — 사용자도 개발자도 원인을 모른다.
파이프라인이 JSON 을 만든 직후 여기서 걸러, 깨진 데이터가 Pages 로 나가지 않게 한다.

    python3 pipeline/validate.py data/v1/mountains.json
    python3 pipeline/validate.py data/v1/crowd_model.json
    python3 pipeline/validate.py data/v1/            # 디렉터리면 아는 파일 전부

앱 모델과 어긋나면 여기 스펙을 고치는 게 아니라 **둘 중 뭐가 맞는지 정하고 양쪽을 맞춘다.**
출처: monthly-mountains/MonthlyMountains/Model/{Mountain,CrowdModel}.swift
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Swift 의 non-optional 프로퍼티 = 필수. Optional(`?`) = 있으면 타입만 맞으면 된다.
PARK_TYPES = {"national", "provincial", "county", "none"}
SPECIES_KINDS = {"mammal", "bird", "plant", "insect", "amphibian", "fish"}

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def need(obj: dict, where: str, key: str, types: type | tuple[type, ...]) -> object | None:
    """필수 키 — 없거나 타입이 다르면 Swift 가 디코딩에 실패한다."""
    if key not in obj or obj[key] is None:
        err(f"{where}: 필수 키 '{key}' 없음")
        return None
    if not isinstance(obj[key], types):
        err(f"{where}: '{key}' 타입 {type(obj[key]).__name__} (기대 {types})")
        return None
    return obj[key]


def opt(obj: dict, where: str, key: str, types: type | tuple[type, ...]) -> None:
    """Optional 키 — 없어도 되지만 있으면 타입이 맞아야 한다."""
    if obj.get(key) is not None and not isinstance(obj[key], types):
        err(f"{where}: '{key}' 타입 {type(obj[key]).__name__} (기대 {types}, Optional)")


def validate_mountains(d: dict) -> None:
    need(d, "root", "schemaVersion", int)
    need(d, "root", "generatedAt", str)
    need(d, "root", "seed", bool)
    ms = need(d, "root", "mountains", list)
    if not ms:
        return
    if len(ms) < 10:
        err(f"root: 산이 {len(ms)}개뿐 — 마스터가 덜 채워졌을 가능성")

    seen_ids: set[str] = set()
    for m in ms:
        mid = m.get("id", "?")
        w = f"mountains[{mid}]"
        if mid in seen_ids:
            err(f"{w}: id 중복")
        seen_ids.add(mid)

        for k, t in [("id", str), ("name", str), ("tagline", str), ("region", str),
                     ("sigungu", str), ("lat", (int, float)), ("lon", (int, float)),
                     ("elevation", int), ("isTop100", bool), ("difficulty", int),
                     ("airRegion", str)]:
            need(m, w, k, t)
        for k, t in [("story", str), ("parkName", str), ("kmaMountainCode", str),
                     ("photoURL", str), ("photoCredit", str)]:
            opt(m, w, k, t)

        pt = need(m, w, "parkType", str)
        if pt is not None and pt not in PARK_TYPES:
            err(f"{w}: parkType '{pt}' 는 앱 enum 에 없음 {sorted(PARK_TYPES)}")

        diff = m.get("difficulty")
        if isinstance(diff, int) and not 1 <= diff <= 5:
            err(f"{w}: difficulty {diff} — 1~5 여야 한다")

        lat, lon = m.get("lat"), m.get("lon")
        if isinstance(lat, (int, float)) and not 33 <= lat <= 39:
            err(f"{w}: lat {lat} 이 한반도 범위(33~39) 밖")
        if isinstance(lon, (int, float)) and not 124 <= lon <= 132:
            err(f"{w}: lon {lon} 이 한반도 범위(124~132) 밖")

        grid = need(m, w, "grid", dict)
        if isinstance(grid, dict):
            need(grid, f"{w}.grid", "nx", int)
            need(grid, f"{w}.grid", "ny", int)

        for peak in need(m, w, "peaks", list) or []:
            need(peak, f"{w}.peaks", "name", str)
            need(peak, f"{w}.peaks", "elevation", int)

        for c in need(m, w, "courses", list) or []:
            cw = f"{w}.courses[{c.get('name','?')}]"
            need(c, cw, "name", str)
            need(c, cw, "distanceKm", (int, float))
            need(c, cw, "durationMin", int)
            need(c, cw, "difficulty", int)
            opt(c, cw, "ascentM", int)

        for s in need(m, w, "species", list) or []:
            sw = f"{w}.species[{s.get('name','?')}]"
            need(s, sw, "name", str)
            need(s, sw, "flagship", bool)
            opt(s, sw, "badge", str)
            kind = need(s, sw, "kind", str)
            if kind is not None and kind not in SPECIES_KINDS:
                err(f"{sw}: kind '{kind}' 는 앱 enum 에 없음 {sorted(SPECIES_KINDS)}")

        for t in need(m, w, "trailheads", list) or []:
            tw = f"{w}.trailheads[{t.get('name','?')}]"
            need(t, tw, "name", str)
            need(t, tw, "lat", (int, float))
            need(t, tw, "lon", (int, float))
            opt(t, tw, "transit", str)
            opt(t, tw, "parking", str)


def validate_crowd_model(d: dict) -> None:
    need(d, "root", "schemaVersion", int)
    need(d, "root", "generatedAt", str)
    need(d, "root", "holidayFactor", (int, float))
    need(d, "root", "factorExponent", (int, float))
    need(d, "root", "holidays", list)
    opt(d, "root", "trainedThrough", str)

    dow = need(d, "root", "dowFactors", list)
    if isinstance(dow, list) and len(dow) != 7:
        err(f"root: dowFactors 가 {len(dow)}개 — 요일 계수는 7개여야 한다")

    curves = need(d, "root", "hourCurves", dict) or {}
    for k, v in curves.items():
        if not isinstance(v, list) or len(v) != 24:
            err(f"hourCurves['{k}']: {len(v) if isinstance(v, list) else '리스트 아님'} — 24시간이어야 한다")

    profiles = need(d, "root", "monthProfiles", dict) or {}
    for k, v in profiles.items():
        if not isinstance(v, list) or len(v) != 12:
            err(f"monthProfiles['{k}']: {len(v) if isinstance(v, list) else '리스트 아님'} — 12개월이어야 한다")

    need(d, "root", "weather", dict)

    # 산별 파라미터가 참조하는 곡선·프로필이 실제로 있는지 — 앱은 여기서 조용히 실패한다.
    for mid, p in (need(d, "root", "mountains", dict) or {}).items():
        w = f"mountains['{mid}']"
        need(p, w, "baseIndex", (int, float))
        hc = need(p, w, "hourCurve", str)
        mp = need(p, w, "monthProfile", str)
        if hc is not None and hc not in curves:
            err(f"{w}: hourCurve '{hc}' 가 hourCurves 에 없음")
        if mp is not None and mp not in profiles:
            err(f"{w}: monthProfile '{mp}' 가 monthProfiles 에 없음")

    v = d.get("validation")
    if isinstance(v, dict):
        need(v, "validation", "mape", (int, float))
        need(v, "validation", "holdoutParks", list)


VALIDATORS = {"mountains.json": validate_mountains, "crowd_model.json": validate_crowd_model}


def run(path: Path) -> None:
    fn = VALIDATORS.get(path.name)
    if fn is None:
        print(f"  · {path.name}: 검사기 없음 — 건너뜀")
        return
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"{path.name}: JSON 파싱 실패 — {e}")
        return
    before = len(errors)
    fn(d)
    n = len(errors) - before
    print(f"  {'✗' if n else '✓'} {path.name}: {n}건" if n else f"  ✓ {path.name}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    targets: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            targets += sorted(x for x in p.glob("*.json") if x.name in VALIDATORS)
        else:
            targets.append(p)
    if not targets:
        print("검사할 파일이 없습니다", file=sys.stderr)
        return 2

    print(f"스키마 검사 — 앱 Swift 디코더 계약 기준 ({len(targets)}개 파일)")
    for t in targets:
        run(t)

    if errors:
        print(f"\n✗ {len(errors)}건 — 이대로 배포하면 앱이 빈 화면을 보여줍니다:")
        for e in errors[:30]:
            print("   -", e)
        if len(errors) > 30:
            print(f"   … 외 {len(errors) - 30}건")
        return 1
    print("\n✓ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
