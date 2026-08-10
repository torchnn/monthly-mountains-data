#!/usr/bin/env python3
"""좌표계 변환과 다각형 판정. **외부 의존성 없음**(표준 라이브러리만).

pyproj/shapely 를 쓰지 않는 이유: 이 파일이 하는 일은 횡메르카토르 역변환 하나와
점-다각형 판정 하나뿐인데, 그것 때문에 CI 에 PROJ 바이너리(수십 MB)를 끌어오면
`pip install` 시간이 수집 시간보다 길어진다. 두 함수 모두 공식이 확정돼 있고
검증 수단도 있다 — `python3 pipeline/geo.py` 로 자기검사가 돈다.

받는 원본이 쓰는 좌표계가 둘이라 파라미터만 바꿔 같은 공식을 쓴다.
  · 국립공원 공원경계  → EPSG:5179 (UTM-K)          FE 1,000,000 / FN 2,000,000 / CM 127.5 / k 0.9996
  · 전국등산로표준데이터 → EPSG:5186 (중부원점 2010) FE   200,000 / FN   600,000 / CM 127.0 / k 1.0
둘 다 GRS80 타원체 위의 Transverse Mercator 다. ITRF2000·Korea2000 과 WGS84 의
차이는 cm 급이라 이 앱(지도 핀·공원 소속 판정)에서는 무시한다.
"""
from __future__ import annotations

import math

# GRS80
A = 6378137.0
INV_F = 298.257222101
F = 1.0 / INV_F
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)


class TM:
    """횡메르카토르 도법 파라미터. 원본 .prj 의 PARAMETER 값을 그대로 옮긴다."""

    def __init__(self, *, fe: float, fn: float, cm: float, lat0: float, k: float):
        self.fe, self.fn, self.k = fe, fn, k
        self.cm = math.radians(cm)
        self.lat0 = math.radians(lat0)
        self.m0 = _meridian_arc(self.lat0)


def _meridian_arc(lat: float) -> float:
    """적도에서 위도 lat 까지의 자오선 호 길이(m). Snyder 3-21."""
    return A * (
        (1 - E2 / 4 - 3 * E2**2 / 64 - 5 * E2**3 / 256) * lat
        - (3 * E2 / 8 + 3 * E2**2 / 32 + 45 * E2**3 / 1024) * math.sin(2 * lat)
        + (15 * E2**2 / 256 + 45 * E2**3 / 1024) * math.sin(4 * lat)
        - (35 * E2**3 / 3072) * math.sin(6 * lat)
    )


# .prj 에서 확인한 값 (data/raw/*/**.prj)
KOREA_UNIFIED = TM(fe=1_000_000.0, fn=2_000_000.0, cm=127.5, lat0=38.0, k=0.9996)   # EPSG:5179
KOREA_CENTRAL = TM(fe=200_000.0, fn=600_000.0, cm=127.0, lat0=38.0, k=1.0)          # EPSG:5186


def to_wgs84(x: float, y: float, tm: TM) -> tuple[float, float]:
    """투영좌표(m) → (위도, 경도) 도 단위. Snyder 8-1..8-6 역변환."""
    m = tm.m0 + (y - tm.fn) / tm.k
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    mu = m / (A * (1 - E2 / 4 - 3 * E2**2 / 64 - 5 * E2**3 / 256))

    lat1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    sin1, cos1, tan1 = math.sin(lat1), math.cos(lat1), math.tan(lat1)
    c1 = EP2 * cos1**2
    t1 = tan1**2
    n1 = A / math.sqrt(1 - E2 * sin1**2)
    r1 = A * (1 - E2) / (1 - E2 * sin1**2) ** 1.5
    d = (x - tm.fe) / (n1 * tm.k)

    lat = lat1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * EP2 - 3 * c1**2) * d**6 / 720
    )
    lon = tm.cm + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * EP2 + 24 * t1**2) * d**5 / 120
    ) / cos1

    return math.degrees(lat), math.degrees(lon)


def point_in_rings(lat: float, lon: float, rings: list[list[list[float]]]) -> bool:
    """짝수-홀수 규칙 점-다각형 판정. 링을 구분하지 않고 전부 세므로
    구멍(내부 링)이 자동으로 처리된다 — 국립공원 경계에는 사유지 제외 구멍이 실제로 있다.

    rings 는 [[[lon, lat], ...], ...] (GeoJSON 순서와 동일).
    """
    inside = False
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat):
                # 경계선이 수평이면 (yj - yi) 가 0 이지만, 위 조건이 이미 걸러낸다.
                if lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                    inside = not inside
            j = i
    return inside


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이 대권거리(m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def _self_test() -> int:
    """원본 데이터가 같은 지점을 투영좌표와 WGS84 둘 다로 주기 때문에 실측 검증이 된다.
    전국등산로표준데이터의 SPOT 레이어는 esri json(EPSG:5186)과 GPX(WGS84)로 함께 배포된다.
    """
    import zipfile
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    trails = root / "data" / "raw" / "trails" / "mountain"
    if not trails.exists():
        print("⏭  data/raw/trails 없음 — 원본을 받은 뒤에 다시 돌리세요.")
        return 0

    def members(path: Path) -> dict[str, bytes]:
        out = {}
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                try:
                    name = info.filename.encode("cp437").decode("cp949")
                except Exception:  # noqa: BLE001 — 인코딩 추정 실패는 원본 이름으로 둔다
                    name = info.filename
                out[name] = z.read(info)
        return out

    import json
    import re

    worst = 0.0
    checked = 0
    for code in ("111100101", "113050202", "114000101"):
        gj, gpx = trails / f"{code}_geojson.zip", trails / f"{code}_gpx.zip"
        if not (gj.exists() and gpx.exists()):
            continue
        spot_json = next((v for k, v in members(gj).items() if "SPOT" in k and k.endswith(".json")), None)
        spot_gpx = next((v for k, v in members(gpx).items() if "SPOT" in k and k.endswith(".gpx")), None)
        if not (spot_json and spot_gpx):
            continue

        proj = [(f["geometry"]["x"], f["geometry"]["y"]) for f in json.loads(spot_json)["features"]]
        truth = [
            (float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r'<wpt lat="([-\d.]+)" lon="([-\d.]+)"', spot_gpx.decode("utf-8", "replace"))
        ]
        if len(proj) != len(truth):
            print(f"  ! {code}: 지점 수 불일치 {len(proj)} vs {len(truth)} — 건너뜀")
            continue

        # 두 파일의 행 순서가 같다는 보장이 없으므로, 변환 결과마다 가장 가까운 정답을 찾는다.
        for x, y in proj:
            lat, lon = to_wgs84(x, y, KOREA_CENTRAL)
            d = min(haversine_m(lat, lon, tlat, tlon) for tlat, tlon in truth)
            worst = max(worst, d)
            checked += 1

    print(f"등산로 SPOT {checked}개 지점 — GPX 정답 대비 최대 오차 {worst*100:.2f}cm")
    ok = checked > 0 and worst < 1.0
    print("✅ 통과" if ok else "❌ 실패(1m 초과)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
