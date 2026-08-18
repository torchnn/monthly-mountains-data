#!/usr/bin/env python3
"""공공데이터 + 등산로 변환본 → `data/v1/mountains.json` (앱이 읽는 산 마스터).

    python3 pipeline/build_mountains.py                 # 300개
    python3 pipeline/build_mountains.py --limit 40      # 시험
    python3 pipeline/build_mountains.py --no-photo      # 관광공사 호출 생략(빠름)

원천 (전부 `DATA_GO_KR_KEY` 하나로 접근)
  · 산림청_산정보            4,705건 → 표고·소재지·`story`
  · 100대명산 목록정보         100건 → 좌표·표고·`mtnCd`·`isTop100`
  · 주요봉우리 문화자원 POI   3,854건 → `peaks`
  · 관광공사 국문관광정보            → `photoURL`(공공누리 1유형)
  · `pipeline/trails.json`   2,932건 → `courses`·`trailheads`  (로컬 변환본)
  · `pipeline/flagship_species.json` → `species`(국립공원 깃대종)

**조인은 코드로 한다.** 100대명산의 `mtnCd` 와 `trails.json` 의 `code` 가 같은 체계라
100개 중 82개가 직접 붙는다. 코드가 없을 때만 이름+좌표 매칭(`find_for`)으로 내려간다 —
등산로 원본에는 동명이산이 그대로 들어 있어 이름만으로 맞추면 계룡산이 207km 떨어진
다른 산에 붙는다(앱 레포 HANDOFF 함정 12).

⚠️ 채우지 않는 필드와 그 이유
  · `ascentM`         등산로 원본 GPX 고도가 전부 0이다 (함정 10)
  · `kmaMountainCode` 기상청 산악예보는 포털에 없다 — 단기예보 격자로만 간다
  · `parkType`        '공원경계' 파일이 실은 3km 버퍼라 좌표 판정이 불가능하다 (함정 11).
                      국립공원은 아래 표로 손 매핑한다. 도립·군립은 원천이 없어 none.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from build_trail_index import find_for
from geo import haversine_m
from hangul import slug
# 진행률 로그. 스크립트로 직접 돌리면 `_progress` 가 바로 보이지만,
# 테스트가 `from pipeline import ...` 처럼 패키지로 부르면 안 보인다. 둘 다 되게 한다.
try:
    from _progress import track
except ImportError:  # pragma: no cover
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _progress import track

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
OUT = ROOT / "data" / "v1" / "mountains.json"
CACHE = ROOT / "data" / "raw" / "api_cache"

KEY = os.environ.get("DATA_GO_KR_KEY", "")
TIMEOUT = 30
RETRIES = 3
TARGET = int(os.environ.get("MOUNTAIN_LIMIT") or 0) or 300

# 하루 코스로 볼 수 있는 상한. 넘는 건 원본의 구간 묶음이지 경로가 아니다.
COURSE_MAX_KM, COURSE_MAX_MIN = 25.0, 600

FOREST = "https://apis.data.go.kr/1400000/service/cultureInfoService2/mntInfoOpenAPI2"
TOP100 = "https://apis.data.go.kr/B553662/top100FamtListBasiInfoService/getTop100FamtListBasiInfoList"
PEAKS = "https://apis.data.go.kr/B553662/culturalInfoService/getCulturalInfoList"
TOUR = "https://apis.data.go.kr/B551011/KorService2/searchKeyword2"

# 국립공원 23곳 → 그 공원에 속한 산 이름.
# 좌표 판정을 못 쓰는 대신(함정 11) 손으로 적는다. 여기 없는 산은 `none` 이 된다 —
# 잘못 붙이는 것보다 비워 두는 쪽이 낫다(3km 버퍼로 판정했더니 인왕산이 북한산이 됐다).
NATIONAL_PARKS = {
    "북한산": ["북한산", "도봉산"],
    "설악산": ["설악산", "점봉산"],
    "지리산": ["지리산", "반야봉", "노고단", "천왕봉"],
    "한라산": ["한라산"],
    "덕유산": ["덕유산", "남덕유산", "향적봉"],
    "오대산": ["오대산", "노인봉", "계방산"],
    "속리산": ["속리산", "구병산"],
    "계룡산": ["계룡산"],
    "월악산": ["월악산", "주흘산", "만수봉"],
    "치악산": ["치악산"],
    "소백산": ["소백산", "비로봉"],
    "가야산": ["가야산", "남산제일봉"],
    "내장산": ["내장산", "백암산", "입암산"],
    "주왕산": ["주왕산"],
    "무등산": ["무등산", "안양산"],
    "태백산": ["태백산", "함백산"],
    "팔공산": ["팔공산"],
    "월출산": ["월출산"],
    "변산반도": ["변산", "쌍선봉"],
    "경주": ["토함산", "남산"],
    "다도해해상": [],
    "한려해상": ["금산"],
    "태안해안": [],
}

# 소재지 시도 → 에어코리아 sidoName
AIR_REGION = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주",
    "대전": "대전", "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원",
    "충청북": "충북", "충북": "충북", "충청남": "충남", "충남": "충남",
    "전라북": "전북", "전북": "전북", "전라남": "전남", "전남": "전남",
    "경상북": "경북", "경북": "경북", "경상남": "경남", "경남": "경남", "제주": "제주",
}

# ---------------------------------------------------------------- 기상청 격자

# Lambert Conformal Conic 파라미터 (동네예보 활용가이드 부록).
# 앱 레포 `pipeline/make_seed.py` 와 같은 값이어야 한다 — 시드와 마스터의 격자가 어긋나면
# 같은 산인데 예보가 달라진다.
_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT = 30.0, 60.0, 126.0, 38.0
_XO, _YO = 43, 136


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 단기예보 격자(nx, ny)."""
    deg = math.pi / 180.0
    re_ = _RE / _GRID
    slat1, slat2 = _SLAT1 * deg, _SLAT2 * deg
    olon, olat = _OLON * deg, _OLAT * deg

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf**sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re_ * sf / (ro**sn)

    ra = math.tan(math.pi * 0.25 + lat * deg * 0.5)
    ra = re_ * sf / (ra**sn)
    theta = lon * deg - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    return int(ra * math.sin(theta) + _XO + 0.5), int(ro - ra * math.cos(theta) + _YO + 0.5)


