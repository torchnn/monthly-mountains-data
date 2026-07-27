#!/usr/bin/env python3
"""개발용 표본 예보/맛집 파일을 앱 번들에 넣는다 (DEBUG 에서만 로드).

목적은 하나 — **파이프라인 출력 스키마를 Swift 디코더가 읽을 수 있는지 검증**하는 것.
이 계약이 어긋난 채로 파이프라인을 배포하면 앱이 조용히 빈 화면을 보여주게 된다.

식당 이름은 실제와 헷갈리지 않게 명백한 표본 문자열을 쓴다.

    python3 pipeline/make_dev_samples.py   # monthly_mountains_data 레포에서 실행
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 앱 레포는 형제 디렉터리에 있다고 가정한다. 스키마를 소유한 쪽(이 레포)이 표본을 만들어
# 앱 번들에 넣어야 계약이 갈라지지 않는다.
APP_REPO = ROOT.parent / "monthly_mountains"
RESOURCES = APP_REPO / "MonthlyMountains" / "Resources"
DATA_REPO = ROOT
SAMPLE_ID = "bukhansan"

KST = timezone(timedelta(hours=9))


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_forecast() -> dict:
    """collect_weather.py --dry-run 을 그대로 호출한다 — 표본과 실제 코드가 갈라지지 않게."""
    subprocess.run(
        [sys.executable, "pipeline/collect_weather.py", "--dry-run", "--only", SAMPLE_ID],
        cwd=DATA_REPO, check=True, capture_output=True,
    )
    payload = json.loads((DATA_REPO / "data" / "v1" / "forecast" / f"{SAMPLE_ID}.json").read_text("utf-8"))

    # 안전 배너와 혼잡도 보정 경로도 화면에서 확인할 수 있게 표본에 넣는다.
    now = datetime.now(KST)
    payload["alerts"] = [{"type": "폭염주의보", "message": "한낮 야외활동 자제", "issuedAt": _iso(now)}]
    payload["closures"] = [
        {"scope": "백운대 정상 구간", "reason": "낙석 위험 정비", "until": "2026-08-31"}
    ]
    return payload


def build_restaurants() -> dict:
    """맛집 스키마 표본. 실제 상호가 아님이 드러나게 이름을 짓는다."""
    now = datetime.now(KST)
    items = [
        {"name": "표본식당 가 (개발용)", "category": "한식 > 두부요리",
         "rating": 4.5, "reviewBucket": 1500, "signatureMenu": ["순두부", "도토리묵"],
         "lat": 37.6631, "lon": 127.0112, "walkMinutes": 6,
         "naverPlaceId": None, "trailhead": "우이분소"},
        {"name": "표본식당 나 (개발용)", "category": "한식 > 국수",
         "rating": 4.2, "reviewBucket": 500, "signatureMenu": ["잔치국수", "비빔국수"],
         "lat": 37.6640, "lon": 127.0098, "walkMinutes": 11,
         "naverPlaceId": None, "trailhead": "우이분소"},
        {"name": "표본카페 다 (개발용)", "category": "카페 > 디저트",
         "rating": 4.7, "reviewBucket": 3000, "signatureMenu": ["드립커피"],
         "lat": 37.6612, "lon": 127.0125, "walkMinutes": 4,
         "naverPlaceId": None, "trailhead": "우이분소"},
        {"name": "표본식당 라 (개발용)", "category": "한식 > 백반",
         "rating": None, "reviewBucket": None, "signatureMenu": [],
         "lat": 37.6655, "lon": 127.0090, "walkMinutes": 14,
         "naverPlaceId": None, "trailhead": "우이분소"},
    ]
    return {"mountainId": SAMPLE_ID, "updatedAt": _iso(now), "items": items}


def main() -> None:
    RESOURCES.mkdir(parents=True, exist_ok=True)
    targets = {
        f"dev_forecast_{SAMPLE_ID}.json": build_forecast(),
        f"dev_restaurants_{SAMPLE_ID}.json": build_restaurants(),
    }
    for name, payload in targets.items():
        path = RESOURCES / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")

    print("\nDEBUG 빌드에서 북한산 상세 화면을 열면 날씨·맛집·안전배너 섹션이 표본으로 렌더된다.")
    print("여기서 화면이 비면 파이프라인 스키마와 Swift 디코더가 어긋난 것이다.")


if __name__ == "__main__":
    main()
