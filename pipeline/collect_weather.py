#!/usr/bin/env python3
"""산별 날씨·대기질·특보를 모아 data/v1/forecast/<id>.json 으로 쓴다.

호출량 (300개 산 기준, 3시간 주기 = 하루 8회):
  기상청 산악예보/단기예보  300 × 8 = 2,400/일
  에어코리아(시도 단위)      17 × 8 =   136/일
  기상특보(전국 일괄)         1 × 8 =     8/일
  ────────────────────────────────────
  계 약 2,550/일 — 공공데이터포털 개발계정 10,000/일 한도의 25%

키 없이 스키마만 확인하려면:
    python3 collect_weather.py --dry-run --only bukhansan
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "v1"

SERVICE_KEY = os.environ.get("DATA_GO_KR_KEY", "")
TIMEOUT = 10
RETRIES = 3

KMA_BASE = "https://apis.data.go.kr/1360000"
AIRKOREA = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"

# 기상청 SKY/PTY 코드 → 앱의 Sky enum
SKY_CODE = {"1": "clear", "3": "partlyCloudy", "4": "cloudy"}
PTY_CODE = {"1": "rain", "2": "sleet", "3": "snow", "4": "rain", "5": "rain", "6": "sleet", "7": "snow"}


def get_json(url: str, params: dict) -> dict | None:
    """공공데이터포털은 간헐적으로 XML 에러나 빈 응답을 준다 — 조용히 재시도하고 포기한다."""
    params = {**params, "serviceKey": SERVICE_KEY, "dataType": "JSON"}
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code != 200:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r.json()
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 재시도 후 넘어간다
            if attempt == RETRIES - 1:
                print(f"  ! 실패 {url.rsplit('/', 1)[-1]}: {exc}", file=sys.stderr)
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def _items(payload: dict | None) -> list[dict]:
    try:
        return payload["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return []


def base_datetime(now: datetime) -> tuple[str, str]:
    """단기예보 발표 시각(02·05·08·11·14·17·20·23시) 중 직전 것."""
    slots = [2, 5, 8, 11, 14, 17, 20, 23]
    ref = now - timedelta(minutes=15)  # 발표 직후엔 아직 안 올라와 있다
    hour = max((h for h in slots if h <= ref.hour), default=None)
    if hour is None:
        ref -= timedelta(days=1)
        hour = 23
    return ref.strftime("%Y%m%d"), f"{hour:02d}00"


def fetch_village_forecast(nx: int, ny: int, now: datetime) -> list[dict]:
    base_date, base_time = base_datetime(now)
    payload = get_json(
        f"{KMA_BASE}/VilageFcstInfoService_2.0/getVilageFcst",
        {"numOfRows": 1000, "pageNo": 1, "base_date": base_date, "base_time": base_time,
         "nx": nx, "ny": ny},
    )
    return _items(payload)


def parse_forecast(items: list[dict]) -> dict:
    """기상청 항목(카테고리별 행)을 시간별/일별로 접는다."""
    by_slot: dict[tuple[str, str], dict[str, str]] = {}
    for it in items:
        key = (it.get("fcstDate", ""), it.get("fcstTime", ""))
        by_slot.setdefault(key, {})[it.get("category", "")] = it.get("fcstValue", "")

    hourly, daily = [], {}
    for (date, hhmm), values in sorted(by_slot.items()):
        if not date or not hhmm:
            continue
        stamp = datetime.strptime(date + hhmm, "%Y%m%d%H%M").replace(tzinfo=KST)

        temp = _as_float(values.get("TMP"))
        pop = int(_as_float(values.get("POP")) or 0)
        pcp = _parse_pcp(values.get("PCP", "강수없음"))
        sky = PTY_CODE.get(values.get("PTY", "0")) or SKY_CODE.get(values.get("SKY", ""), "unknown")

        if temp is not None:
            hourly.append({"time": _iso(stamp), "tempC": temp, "pop": pop, "pcpMm": pcp, "sky": sky})

        day = daily.setdefault(date, {"temps": [], "pops": [], "skies": [],
                                      "min": _as_float(values.get("TMN")),
                                      "max": _as_float(values.get("TMX"))})
        if temp is not None:
            day["temps"].append(temp)
        day["pops"].append(pop)
        day["skies"].append(sky)
        # TMN/TMX 는 하루 한 슬롯에만 실려 온다
        if values.get("TMN"):
            day["min"] = _as_float(values["TMN"])
        if values.get("TMX"):
            day["max"] = _as_float(values["TMX"])

    daily_out = []
    for date, day in sorted(daily.items()):
        if not day["temps"]:
            continue
        stamp = datetime.strptime(date, "%Y%m%d").replace(tzinfo=KST)
        daily_out.append({
            "date": _iso(stamp),
            "minC": day["min"] if day["min"] is not None else min(day["temps"]),
            "maxC": day["max"] if day["max"] is not None else max(day["temps"]),
            "pop": max(day["pops"]) if day["pops"] else 0,
            "sky": _dominant_sky(day["skies"]),
        })

    current = None
    if hourly:
        first = hourly[0]
        current = {"tempC": first["tempC"], "feelsLikeC": None, "humidity": None,
                   "windMs": None, "sky": first["sky"]}

    return {"current": current, "hourly": hourly[:24], "daily": daily_out[:5]}


def _dominant_sky(skies: list[str]) -> str:
    """하루 대표 하늘상태 — 강수가 한 번이라도 있으면 그걸 우선한다."""
    for wet in ("snow", "sleet", "rain"):
        if wet in skies:
            return wet
    return max(set(skies), key=skies.count) if skies else "unknown"


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_pcp(raw: str) -> float:
    """기상청 강수량은 '강수없음' / '1.0mm' / '30.0~50.0mm' 같은 문자열로 온다."""
    if not raw or "없음" in raw:
        return 0.0
    digits = "".join(c for c in raw.split("~")[0] if c.isdigit() or c == ".")
    return float(digits) if digits else 0.0


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_air_by_region() -> dict[str, dict]:
    """시도별 실시간 대기질. 산마다 부르지 않고 17개 시도만 부른다."""
    regions = ["서울", "인천", "경기", "강원", "충북", "충남", "대전", "세종",
               "전북", "전남", "광주", "경북", "경남", "대구", "울산", "부산", "제주"]
    out = {}
    for region in regions:
        items = _items(get_json(AIRKOREA, {"sidoName": region, "numOfRows": 100,
                                           "pageNo": 1, "ver": "1.3"}))
        pm10 = [int(v) for v in (i.get("pm10Value") for i in items) if _is_int(v)]
        pm25 = [int(v) for v in (i.get("pm25Value") for i in items) if _is_int(v)]
        if not pm10:
            continue
        avg10 = round(sum(pm10) / len(pm10))
        out[region] = {
            "pm10": avg10,
            "pm25": round(sum(pm25) / len(pm25)) if pm25 else None,
            "grade": _pm10_grade(avg10),
        }
    return out


def _is_int(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _pm10_grade(pm10: int) -> int:
    """환경부 기준: 0-30 좋음 / 31-80 보통 / 81-150 나쁨 / 151+ 매우나쁨"""
    return 1 if pm10 <= 30 else 2 if pm10 <= 80 else 3 if pm10 <= 150 else 4


def fetch_alerts() -> dict[str, list[dict]]:
    """기상특보를 전국 일괄 조회해 지역명으로 인덱싱한다."""
    now = datetime.now(KST)
    payload = get_json(
        f"{KMA_BASE}/WthrWrnInfoService/getWthrWrnList",
        {"numOfRows": 100, "pageNo": 1, "stnId": 108,
         "fromTmFc": (now - timedelta(days=1)).strftime("%Y%m%d"),
         "toTmFc": now.strftime("%Y%m%d")},
    )
    by_region: dict[str, list[dict]] = {}
    for item in _items(payload):
        title = item.get("title") or item.get("warnVar", "")
        area = item.get("areaName", "")
        if not title:
            continue
        by_region.setdefault(area, []).append(
            {"type": title, "message": item.get("command"), "issuedAt": None}
        )
    return by_region


def sample_forecast(mountain: dict, now: datetime) -> dict:
    """--dry-run 용. 실제 API 응답과 **같은 스키마**로 그럴듯한 값을 만든다.
    앱의 Swift 디코더가 이 파일을 읽을 수 있으면 스키마 계약이 맞는 것이다."""
    seed = sum(ord(c) for c in mountain["id"])
    hourly, daily = [], []
    for h in range(24):
        stamp = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h)
        temp = 22 + 6 * ((seed + h) % 7) / 6
        hourly.append({"time": _iso(stamp), "tempC": round(temp, 1),
                       "pop": (seed + h * 7) % 60, "pcpMm": 0.0,
                       "sky": ["clear", "partlyCloudy", "cloudy"][(seed + h) % 3]})
    for d in range(5):
        stamp = (now + timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        daily.append({"date": _iso(stamp), "minC": 19.0 + (seed + d) % 4,
                      "maxC": 27.0 + (seed + d) % 5, "pop": (seed + d * 13) % 70,
                      "sky": ["clear", "partlyCloudy", "cloudy", "rain"][(seed + d) % 4]})
    return {
        "mountainId": mountain["id"],
        "updatedAt": _iso(now),
        "weather": {"current": {"tempC": hourly[0]["tempC"], "feelsLikeC": None,
                                "humidity": 62, "windMs": 2.1, "sky": hourly[0]["sky"]},
                    "hourly": hourly, "daily": daily},
        "air": {"pm10": 20 + seed % 60, "pm25": 10 + seed % 30, "grade": 1 + seed % 3},
        "alerts": [],
        "closures": [],
        "crowdDaily": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 스키마 확인용 샘플 생성")
    parser.add_argument("--only", help="특정 산 id 하나만")
    parser.add_argument("--out", type=Path, default=DATA, help="출력 디렉터리")
    args = parser.parse_args()

    if not args.dry_run and not SERVICE_KEY:
        print("DATA_GO_KR_KEY 가 없습니다. --dry-run 으로 스키마만 확인하거나 키를 설정하세요.",
              file=sys.stderr)
        return 2

    catalog_path = args.out / "mountains.json"
    if not catalog_path.exists():
        print(f"{catalog_path} 없음 — build_mountains.py 를 먼저 돌리세요.", file=sys.stderr)
        return 2
    mountains = json.loads(catalog_path.read_text(encoding="utf-8"))["mountains"]
    if args.only:
        mountains = [m for m in mountains if m["id"] == args.only]

    now = datetime.now(KST)
    out_dir = args.out / "forecast"
    out_dir.mkdir(parents=True, exist_ok=True)

    air_by_region = {} if args.dry_run else fetch_air_by_region()
    alerts_by_region = {} if args.dry_run else fetch_alerts()

    written = 0
    for mountain in mountains:
        if args.dry_run:
            payload = sample_forecast(mountain, now)
        else:
            items = fetch_village_forecast(mountain["grid"]["nx"], mountain["grid"]["ny"], now)
            if not items:
                continue  # 이번 회차는 건너뛴다 — 앱은 직전 파일을 계속 쓴다
            region = mountain["airRegion"]
            payload = {
                "mountainId": mountain["id"],
                "updatedAt": _iso(now),
                "weather": parse_forecast(items),
                "air": air_by_region.get(region),
                "alerts": _match_alerts(alerts_by_region, mountain),
                "closures": [],   # TODO: 국립공원 통제정보 연동
                "crowdDaily": [], # train-crowd 가 채운다
            }

        (out_dir / f"{mountain['id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        written += 1

    _update_manifest(args.out, now, forecast_count=written)
    print(f"forecast {written}/{len(mountains)}개 작성" + (" (dry-run)" if args.dry_run else ""))
    return 0


def _match_alerts(by_region: dict[str, list[dict]], mountain: dict) -> list[dict]:
    """특보 지역명은 '서울', '경기북부' 처럼 와서 시도명 부분일치로 맞춘다."""
    hits = []
    for area, alerts in by_region.items():
        if mountain["region"] in area or area in mountain["sigungu"]:
            hits.extend(alerts)
    return hits


def _update_manifest(root: Path, now: datetime, **counts) -> None:
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest["schemaVersion"] = 1
    manifest["updatedAt"] = _iso(now)
    manifest.update(counts)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