# ---------------------------------------------------------------- 원천 수집


# 마지막 _get 호출이 '실패' 였는지. 사진 캐시가 실패를 '사진 없음' 으로 굳히는 걸 막는다.
_LAST_CALL_FAILED = False


def _get(url: str, params: dict) -> str | None:
    """공공데이터포털은 간헐적으로 빈 응답·XML 에러를 준다 — 재시도 후 포기.

    ⚠️ 관광공사(B551011)는 짧은 시간에 몰아 부르면 **HTTP 429** 를 준다.
       사진을 못 찾은 산마다 최대 6회씩 물어보다가 실제로 429 가 쏟아졌다.
       429 는 '잠깐 쉬라'는 뜻이므로 일반 오류보다 훨씬 길게 기다린다.
    """
    global _LAST_CALL_FAILED
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params={**params, "serviceKey": KEY}, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(5.0 * (attempt + 1))
                raise requests.HTTPError("HTTP 429 (호출 제한)")
            if r.status_code != 200:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            if "SERVICE_KEY_IS_NOT_REGISTERED" in r.text:
                sys.exit(f"인증키가 이 API 에 승인되지 않았습니다: {url}")
            _LAST_CALL_FAILED = False
            return r.text
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도 후 넘어간다
            if attempt == RETRIES - 1:
                print(f"  ! 실패 {url.rsplit('/', 1)[-1]}: {exc}", file=sys.stderr)
                _LAST_CALL_FAILED = True
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def _tags(xml: str) -> list[dict]:
    """<item> 블록을 평평한 딕셔너리 목록으로. 이 API 들은 중첩이 없어 이걸로 충분하다."""
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        row = {k: v.strip() for k, v in re.findall(r"<(\w+)>(.*?)</\1>", block, re.S)}
        if row:
            out.append(row)
    return out


