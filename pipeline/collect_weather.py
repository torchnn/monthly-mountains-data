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

# 산 하나가 완전히 실패하면 3회 × 10초 + 대기(1.5·3초) = **약 34초**를 태운다.
# 포털이 통째로 죽으면 300산 × 34초 = 175분이라 20분 상한에 걸려 끊기고,
# 그때는 커밋 단계가 skip 되어 **그 회차가 통째로 없어진다**.
# 2026-08-17 21:44 회차가 정확히 그랬다 — 로그가 34~35초 간격의 connect timeout 으로만 채워졌다.
#
# 연속으로 이만큼 실패하면 그 산의 문제가 아니라 포털이 죽은 것이다.
# 300번 확인해 볼 이유가 없으므로 그만두고, 그때까지 받은 것만 저장한다.
# 12산 = 약 7분 — 일시적 흔들림과 진짜 장애를 가르기에 충분하고 상한 안에 들어온다.
# (2026-08-18 실측으로 확인: 이 구간은 6분 24초였다. 문제는 이 앞이었다 — 아래 참고.)
OUTAGE_STREAK = 12

# 산 루프에 닿기 **전**에 도는 대기질·특보에도 같은 장치가 필요하다.
# 이쪽은 시도 17곳을 각각 부르므로 포기 없이 두면 9분 19초를 태운다(실측).
# 셋이 내리 실패하면 그 지역 문제가 아니라 포털이 죽은 것이다 — 약 1분 45초면 안다.
PORTAL_DOWN_STREAK = 3

# 예보가 이만큼 낡으면 그때 빨간불을 켠다.
#
# 한 회차를 놓치는 것 자체는 사고가 아니다 — 3시간 뒤 회차가 이어받고, 앱은 그동안
# 직전 파일을 그대로 쓴다. 그런데도 회차마다 실패로 처리하면 포털이 한 번 흔들릴 때마다
# 메일이 날아온다(하루 8통). 사람이 할 수 있는 일이 없는 알림은 곧 안 보게 된다.
# 세 회차(9시간)를 내리 못 받으면 그건 일시적 흔들림이 아니라 봐야 할 일이다.
STALE_AFTER_HOURS = 9

# 연속 실패만으로는 부족하다. 성공과 실패가 섞이면 streak 이 계속 끊겨
# 150산이 34초씩 실패해도 85분을 태운다. 그래서 벽시계로도 막는다.
# 잡 상한이 20분이고 평시 실측이 9~13분이므로, 14분에서 스스로 끊고
# 받은 것을 저장한다 — 러너가 끊으면 저장도 커밋도 못 한다.
DEADLINE_SEC = 14 * 60

KMA_BASE = "https://apis.data.go.kr/1360000"
AIRKOREA = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"

# 기상청 SKY/PTY 코드 → 앱의 Sky enum
SKY_CODE = {"1": "clear", "3": "partlyCloudy", "4": "cloudy"}
PTY_CODE = {"1": "rain", "2": "sleet", "3": "snow", "4": "rain", "5": "rain", "6": "sleet", "7": "snow"}


def get_json(url: str, params: dict, fmt_param: str = "dataType") -> dict | None:
    """공공데이터포털은 간헐적으로 XML 에러나 빈 응답을 준다 — 조용히 재시도하고 포기한다.

    ⚠️ 응답 형식을 고르는 파라미터 이름이 기관마다 다르다.
       기상청은 `dataType=JSON`, 에어코리아는 `returnType=json` 이다.
       틀린 이름을 보내면 **에러가 아니라 XML 이 200 으로 돌아와서**
       `r.json()` 이 "Expecting value: line 1 column 1" 로 죽는다 —
       인증키 문제로 착각하기 딱 좋으니 호출부에서 반드시 맞춰 줄 것.
    """
    params = {**params, "serviceKey": SERVICE_KEY, fmt_param: "JSON" if fmt_param == "dataType" else "json"}
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
    """`response.body.items` 를 목록으로 꺼낸다.

    기관마다 모양이 다르다 — 기상청은 `items: {item: [...]}`, 에어코리아는 `items: [...]`.
    한쪽만 가정하면 다른 쪽에서 조용히 빈 목록이 나와, 값이 안 채워지는데도
    에러 로그가 하나도 안 남는다(대기질이 계속 null 이던 원인).
    """
    try:
        items = payload["response"]["body"]["items"]
    except (KeyError, TypeError):
        return []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):     # 결과가 1건이면 리스트가 아니라 객체로 온다
        return [items]
    return items if isinstance(items, list) else []


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
    # ⚠️ **여기에도 포기 장치가 필요하다.** 2026-08-18 01:54 회차에서 이 함수 하나가
    # **9분 19초**를 태웠다 — 17개 시도를 각각 부르는데 포털이 죽어 전부 34초씩 실패했다.
    # 그다음 특보 35초, 그리고 나서야 산 루프의 차단기가 6분 24초를 더 쓴다. 합쳐 17분 29초,
    # 잡 상한 20분에 아슬아슬하게 붙었다. 산 루프만 막아 놓고 앞을 안 본 것이 실수였다.
    #
    # 게다가 여기서 이미 알 수 있다 — 시도 셋이 내리 실패하면 그건 그 지역 문제가 아니라
    # 포털이 죽은 것이고, 남은 14개와 산 300개를 두드려 볼 이유가 없다.
    dead_streak = 0
    for region in regions:
        payload = get_json(AIRKOREA, {"sidoName": region, "numOfRows": 100,
                                      "pageNo": 1, "ver": "1.3"},
                           fmt_param="returnType")
        if payload is None:
            dead_streak += 1
            if dead_streak >= PORTAL_DOWN_STREAK:
                print(f"  !! 시도 {PORTAL_DOWN_STREAK}곳 연속 실패 — 포털이 죽었다고 보고"
                      f" 대기질 수집을 그만둡니다({len(out)}/{len(regions)}곳).", file=sys.stderr)
                break
            continue
        dead_streak = 0
        items = _items(payload)
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


