#!/usr/bin/env python3
"""국립공원 '공원경계' SHP → `pipeline/park_buffer_3km.json` (WGS84 다각형).

⚠️ **이 원본은 공원경계가 아니라 경계를 3km 밖으로 부풀린 버퍼다.**
   공공데이터포털 '국립공원공단_국립공원 공원경계_20231231'(15017313)로 배포되지만,
   동봉된 `BSI_NPK_BBNDR.shp.xml` 의 처리 계보에 그대로 남아 있다:

       Buffer diss ... buffer.shp "3 Kilometers" FULL ROUND NONE
       원본 레이어명 GIS_NPM_3KBND3  ← 3K BND = 3km 경계

   실측으로도 확인된다 — 23개 공원 전부 공표 면적의 1.9~4.8배이고, 작은 공원일수록
   배율이 크다(태백산 4.3배, 다도해해상 2.2배). 고정폭 버퍼의 전형적인 신호다.
   그래서 이 다각형으로 `parkType` 을 판정하면 **인왕산·경복궁이 북한산국립공원이 된다.**

   → `parkType` 판정에는 쓰지 말 것. 이 파일은 '국립공원 인접' 신호와,
     진짜 경계 판정을 하기 전의 **1차 후보 거르개**로만 쓴다.

**로컬에서 한 번만 돌리고 결과를 커밋한다.** 원본은 다운로드에 로그인이 필요해
CI 가 받아올 수 없다. 무거운 SHP 대신 가벼운 JSON 을 레포에 넣는다.

    data/raw/park_boundary/BSI_NPK_BBNDR.{shp,dbf,prj}   # gitignore 대상
    python3 pipeline/build_park_index.py

SHP/DBF 를 직접 파싱하는 이유: 이 변환에만 쓰는 형식이라 pyshp 를 CI requirements 에
넣고 싶지 않았다. 두 형식 모두 헤더가 고정폭이라 아래로 충분하고,
`--verify` 가 면적으로 결과를 검사한다.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from geo import KOREA_UNIFIED, point_in_rings, to_wgs84

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "park_boundary" / "BSI_NPK_BBNDR"
OUT = ROOT / "pipeline" / "park_buffer_3km.json"

# 좌표 소수점 자릿수. 5자리 = 약 1.1m — 3km 버퍼 다각형에는 차고 넘친다.
PRECISION = 5

# 국립공원공단이 공표한 공원 면적(km²). 변환 결과가 '버퍼'임을 검증하는 기준.
OFFICIAL_KM2 = {
    "가야산": 76.3, "경주": 136.6, "계룡산": 65.3, "내장산": 80.7, "다도해해상": 2266.2,
    "덕유산": 229.4, "무등산": 75.4, "변산반도": 153.9, "북한산": 76.9, "설악산": 398.2,
    "소백산": 322.0, "속리산": 274.5, "오대산": 326.3, "월악산": 287.6, "월출산": 56.2,
    "주왕산": 105.6, "지리산": 483.0, "치악산": 175.7, "태백산": 70.1, "태안해안": 377.0,
    "팔공산": 126.2, "한라산": 153.4, "한려해상": 535.7,
}


def read_dbf(path: Path) -> list[dict]:
    """dBASE III 테이블 → 레코드 딕셔너리 목록."""
    raw = path.read_bytes()
    count, header_len, record_len = struct.unpack_from("<IHH", raw, 4)

    fields = []
    pos = 32
    while raw[pos] != 0x0D:              # 0x0D 가 필드 서술자의 끝
        name = raw[pos : pos + 11].split(b"\x00")[0].decode("cp949", "replace")
        size = raw[pos + 16]
        fields.append((name, size))
        pos += 32

    rows = []
    for i in range(count):
        base = header_len + i * record_len
        if raw[base : base + 1] == b"*":  # 삭제 표시 레코드
            continue
        off = base + 1
        row = {}
        for name, size in fields:
            row[name] = raw[off : off + size].decode("cp949", "replace").strip()
            off += size
        rows.append(row)
    return rows


def read_shp_polygons(path: Path) -> list[list[list[tuple[float, float]]]]:
    """SHP(폴리곤) → 도형별 링 목록. 링 하나는 [(x, y), ...] 투영좌표.

    ESRI Shapefile 사양: 파일 헤더 100바이트 뒤로 레코드가 이어지고,
    레코드 헤더 8바이트(번호·길이, 빅엔디언) 다음이 내용부(리틀엔디언)다.
    """
    raw = path.read_bytes()
    shapes = []
    pos = 100
    while pos < len(raw):
        _num, content_words = struct.unpack_from(">II", raw, pos)
        pos += 8
        end = pos + content_words * 2

        shape_type = struct.unpack_from("<i", raw, pos)[0]
        if shape_type == 0:              # Null Shape
            pos = end
            continue
        if shape_type != 5:
            raise ValueError(f"폴리곤(5)이 아닌 도형 타입 {shape_type}")

        num_parts, num_points = struct.unpack_from("<ii", raw, pos + 36)
        parts = struct.unpack_from(f"<{num_parts}i", raw, pos + 44)
        coords_at = pos + 44 + num_parts * 4
        pts = struct.unpack_from(f"<{num_points * 2}d", raw, coords_at)

        rings = []
        for r, start in enumerate(parts):
            stop = parts[r + 1] if r + 1 < num_parts else num_points
            rings.append([(pts[2 * i], pts[2 * i + 1]) for i in range(start, stop)])
        shapes.append(rings)
        pos = end
    return shapes


def _shoelace_km2(rings: list[list[tuple[float, float]]]) -> float:
    """투영좌표(m)에서의 면적(km²). 구멍 링은 감김 방향이 반대라 자동으로 빠진다."""
    total = 0.0
    for ring in rings:
        s = 0.0
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            s += x1 * y2 - x2 * y1
        total += s / 2
    return abs(total) / 1e6


def build() -> dict:
    shp, dbf = SRC.with_suffix(".shp"), SRC.with_suffix(".dbf")
    if not shp.exists():
        sys.exit(f"원본 없음: {shp}\n공공데이터포털 '국립공원공단_국립공원 공원경계' 를 받아 풀어 두세요.")

    shapes = read_shp_polygons(shp)
    records = read_dbf(dbf)
    if len(shapes) != len(records):
        sys.exit(f"도형 {len(shapes)}개 ≠ 속성 {len(records)}개 — 원본이 깨졌습니다.")

    parks = []
    for rings, rec in zip(shapes, records):
        wgs_rings = [
            [
                [round(lon, PRECISION), round(lat, PRECISION)]
                for lat, lon in (to_wgs84(x, y, KOREA_UNIFIED) for x, y in ring)
            ]
            for ring in rings
        ]
        flat = [p for r in wgs_rings for p in r]
        parks.append(
            {
                "name": rec["NPK_NM"],
                "code": rec["NPK_CD"],
                # 점-다각형 판정 전에 사각형으로 먼저 걸러내면 대부분의 산이 즉시 탈락한다.
                "bbox": [
                    min(p[0] for p in flat), min(p[1] for p in flat),
                    max(p[0] for p in flat), max(p[1] for p in flat),
                ],
                "areaKm2": round(_shoelace_km2(rings), 1),
                "rings": wgs_rings,
            }
        )

    parks.sort(key=lambda p: p["name"])
    return {
        "source": "국립공원공단_국립공원 공원경계_20231231 (공공누리 1유형)",
        "warning": "공원경계가 아니라 경계를 3km 확장한 버퍼다. parkType 판정에 쓰지 말 것.",
        "bufferM": 3000,
        "crs": "WGS84",
        "parks": parks,
    }


def near_national_park(lat: float, lon: float, index: dict) -> str | None:
    """좌표가 어느 국립공원 3km 버퍼 안에 있는지. **공원 소속 판정이 아니다.**"""
    for park in index["parks"]:
        x0, y0, x1, y1 = park["bbox"]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if point_in_rings(lat, lon, park["rings"]):
            return park["name"]
    return None


def verify(index: dict) -> int:
    """면적으로 '이건 버퍼다'를 재확인한다. 공표 면적과 같아지면 원본이 바뀐 것이므로 알려야 한다."""
    print(f"{'공원':<10}{'변환 면적':>10}{'공표 면적':>10}{'배율':>8}")
    ratios = []
    for park in index["parks"]:
        official = OFFICIAL_KM2.get(park["name"])
        if not official:
            print(f"{park['name']:<10}{park['areaKm2']:>10.1f}{'-':>10}{'-':>8}")
            continue
        ratio = park["areaKm2"] / official
        ratios.append(ratio)
        print(f"{park['name']:<10}{park['areaKm2']:>10.1f}{official:>10.1f}{ratio:>7.2f}x")

    lo, hi = min(ratios), max(ratios)
    print(f"\n배율 {lo:.2f}~{hi:.2f}x (공원 {len(ratios)}개)")
    if lo > 1.3:
        print("→ 예상대로 버퍼 레이어다. parkType 판정에는 쓸 수 없다.")
        return 0
    print("→ ⚠️ 면적이 공표값에 가깝다. 원본이 진짜 공원경계로 교체됐을 수 있으니 확인하세요.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="면적 대조만 하고 파일은 쓰지 않는다")
    args = ap.parse_args()

    index = build()
    if args.verify:
        return verify(index)

    OUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    pts = sum(len(r) for p in index["parks"] for r in p["rings"])
    print(f"{OUT.relative_to(ROOT)} — 공원 {len(index['parks'])}개 · 정점 {pts:,}개 · {OUT.stat().st_size/1024:.0f}KB")
    print("⚠️ 3km 버퍼다. parkType 판정 아님 — 인접 신호·후보 거르개 용도.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