def _paged(url: str, params: dict, name: str, per_page: int = 1000) -> list[dict]:
    """전체 페이지를 훑는다. 결과는 캐시에 남겨 재실행을 빠르게 한다."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{name}.json"
    if cache.exists():
        rows = json.loads(cache.read_text())
        print(f"  {name}: 캐시 {len(rows):,}건")
        return rows

    rows, page = [], 1
    while True:
        xml = _get(url, {**params, "numOfRows": per_page, "pageNo": page})
        if not xml:
            break
        batch = _tags(xml)
        rows.extend(batch)
        total = re.search(r"<totalCount>(\d+)</totalCount>", xml)
        if not batch or (total and len(rows) >= int(total.group(1))):
            break
        page += 1
        if page > 50:                      # 폭주 방지
            break
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    print(f"  {name}: {len(rows):,}건 수신")
    return rows


def fetch_photo(name: str, lat: float, lon: float) -> tuple[str | None, str | None]:
    """캐시를 먼저 본다. **못 찾은 것도 기록**한다 — 사진 없는 산이 130개라
    매 실행마다 산당 최대 10회씩 다시 물어보면 빌드가 40분씩 늘어난다."""
    cached = _photo_cache()
    if name in cached:
        url = cached[name]
        return (url, "한국관광공사 (공공누리 제1유형)") if url else (None, None)
    global _LAST_CALL_FAILED
    _LAST_CALL_FAILED = False
    url, credit = _fetch_photo_uncached(name, lat, lon)
    # 호출이 실패해서 못 찾은 것을 '사진 없음' 으로 굳히면, 다음 실행에서 영영 재시도하지 않는다.
    # 호출 제한(429)에 걸린 회차가 그대로 캐시에 박히는 사고가 실제로 있었다.
    if url or not _LAST_CALL_FAILED:
        cached[name] = url
        _save_photo_cache()
    # 관광공사는 몰아 부르면 429 를 준다 — 산 사이에 숨을 둔다.
    time.sleep(1.2)
    return url, credit


_PHOTOS: dict[str, str | None] | None = None


def _photo_cache() -> dict:
    global _PHOTOS
    if _PHOTOS is None:
        path = CACHE / "photos.json"
        _PHOTOS = json.loads(path.read_text()) if path.exists() else {}
    return _PHOTOS


def _save_photo_cache() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "photos.json").write_text(json.dumps(_PHOTOS, ensure_ascii=False))


def _fetch_photo_uncached(name: str, lat: float, lon: float) -> tuple[str | None, str | None]:
    """관광공사 대표사진. 좌표가 멀거나 관광지 유형이 아니면 버린다.

    ⚠️ 키워드 검색은 '북한산' 으로 '북한산 둘레캠프'(contenttypeid 28) 를 1등으로 준다.
       관광지(12)·자연(cat1 A01) 로 좁히고 좌표 거리도 확인해야 산 사진이 나온다.
    """
    # 이름에 괄호가 붙은 산('백운산(광양)')은 그대로 검색하면 0건이다.
    # 괄호를 떼면 붙는다 — 동명이산 오염은 아래 좌표 검증이 막는다.
    queries = [name]
    stripped = re.sub(r"\(.*?\)", "", name).strip()
    if stripped and stripped != name:
        queries.append(stripped)

    base = re.sub(r"\(.*?\)", "", name).strip().split("_")[0]

    # 1차: 관광지(12)로 좁혀 검색. 2차: 유형을 풀되 **제목에 산 이름이 들어간 것만**.
    #
    # ⚠️ 유형·반경을 그냥 넓히면 안 된다. 사진이 없는 산 주변 10km 를 뒤지면
    #    '뚜레한우 홍천본점'·'산골캠핑장' 사진이 잡혀 가리산 대표사진이 된다.
    #    확인해 보면 그 산들은 TourAPI 에 항목은 있는데 `firstimage` 가 비어 있다 —
    #    필터 탓이 아니라 원본에 사진이 없는 것이라, 없는 채로 두는 게 맞다.
    #    (앱은 사진이 없으면 능선 일러스트로 대체한다.)
    attempts = [({"contentTypeId": 12}, False)]
    attempts += [({}, True)] if base else []

    for query in queries:
        for extra, need_title in attempts:
            xml = _get(TOUR, {"numOfRows": 20, "pageNo": 1, "MobileOS": "ETC",
                              "MobileApp": "monthly-mountains", "keyword": query,
                              "arrange": "O", **extra})
            if not xml:
                continue
            best = None
            for row in _tags(xml):
                img = row.get("firstimage") or ""
                if not img.startswith("http"):
                    continue
                if need_title and base not in (row.get("title") or ""):
                    continue
                try:
                    d = haversine_m(lat, lon, float(row["mapy"]), float(row["mapx"]))
                except (KeyError, ValueError, TypeError):
                    continue
                if d > 15000:               # 15km 밖이면 다른 곳이다
                    continue
                if best is None or d < best[0]:
                    best = (d, img)
            if best:
                return best[1], "한국관광공사 (공공누리 제1유형)"

    # 3차: `firstimage` 가 비어도 **추가 이미지**(detailImage2)는 있는 경우가 있다.
    #      표본 8개 중 4개가 여기서 나왔다.
    #
    # ⚠️ 다만 '홍천 가리산 레포츠파크'·'황석산청소년수련원' 처럼 산 이름을 딴 시설이 섞인다.
    #    시설 사진을 산 대표사진으로 올리면 능선 일러스트보다 나쁘므로,
    #    제목이 산 이름(+지역 괄호)과 사실상 같은 것만 받는다.
    for row in _keyword_candidates(base or name):
        title = (row.get("title") or "").strip()
        if _facility_like(title, base or name):
            continue
        try:
            if haversine_m(lat, lon, float(row["mapy"]), float(row["mapx"])) > 15000:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        xml = _get(TOUR.replace("searchKeyword2", "detailImage2"),
                   {"contentId": row.get("contentid"), "imageYN": "Y",
                    "numOfRows": 5, "pageNo": 1, "MobileOS": "ETC", "MobileApp": "monthly-mountains"})
        if not xml:
            continue
        for img in _tags(xml):
            url = (img.get("originimgurl") or "").strip()
            if url.startswith("http"):
                return url, "한국관광공사 (공공누리 제1유형)"
    return None, None


def _keyword_candidates(keyword: str) -> list[dict]:
    xml = _get(TOUR, {"numOfRows": 5, "pageNo": 1, "MobileOS": "ETC",
                      "MobileApp": "monthly-mountains", "keyword": keyword, "arrange": "O"})
    return _tags(xml) if xml else []


# 산 이름을 딴 시설. 이런 제목의 사진은 산이 아니라 건물이다.
FACILITY = ("파크", "수련원", "캠핑", "펜션", "리조트", "식당", "주차장", "센터", "휴양림",
            "박물관", "미술관", "관광지", "체험", "농원", "마을", "온천", "골프")


# 산 자체를 가리키는 수식어. 이게 붙은 제목은 시설이 아니라 산 사진으로 본다.
MOUNTAIN_WORDS = ("정상", "능선", "등산로", "전경", "설경", "일출", "단풍", "계곡", "봉", "산")


def _facility_like(title: str, name: str) -> bool:
    """제목이 산 그 자체가 아니라 그 이름을 딴 시설인지.

    '홍천 가리산 레포츠파크'·'황석산청소년수련원' 같은 게 실제로 온다 —
    건물 사진을 산 대표사진으로 올리면 능선 일러스트보다 나쁘다.
    """
    if not title or name not in title:
        return True
    if any(word in title for word in FACILITY):
        return True
    # 이름을 빼고 남는 게 지역·수식어 정도면 산 사진으로 본다.
    rest = re.sub(r"\(.*?\)", "", title).replace(name, "").strip()
    return bool(rest) and len(rest) > 6 and not any(w in rest for w in MOUNTAIN_WORDS)


# ---------------------------------------------------------------- 조립


def _region_of(addr: str) -> tuple[str, str]:
    """소재지 문자열 → (시도, 시군구). 원본은 '서울특별시  강북구 우이동' 처럼 공백이 불규칙하다."""
    parts = [p for p in re.split(r"\s+", (addr or "").strip()) if p]
    if not parts:
        return "", ""
    sido = parts[0]
    short = re.sub(r"(특별자치도|특별자치시|특별시|광역시|자치도|자치시|도|시)$", "", sido) or sido
    sigungu = f"{short} {parts[1]}" if len(parts) > 1 else short
    return short, sigungu


def _air_region(sido: str) -> str:
    for prefix, air in AIR_REGION.items():
        if sido.startswith(prefix):
            return air
    return "서울"


def _park_of(name: str) -> tuple[str, str | None]:
    base = name.split("_")[0]
    for park, members in NATIONAL_PARKS.items():
        if base in members:
            return "national", f"{park}국립공원"
    return "none", None


def _difficulty_from(elevation: int, courses: list[dict]) -> int:
    """산 난이도 1~5.

    코스 난이도의 **중앙값**을 쓰고, 표고로 상한을 씌운다.
    최댓값을 쓰면 63m 짜리 초록봉이 '어려움'이 된다 — 라우팅이 정상에서 먼 들머리까지
    이어 붙여 7.8km 코스가 생기고, 그 하나가 산 전체의 난이도를 정해 버리기 때문이다.
    낮은 산이 어려울 수는 없으므로 표고가 최종 결정권을 갖는다.
    """
    ceiling = 1 if elevation < 200 else 2 if elevation < 500 else 3 if elevation < 900 else 5
    got = sorted(c["difficulty"] for c in courses if c.get("difficulty"))
    if got:
        median = got[len(got) // 2]
        return max(1, min(ceiling, median))
    return min(ceiling, 1 if elevation < 300 else 2 if elevation < 600 else 3 if elevation < 1000 else 4)


def _course_difficulty(course: dict, fallback: int) -> int:
    """앱은 코스 난이도를 필수(non-optional)로 받는다 — null 을 남길 수 없다.
    원본 난이도가 비어 있으면 거리로 가른다."""
    if course.get("difficulty"):
        return course["difficulty"]
    km = course.get("distanceKm") or 0
    return 2 if km < 3 else 3 if km < 6 else 4


def _tagline(elevation: int, sido: str, top100: bool, park: str | None) -> str:
    """한 줄 소개. 편집 문구는 300개를 손으로 못 쓰므로 사실만 조합한다."""
    bits = []
    if park:
        bits.append(park)
    elif top100:
        bits.append("100대 명산")
    if sido:
        bits.append(sido)
    if elevation:
        bits.append(f"해발 {elevation:,}m")
    return " · ".join(bits) or "우리 산"


def build(limit: int, want_photo: bool) -> dict:
    if not KEY:
        sys.exit("DATA_GO_KR_KEY 가 없습니다.")

    print("원천 수집")
    forest = _paged(FOREST, {"searchWrd": ""}, "forest_mntinfo")
    top100 = _paged(TOP100, {}, "top100")
    peaks_raw = _paged(PEAKS, {}, "peaks")
    trails = json.loads((PIPE / "trails.json").read_text())
    # 깃대종은 공원 이름('북한산')이 키다 — '국립공원' 접미사는 붙지 않는다.
    flagship = json.loads((PIPE / "flagship_species.json").read_text())["parks"]

    # 손으로 편집한 코스(24개 산). 라우팅보다 정확하므로 있으면 그걸 쓴다.
    curated_path = PIPE / "curated_courses.json"
    _cur = json.loads(curated_path.read_text()) if curated_path.exists() else {}
    curated = _cur.get("courses", {})
    curated_taglines = _cur.get("taglines", {})
    curated_peaks = _cur.get("peaks", {})

    # 기존 id 승계 — 나간 id 를 바꾸면 사용자의 즐겨찾기가 끊긴다.
    prior = {}
    if OUT.exists():
        for m in json.loads(OUT.read_text()).get("mountains", []):
            prior[m["name"]] = m

    # ── 산정보를 이름으로 인덱싱. 같은 이름이 여럿이면 표고가 높은 쪽을 쓴다
    #    (원본에 '북한산'(서대문구, 0m)과 '북한산_백운대'(835.6m)가 따로 있다).
    forest_by_name: dict[str, dict] = {}
    for row in forest:
        name = (row.get("mntiname") or "").strip()
        if not name:
            continue
        base = name.split("_")[0]
        try:
            high = float(row.get("mntihigh") or 0)
        except ValueError:
            high = 0.0
        cur = forest_by_name.get(base)
        if cur is None or high > cur["_high"]:
            forest_by_name[base] = {**row, "_high": high}

    trail_by_code = {t["code"]: t for t in trails["mountains"]}

    # ── 대상 선정: 100대명산 → 기존 시드 → 등산로가 긴 산 순
    picked: dict[str, dict] = {}     # 이름 → 원천 조각

    for row in top100:
        name = (row.get("frtrlNm") or "").strip()
        if not name:
            continue
        picked.setdefault(name, {"top100": True, "t100": row})

    for name in prior:
        picked.setdefault(name, {"top100": False})

    # 표고를 못 구해 탈락하는 산이 나오므로 목표보다 넉넉히 고르고 마지막에 자른다.
    pool = int(limit * 1.2) + 10
    for t in sorted(trails["mountains"], key=lambda x: -x["totalKm"]):
        if len(picked) >= pool:
            break
        base = t["name"].split("_")[0]
        # 등산로 원본에는 '낙동정맥'·'백두대간트레일인제' 같은 장거리 노선도 섞여 있다.
        if not base.endswith(("산", "봉", "악", "대", "령", "岳")):
            continue
        if base not in forest_by_name:      # 산정보에 없으면 표고·소재지를 못 채운다
            continue
        picked.setdefault(base, {"top100": False, "trail": t})

    names = list(picked)[:pool]
    print(f"\n후보 {len(names)}개 → 목표 {limit}개 "
          f"(100대명산 {sum(1 for n in names if picked[n].get('top100'))}개 포함)")

    mountains, skipped_no_elev = [], []
    stats = {"trail": 0, "story": 0, "photo": 0, "peaks": 0, "species": 0, "park": 0}
    for i, name in enumerate(names, 1):
        src = picked[name]
        finfo = forest_by_name.get(name, {})
        t100 = src.get("t100", {})

        # 좌표: 기존 시드 > 100대명산 > 등산로
        prev = prior.get(name)
        trail = src.get("trail")
        lat = lon = None
        if prev:
            lat, lon = prev["lat"], prev["lon"]
        elif t100.get("lat"):
            try:
                lat, lon = float(t100["lat"]), float(t100["lot"])
            except (ValueError, KeyError):
                lat = lon = None
        if lat is None and trail:
            lat, lon = trail["lat"], trail["lon"]
        if lat is None or not (33 <= lat <= 39 and 124 <= lon <= 132):
            continue

        # 주변 3km 안의 봉우리 POI. 표고 폴백과 `peaks` 둘 다에 쓰므로 먼저 모은다.
        nearby = []
        for p in peaks_raw:
            try:
                plat, plon, alt = float(p["lat"]), float(p["lot"]), float(p.get("aslAltide") or 0)
            except (KeyError, ValueError):
                continue
            if alt > 0 and haversine_m(lat, lon, plat, plon) <= 3000:
                nearby.append(((p.get("frtrlNm") or "").strip(), alt))

        # 표고: 100대명산 > 산정보 > 기존 > 주변 봉우리 최고점
        elevation = 0
        for cand in (t100.get("aslAltide"), finfo.get("mntihigh")):
            try:
                elevation = int(round(float(cand)))
            except (TypeError, ValueError):
                continue
            if elevation > 0:
                break
        if elevation <= 0 and prev:
            elevation = prev["elevation"]
        if elevation <= 0 and nearby:
            # 산정보에 표고가 비어 있는 산이 실제로 있다(21개가 0m 로 나갔다).
            # 봉우리 POI 는 실측 고도를 갖고 있으니 주변 최고점으로 대신한다.
            elevation = int(round(max(alt for _, alt in nearby)))
        if elevation <= 0:
            skipped_no_elev.append(name)
            continue

        # 등산로: mtnCd 직결이 1순위, 없으면 이름+좌표 매칭
        if trail is None:
            code = (t100.get("mtnCd") or "").strip()
            trail = trail_by_code.get(code) or find_for(name, lat, lon, trails)
        if trail:
            stats["trail"] += 1

        addr = (t100.get("addrNm") or finfo.get("mntiadd") or "").strip()
        sido, sigungu = _region_of(addr)
        if not sido and prev:
            sido, sigungu = prev["region"], prev["sigungu"]

        park_type, park_name = _park_of(name)
        if park_type == "national":
            stats["park"] += 1

        # 코스 우선순위: 편집본 > 라우팅 > 이름 묶음.
        #
        # 편집본(`curated_courses.json`, 24개 산)이 1순위인 이유는 원본의 상행 시간이
        # 낙관적이기 때문이다 — 북한산 우이동~백운대가 편집본 4.7km·180분인데
        # 원본 합산은 3km·53분으로 나온다.
        # `routes` 는 구간을 그래프로 이어 만든 들머리→정상 실경로이고,
        # `courses` 는 이름 묶음이라 하나의 경로가 아니라 여러 갈래의 합이다
        # (지리산 '중태리구간' 45km·22시간) — 그래서 상한으로 걸러 낸다.
        #
        # ⚠️ 여기서 `prev`(직전 생성물)를 쓰면 안 된다. 직전 실행이 만든 라우팅 코스를
        #    "손입력"으로 착각해 물려받아, 보정을 고쳐도 영원히 반영되지 않는다.
        #    실제로 한 번 그렇게 돼서 북한산이 0.75km·14분으로 남았다.
        source = curated.get(name) \
            or (trail.get("routes") if trail else None) \
            or (trail["courses"] if trail else [])
        courses = []
        for c in source:
            km, mins = round(c["distanceKm"], 2), int(c["durationMin"])
            if not (0 < km <= COURSE_MAX_KM and 0 < mins <= COURSE_MAX_MIN):
                continue
            courses.append({
                "name": c["name"],
                "distanceKm": km,
                "durationMin": mins,
                "difficulty": _course_difficulty(c, 3),
                "ascentM": None,            # 원본 GPX 고도가 전부 0 (함정 10)
            })
            if len(courses) >= 8:
                break

        trailheads = []
        for j, th in enumerate((trail["trailheads"] if trail else [])[:8], 1):
            label = (th.get("label") or "").strip()
            trailheads.append({
                "name": label if label and label != "시종점" else f"{name} 들머리 {j}",
                "lat": th["lat"], "lon": th["lon"],
                "transit": None, "parking": None,
            })

        # 봉우리: 3km 안에서 표고가 높은 순. POI 원본에 공통 조인키가 없어 좌표로 붙인다.
        #
        # ⚠️ 이 원본은 '문화자원 POI' 라 `aslAltide` 가 정상 높이가 아니라 **그 문화재가 놓인
        #    지점의 고도**다. 거르지 않으면 1,051m 가리산에 286m 짜리 '가리산' 봉우리가 붙는다.
        #    정상 부근만 남기려면 산 표고에 견줘 걸러야 한다.
        lo = max(200.0, elevation * 0.7)
        hi = elevation * 1.05
        peaks = []
        for pname, alt in nearby:
            if not (lo <= alt <= hi):
                continue
            # `frtrlNm` 은 봉우리명일 때도 있고 그냥 등산로명일 때도 있다.
            # '…봉' 으로 끝나는 것만 봉우리로 인정하고, 산 이름과 같은 건 버린다
            # (안 그러면 629m 관악산에 '자운암국기대(466m)', 675m 감악산에 '감악산(575m)'이 붙는다).
            if pname.endswith("봉") and pname.split("_")[0] != name:
                peaks.append({"name": pname, "elevation": int(round(alt))})
        peaks = sorted({p["name"]: p for p in peaks}.values(), key=lambda p: -p["elevation"])[:5]
        # 편집본이 있으면 그게 우선이다. POI 매칭은 837m 북한산에 보현봉(614m)·시단봉(600m)을
        # 대표 봉우리로 올려 놓는다 — 백운대·인수봉·만경대를 밀어낸다.
        if curated_peaks.get(name):
            peaks = curated_peaks[name]
        if peaks:
            stats["peaks"] += 1

        species = flagship.get(park_name.replace("국립공원", "")) if park_name else None
        species = species or (prev.get("species") if prev else []) or []
        if species:
            stats["species"] += 1

        story = (finfo.get("mntidetails") or "").strip() or (prev.get("story") if prev else None)
        if story:
            stats["story"] += 1

        photo_url = photo_credit = None
        if prev:
            photo_url, photo_credit = prev.get("photoURL"), prev.get("photoCredit")
        if want_photo and not photo_url:
            photo_url, photo_credit = fetch_photo(name, lat, lon)
        if photo_url:
            stats["photo"] += 1

        nx, ny = latlon_to_grid(lat, lon)
        mountains.append({
            "id": prev["id"] if prev else slug(name),
            "name": name,
            # 편집본이 있으면 그것, 없으면 **매번 다시 만든다.**
            # `prev` 를 쓰면 표고가 0이던 시절의 '강원' 같은 한 줄이 영원히 남는다(실제로 14개 그랬다).
            "tagline": curated_taglines.get(name) or _tagline(elevation, sido, src.get("top100", False), park_name),
            "story": story,
            "region": sido,
            "sigungu": sigungu or sido,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "elevation": elevation,
            "peaks": peaks,
            "parkType": park_type,
            "parkName": park_name,
            "isTop100": bool(src.get("top100")),
            "difficulty": _difficulty_from(elevation, courses),
            "courses": courses,
            "species": species,
            "trailheads": trailheads,
            "kmaMountainCode": None,        # 산악예보 미사용 — 단기예보 격자로 간다
            "grid": {"nx": nx, "ny": ny},
            "airRegion": _air_region(sido),
            "photoURL": photo_url,
            "photoCredit": photo_credit,
        })
        if len(mountains) >= limit:         # 목표를 채웠으면 남은 후보는 부르지 않는다
            break
        if i % 50 == 0:
            print(f"  {len(mountains)}/{limit} …", flush=True)

    # id 중복 방지 — 동명이산이 둘 다 뽑히면 뒤엣것에 꼬리를 붙인다.
    seen: dict[str, int] = {}
    for m in track(mountains, '산 정보'):
        if m["id"] in seen:
            seen[m["id"]] += 1
            m["id"] = f"{m['id']}{seen[m['id']]}"
        else:
            seen[m["id"]] = 1

    n = len(mountains)
    print(f"\n산 {n}개")
    if skipped_no_elev:
        print(f"  ⚠️ 표고를 못 구해 제외 {len(skipped_no_elev)}개: {', '.join(skipped_no_elev[:6])}")
    for k, label in [("trail", "등산로"), ("story", "산이야기"), ("peaks", "봉우리"),
                     ("species", "동식물"), ("park", "국립공원"), ("photo", "사진")]:
        print(f"  {label:<8} {stats[k]:>4}/{n} ({stats[k]/n:.0%})")

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": False,
        "mountains": mountains,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=TARGET)
    ap.add_argument("--no-photo", action="store_true", help="관광공사 호출 생략")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않는다")
    args = ap.parse_args()

    catalog = build(args.limit, not args.no_photo)
    if args.dry_run:
        return 0

    OUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")

    # 워크플로가 manifest 도 함께 커밋한다. 산 수가 안 맞으면 앱이 캐시를 갱신할 근거를 잃는다.
    man = OUT.parent / "manifest.json"
    manifest = json.loads(man.read_text()) if man.exists() else {"schemaVersion": 1}
    manifest["updatedAt"] = catalog["generatedAt"]
    manifest["mountains"] = len(catalog["mountains"])
    man.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print(f"\n{OUT.relative_to(ROOT)} — {OUT.stat().st_size/1024:.0f}KB · manifest 갱신")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