def fetch_alerts() -> list[dict]:
    """지금 **발효 중인** 기상특보를 종류별로 가져온다.

    ⚠️ `getWthrWrnList` 를 쓰면 안 된다. 그건 통보문 '목록'이라
       발표·변경·해제가 뒤섞인 이력이 오고, 응답 필드가 `stnId/title/tmFc/tmSeq`뿐이라
       **지역 정보가 아예 없다.** 지역 없이 매칭하면 전국 특보 30건이 모든 산에 붙는다
       (실제로 북한산 예보에 풍랑주의보가 들어갔다).

    `getPwnStatus` 의 `t6` 이 현재 발효 현황을 이런 자유 텍스트로 준다:

        o 강풍주의보 : 전라남도(거문도.초도), 제주도(제주도산지, 제주시동부), 울릉도.독도
        o 풍랑경보 : 남해동부바깥먼바다, 제주도앞바다(...)

    줄마다 '종류 : 지역목록' 이므로 그대로 갈라 쓴다.
    """
    now = datetime.now(KST)
    payload = get_json(
        f"{KMA_BASE}/WthrWrnInfoService/getPwnStatus",
        {"numOfRows": 10, "pageNo": 1, "stnId": 108,
         "fromTmFc": (now - timedelta(days=1)).strftime("%Y%m%d"),
         "toTmFc": now.strftime("%Y%m%d")},
    )
    items = _items(payload)
    if not items:
        return []

    status = str(items[0].get("t6") or "")
    alerts = []
    for line in status.splitlines():
        line = line.strip()
        if not line.startswith("o ") or " : " not in line:
            continue
        kind, areas = line[2:].split(" : ", 1)
        kind = kind.strip()
        if kind == "없음" or not areas.strip():
            continue
        alerts.append({"type": kind, "areas": areas.strip()})
    return alerts


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
    active_alerts = [] if args.dry_run else fetch_alerts()

    written = 0
    miss_streak = 0
    outage = False
    deadline = time.monotonic() + DEADLINE_SEC
    for mountain in mountains:
        if not args.dry_run and time.monotonic() > deadline:
            print(f"  !! {DEADLINE_SEC // 60}분을 넘겨 여기서 멈춥니다"
                  f" ({written}/{len(mountains)}개 저장). 3시간 뒤 회차가 이어받습니다.",
                  file=sys.stderr)
            outage = True
            break
        if args.dry_run:
            payload = sample_forecast(mountain, now)
        else:
            items = fetch_village_forecast(mountain["grid"]["nx"], mountain["grid"]["ny"], now)
            if not items:
                # 이번 산은 건너뛴다 — 앱은 직전 파일을 계속 쓴다.
                miss_streak += 1
                if miss_streak >= OUTAGE_STREAK:
                    print(f"  !! {OUTAGE_STREAK}산 연속 실패 — 포털이 죽은 것으로 보고 여기서 멈춥니다"
                          f" ({written}/{len(mountains)}개 저장). 3시간 뒤 회차가 이어받습니다.",
                          file=sys.stderr)
                    outage = True
                    break
                continue
            miss_streak = 0
            region = mountain["airRegion"]
            payload = {
                "mountainId": mountain["id"],
                "updatedAt": _iso(now),
                "weather": parse_forecast(items),
                "air": air_by_region.get(region),
                "alerts": _match_alerts(active_alerts, mountain),
                "closures": [],   # TODO: 국립공원 통제정보 연동
                "crowdDaily": [], # train-crowd 가 채운다
            }

        (out_dir / f"{mountain['id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        written += 1

    # ⚠️ **한 건도 못 받은 회차가 매니페스트를 더 나쁘게 만들면 안 된다.**
    # 2026-08-18 01:54 회차가 `forecast_count: 0` 을 배포본에 써 넣었다 — 예보 파일 300개는
    # 그대로 있는데 숫자만 0 이라 그걸 보는 사람이 속는다. 읽는 코드가 없어 기능 영향은
    # 없었지만, 배포본에 틀린 값을 올리는 것 자체가 버그다.
    # 실제로 쓴 회차만 숫자와 시각을 갱신하고, 못 쓴 회차는 앞의 값을 그대로 둔다.
    prev = _manifest(args.out)
    counts: dict = {}
    if written > 0:
        counts["forecast_count"] = written
        counts["forecastUpdatedAt"] = _iso(now)
    else:
        for key in ("forecast_count", "forecastUpdatedAt"):
            if key in prev:
                counts[key] = prev[key]
    _update_manifest(args.out, now, **counts)
    print(f"forecast {written}/{len(mountains)}개 작성" + (" (dry-run)" if args.dry_run else ""))

    if not outage:
        return 0

    # 받은 것은 저장하고 커밋까지 간다(부분 진척은 버리지 않는다).
    #
    # **빨간불은 낡았을 때만 켠다.** 한 회차를 놓치는 것 자체는 사고가 아니다 —
    # 3시간 뒤 회차가 이어받고 앱은 그동안 직전 파일을 쓴다. 그런데 회차마다 실패로
    # 처리하면 포털이 한 번 흔들릴 때마다 메일이 온다(하루 8통). 사람이 할 수 있는 일이
    # 없는 알림은 곧 안 보게 되고, 그러면 진짜 장애도 같이 묻힌다.
    stale_h = _hours_since(prev.get("forecastUpdatedAt"))
    if stale_h is None:
        print("포털 장애로 회차를 중단했습니다. (마지막 성공 시각 기록이 아직 없어 이번은 넘어갑니다)",
              file=sys.stderr)
        return 0
    if stale_h < STALE_AFTER_HOURS:
        print(f"포털 장애로 회차를 중단했습니다. 마지막 성공이 {stale_h:.1f}시간 전이라"
              f" 아직 {STALE_AFTER_HOURS}시간 안입니다 — 다음 회차가 이어받습니다.", file=sys.stderr)
        return 0
    print(f"포털 장애가 이어지고 있습니다. 마지막 성공이 {stale_h:.1f}시간 전 —"
          f" {STALE_AFTER_HOURS}시간을 넘겼습니다.", file=sys.stderr)
    return 3


# 바다에만 내리는 특보 — 산에는 뜨면 안 된다. 한라산이 '제주도앞바다'에 걸리는 걸 막는다.
MARINE_ALERTS = ("풍랑", "폭풍해일", "해일")


def _match_alerts(alerts: list[dict], mountain: dict) -> list[dict]:
    """이 산에 실제로 걸리는 특보만 남긴다.

    지역 문자열은 '전라남도(거문도.초도), 제주도(제주도산지, 제주시동부)' 처럼 오므로
    시도명 부분일치로 본다. 빈 문자열은 무엇에나 매칭되므로 반드시 먼저 걸러낸다 —
    이전 구현이 정확히 그 이유로 전국 특보를 전부 붙였다.
    """
    region = (mountain.get("region") or "").strip()
    sigungu = (mountain.get("sigungu") or "").strip()
    if not region:
        return []

    hits = []
    for alert in alerts:
        if any(m in alert["type"] for m in MARINE_ALERTS):
            continue
        areas = alert["areas"]
        # '서울' → '서울특별시'·'서울' 둘 다 잡히도록 시도명 앞 두 글자로 본다.
        key = region[:2]
        if key and (key in areas or (sigungu and sigungu.split()[-1] in areas)):
            hits.append({"type": alert["type"], "message": alert["areas"], "issuedAt": None})
    return hits


def _manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _hours_since(stamp: str | None) -> float | None:
    """`_iso` 가 쓴 시각으로부터 몇 시간 지났는지. 못 읽으면 None."""
    if not stamp:
        return None
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def _update_manifest(root: Path, now: datetime, **counts) -> None:
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest["schemaVersion"] = 1
    manifest["updatedAt"] = _iso(now)
    manifest.update(counts)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
