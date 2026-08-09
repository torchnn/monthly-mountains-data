#!/usr/bin/env python3
"""`crowd_model.json` 의 산별 파라미터를 마스터 전체(300개)로 넓힌다.

    python3 pipeline/build_crowd_params.py            # crowd_model.json 갱신
    python3 pipeline/build_crowd_params.py --dry-run  # 적합도·분포만 보고 쓰지 않는다

**왜 필요한가.** 혼잡도 파라미터는 앱 레포 `make_seed.py` 가 손으로 적은 24개뿐이다.
산을 300개로 늘리면 나머지 276개는 앱에서 `CrowdModel.Params.fallback` 으로 떨어져
**baseIndex 45 · monthProfile "default" 로 전부 같아진다.** 날씨 말고는 차이가 없어
혼잡도 정렬과 '이달의 추천'이 92%의 산에서 무의미해진다 — 이 앱의 차별점이 그 기능이다.

**회귀는 실패했다 — 순위로 간다.** 처음엔 손입력 24개를 정답 삼아 대리지표로 `baseIndex` 를
회귀 적합했다. 결과는 **R² 0.17, 276개 예측의 사분위폭 1.0** — 사실상 상수를 예측했다.
그러면 폴백(45)이 26으로 바뀔 뿐 "276개가 전부 같다"는 문제가 그대로다.

원인은 분명하다. 손입력 24개는 사람이 **유명세**로 매긴 값인데, 마스터에서 얻을 수 있는
지표로는 유명세가 안 잡힌다. 접근성은 오히려 음의 상관(-0.079)이었다 —
설악산·지리산은 도시에서 멀지만 가장 붐비기 때문이다.

그래서 절대값을 맞추려는 시도를 접고 **순위**를 만든다. 사용자가 실제로 쓰는 정보는
"이 산이 저 산보다 한산한가"이고, 순서에는 아래 지표들의 신호가 남아 있다.
  · 100대명산  산림청 선정 — 목적지로서의 인지도 (상관 +0.24)
  · 국립공원   탐방 인프라와 홍보 (+0.28)
  · 표고      단일 지표로는 가장 강했다 (+0.41)
  · 등산로 총연장 수용 규모 (+0.20)
  · 접근성     인구 가중 도시 근접도 — 무명 산끼리는 이게 갈린다

합성 점수의 백분위를 `baseIndex` 구간에 늘어놓는다. **절대값이 아니라 서열이 산출물**이고,
그래서 전부 `confidence: "low"` 로 표시해 앱이 추정치임을 밝힌다.

⚠️ **손입력 24개의 값은 건드리지 않는다.** 실측(설악산 일별 탐방객)과 데이터랩 검색량으로
   얻은 값이라 추정치로 덮으면 손해다.

⚠️ **제대로 된 해법은 따로 있다.** 데이터랩 검색량을 300개 산으로 넓혀 수집하면
   (지금은 signals 레포가 24개만 수집한다) 실측 기반 곡선과 기저값을 그대로 얻는다.
   여기 것은 그때까지의 잠정치다.

⚠️ `factorExponent` 를 바꾸면 24개의 표시 단계까지 흔들린다. 여기서는 바꾸지 않고,
   300개 기준 5단계 분포가 여전히 고른지 **확인만** 한다(쏠리면 경고).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from build_trail_index import find_for
from geo import haversine_m

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
MOUNTAINS = ROOT / "data" / "v1" / "mountains.json"
MODEL = ROOT / "data" / "v1" / "crowd_model.json"

# 인구 가중 접근성용 도시 중심 (2026 주민등록 인구 근사, 백만 명).
# 정확한 인구가 목적이 아니라 '사람이 많은 곳에서 가까운가'의 순서가 목적이다.
CITIES = [
    (37.5665, 126.9780, 9.4),   # 서울
    (37.4563, 126.7052, 3.0),   # 인천
    (37.2636, 127.0286, 1.2),   # 수원
    (35.1796, 129.0756, 3.3),   # 부산
    (35.8714, 128.6014, 2.4),   # 대구
    (36.3504, 127.3845, 1.45),  # 대전
    (35.1595, 126.8526, 1.4),   # 광주
    (35.5384, 129.3114, 1.1),   # 울산
    (35.2280, 128.6811, 1.0),   # 창원
    (36.8000, 127.0740, 0.9),   # 천안
    (37.8813, 127.7298, 0.3),   # 춘천
    (35.8242, 127.1480, 0.65),  # 전주
    (33.4996, 126.5312, 0.49),  # 제주
]

# 5단계 경계 — 앱 `CrowdEngine` 과 같아야 한다.
LEVELS = [(20, "한산"), (40, "여유"), (60, "보통"), (80, "붐빔"), (101, "매우 붐빔")]


def accessibility(lat: float, lon: float) -> float:
    """인구 가중 근접도. 거리에 20km 를 더해 도시 바로 옆에서 값이 발산하지 않게 한다."""
    return sum(pop / (haversine_m(lat, lon, clat, clon) / 1000 + 20) for clat, clon, pop in CITIES)


# 합성 점수의 가중치. 손입력 24개에 대한 상관계수의 크기 순서를 따르되,
# 접근성만은 상관(-0.079)이 아니라 도메인 논리로 양수를 준다 —
# 24개가 전부 유명산이라 '멀어도 붐빈다'가 관측된 것이고,
# 무명 산끼리는 서울에서 가까운 쪽이 실제로 더 붐빈다.
WEIGHTS = {"top100": 0.30, "national": 0.20, "elevation": 0.15, "trail": 0.15, "access": 0.20}

# 추정 산이 놓일 baseIndex 구간.
#
# 위쪽 끝이 **손입력 최솟값(마니산 20.6) 언저리를 넘지 않아야 한다.** 처음엔 33 까지 줬는데,
# 그러면 앱의 '이달의 추천'이 무명 산으로 뒤덮인다 — 추천 점수가
# 계절 × 한산함 × 이름값(baseIndex)인데, 추정 33 짜리 산은 이름값에서 지리산(37.7)에 거의
# 안 밀리면서 한산함에서 크게 앞서기 때문이다. 실제로 첫 화면 추천이 석병산·수리봉이었다.
# 우리는 276개 중 어느 하나가 북한산만큼 알려졌다고 말할 근거가 없다.
EST_MIN, EST_MAX = 8.0, 22.0


def raw_score(m: dict, total_km: float) -> float:
    """0~1 로 정규화한 지표들의 가중합. 절대 혼잡도가 아니라 **서열용 점수**다."""
    elev = max(0.0, min(1.0, (m["elevation"] - 200) / 1400))
    trail = min(1.0, math.log1p(total_km) / math.log1p(200))
    acc = min(1.0, accessibility(m["lat"], m["lon"]) / 0.35)
    return (
        WEIGHTS["top100"] * (1.0 if m["isTop100"] else 0.0)
        + WEIGHTS["national"] * (1.0 if m["parkType"] == "national" else 0.0)
        + WEIGHTS["elevation"] * elev
        + WEIGHTS["trail"] * trail
        + WEIGHTS["access"] * acc
    )


def month_profile_for(m: dict, access: float) -> str:
    """유형 프로필 배정. 산별 실측 곡선이 있는 24개는 여기 오지 않는다."""
    if access > 0.20 and m["elevation"] < 800:
        return "urban"          # 도심 근교라 계절 진폭이 작다
    if m["parkType"] == "national" or m["elevation"] >= 1000:
        return "autumnLeaf"     # 단풍 성수기가 뚜렷한 쪽
    return "default"


def hour_curve_for(m: dict, access: float) -> str:
    return "urban" if (access > 0.20 and m["elevation"] < 800) else "alpine"


def duration_for(m: dict) -> int:
    """대표 소요시간(분, 왕복). 코스가 있으면 대표 코스의 왕복, 없으면 표고로 어림한다."""
    mins = [c["durationMin"] for c in m["courses"] if c["durationMin"] > 0]
    if mins:
        mid = sorted(mins)[len(mins) // 2]
        return max(60, min(540, int(round(mid * 2 / 15)) * 15))
    return max(60, min(540, int(round((90 + m["elevation"] / 4) / 15)) * 15))


def level(index: float) -> str:
    return next(label for bound, label in LEVELS if index < bound)


# 검색량 → 실제 방문의 진폭 감쇠. 설악산이 검색·실측을 둘 다 갖고 있어 **측정**한 값이다
# (10월 검색 3.44 vs 실측 2.74). 앱 레포 make_seed.py 와 같은 값이어야 한다.
SEARCH_TO_VISIT = 0.689


def _search_popularity() -> dict[str, float]:
    """signals 의 데이터랩 검색량. 서열 신호로만 쓴다.

    ⚠️ 산 이름이 지명이기도 하면 도시의 검색량이 섞인다 — 안산 20.7 · 오산 9.4 · 금산 3.3 은
       설악산(2.74)보다 높게 나왔다. 검증된 산 중 최대치를 넘는 값은 신뢰하지 않고 잘라낸다.
    """
    out: dict[str, float] = {}
    signals_dir = MOUNTAINS.parent / "signals"
    if not signals_dir.is_dir():
        return out
    for path in signals_dir.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if data.get("popularity"):
            out[data["mountainId"]] = float(data["popularity"])
    if not out:
        return out
    cap = max(sorted(out.values())[: int(len(out) * 0.98)] or [1.0])
    return {k: min(v, cap) for k, v in out.items()}


def _absorb_signals(model: dict, ids: set[str]) -> int:
    """`data/v1/signals/<id>.json` 의 산별 월 곡선을 모델에 넣는다.

    signals 레포가 데이터랩 검색량으로 만든 곡선이다. 추정 유형 프로필(urban/autumnLeaf/…)
    보다 훨씬 낫고, 이게 들어오면 그 산은 `confidence: medium` 이 된다.
    검색은 실제보다 진폭이 크므로 `SEARCH_TO_VISIT` 로 눌러서 쓴다.
    """
    signals_dir = MOUNTAINS.parent / "signals"
    if not signals_dir.is_dir():
        return 0

    count = 0
    for path in sorted(signals_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        mid = data.get("mountainId")
        raw = data.get("monthProfile")
        if mid not in ids or not raw or len(raw) != 12:
            continue

        damped = [v ** SEARCH_TO_VISIT for v in raw]
        mean = sum(damped) / 12
        if mean <= 0:
            continue
        model["monthProfiles"][mid] = [round(v / mean, 4) for v in damped]

        params = model["mountains"].setdefault(mid, {})
        params["monthProfile"] = mid
        # 손으로 적은 high(설악산 실측)는 낮추지 않는다.
        if params.get("confidence") != "high":
            params["confidence"] = "medium"
        count += 1
    return count


def check_distribution(model: dict, mountains: list[dict]) -> bool:
    """앱의 일별 지수 식을 그대로 옮겨 5단계가 고르게 쓰이는지 본다.

    `make_seed.py` 의 교정 점검과 같은 기준이다 — 계수를 바꾸면 24개가 전부 '한산'으로
    뭉개지는 사고가 실제로 있었고, 개별 함수 단위 테스트로는 잡히지 않았다.
    """
    exponent = model["factorExponent"]
    dow = model["dowFactors"]
    profiles = model["monthProfiles"]
    params = model["mountains"]

    values = []
    for m in mountains:
        p = params.get(m["id"])
        if not p:
            continue
        curve = profiles.get(p["monthProfile"]) or profiles["default"]
        for month in range(12):
            for d in range(7):
                values.append(min(100.0, p["baseIndex"] * ((curve[month] * dow[d]) ** exponent)))

    counts = Counter(level(v) for v in values)
    total = len(values)
    print("\n5단계 분포 (300개 산 × 12개월 × 7요일)")
    for _, label in LEVELS:
        c = counts.get(label, 0)
        print(f"  {label:<8} {c/total:>6.1%} {'█' * int(c/total*40)}")
    sat = sum(1 for v in values if v >= 99.5) / total
    flo = sum(1 for v in values if v <= 0.5) / total
    print(f"  포화(100) {sat:.1%} · 바닥(0) {flo:.1%}")

    ok = len(counts) == 5 and sat <= 0.20 and flo <= 0.30
    print("  ✅ 다섯 단계가 모두 쓰인다" if ok else "  ⚠️ 단계가 쏠린다 — factorExponent 재교정 필요")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="기존 추정치(confidence low)를 버리고 다시 계산한다. 손입력은 유지")
    args = ap.parse_args()

    catalog = json.loads(MOUNTAINS.read_text())
    mountains = catalog["mountains"]
    model = json.loads(MODEL.read_text())
    known = model["mountains"]
    trails = json.loads((PIPE / "trails.json").read_text())

    # 등산로 총연장 — 마스터의 courses 는 8개로 잘라 두어 규모를 대표하지 못한다.
    total_km = {}
    for m in mountains:
        t = find_for(m["name"], m["lat"], m["lon"], trails)
        total_km[m["id"]] = t["totalKm"] if t else 0.0

    # 추정치(confidence low)는 마스터가 바뀌면 서열도 바뀌므로 매번 다시 계산한다.
    # 손입력(high/medium)은 절대 건드리지 않는다.
    if args.refresh:
        dropped = [k for k, v in known.items() if v.get("confidence") == "low"]
        for k in dropped:
            del known[k]
        print(f"기존 추정치 {len(dropped)}개를 버리고 다시 계산합니다.")

    # 마스터에서 빠진 산의 파라미터는 남겨 둘 이유가 없다.
    for k in [k for k in known if k not in {m["id"] for m in mountains}]:
        if known[k].get("confidence") == "low":
            del known[k]

    # ── signals 레포가 수집한 산별 실측 곡선을 먼저 흡수한다.
    #
    # 이게 없으면 데이터랩을 300개로 넓혀 수집해도 **배포되는 모델에는 영영 반영되지 않는다** —
    # 지금까지 그 경로는 앱 레포의 make_seed.py 가 번들용으로 읽는 것뿐이었다.
    absorbed = _absorb_signals(model, {m["id"] for m in mountains})
    if absorbed:
        print(f"signals 산별 월 곡선 {absorbed}개 흡수 (추정 → 검색 기반)")

    # signals 흡수는 곡선·신뢰도만 채우므로 baseIndex 가 없는 항목이 생긴다.
    # '이미 값이 있다'의 기준은 id 존재가 아니라 **baseIndex 존재**다.
    train = [m for m in mountains if "baseIndex" in known.get(m["id"], {})]
    todo = [m for m in mountains if "baseIndex" not in known.get(m["id"], {})]
    if not todo:
        print("이미 전부 채워져 있습니다. (추정치를 다시 계산하려면 --refresh)")
        return 0

    # ── 서열을 매기고, 백분위를 baseIndex 구간에 늘어놓는다.
    #
    # 순위 신호는 **데이터랩 검색량**이 1순위다. 손입력 24개와의 상관이 +0.81 로,
    # 마스터 지표만으로 만든 합성 점수(상관 0.4 안팎)와 비교가 안 된다.
    # 검색량이 없는 산에서만 합성 점수로 내려간다.
    #
    # ⚠️ 검색량을 절대값으로 환산하지는 않는다. 손입력 24개로 회귀하면
    #    baseIndex ≈ 32.31 + 7.50·log(검색량) 인데, 이 식을 학습 범위 밖(검색량 0.006 등)에
    #    외삽하면 241개 중 140개가 바닥에 붙는다. 서열만 쓰고 배치는 구간에 맡긴다.
    pop = _search_popularity()
    ranked_by_search = sum(1 for m in todo if m["id"] in pop)
    if ranked_by_search:
        print(f"  서열 근거: 검색량 {ranked_by_search}개 · 합성 점수 {len(todo) - ranked_by_search}개")

    def rank_key(m: dict) -> tuple[int, float]:
        """검색량이 있으면 그걸로, 없으면 합성 점수로. 두 무리는 섞지 않는다 —
        서로 다른 척도를 한 줄에 세우면 순서가 뒤엉킨다."""
        if m["id"] in pop:
            return (1, math.log(pop[m["id"]]))
        return (0, raw_score(m, total_km[m["id"]]))

    scored = sorted(((rank_key(m), m) for m in todo), key=lambda p: p[0])
    print(f"추정 대상 {len(scored)}개")

    for rank, (_key, m) in enumerate(scored):
        pct = rank / max(1, len(scored) - 1)
        acc = accessibility(m["lat"], m["lon"])
        prior = known.get(m["id"], {})
        known[m["id"]] = {
            "baseIndex": round(EST_MIN + (EST_MAX - EST_MIN) * pct, 1),
            "hourCurve": hour_curve_for(m, acc),
            # signals 가 이 산의 곡선을 이미 넣었으면 유형 프로필로 되돌리지 않는다.
            "monthProfile": prior.get("monthProfile") or month_profile_for(m, acc),
            "confidence": prior.get("confidence", "low"),
            "typicalDurationMin": duration_for(m),
        }

    print(f"\n산별 파라미터 {len(known)}개 (실측·검색 기반 {len(train)} + 추정 {len(todo)})")
    print("  추정 상위 5:", ", ".join(f"{m['name']}({known[m['id']]['baseIndex']})" for _, m in scored[-5:][::-1]))
    print("  추정 하위 5:", ", ".join(f"{m['name']}({known[m['id']]['baseIndex']})" for _, m in scored[:5]))
    prof = Counter(v["monthProfile"] if v["monthProfile"] in ("urban", "autumnLeaf", "default", "spring", "winter")
                   else "산별곡선" for v in known.values())
    print("  월 곡선:", dict(prof))
    bases = sorted(v["baseIndex"] for v in known.values())
    print(f"  baseIndex 범위 {bases[0]}~{bases[-1]} (중앙 {bases[len(bases)//2]})")

    ok = check_distribution(model, mountains)

    if args.dry_run:
        return 0
    MODEL.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    print(f"\n{MODEL.relative_to(ROOT)} 갱신")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
