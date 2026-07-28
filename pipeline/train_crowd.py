#!/usr/bin/env python3
"""국립공원 실측 탐방객 통계로 혼잡도 계수를 학습한다.

입력: 국립공원공단 「국립공원 시간별 일별 탐방객 통계」(공공데이터포털 15107577)
      → data/raw/seoraksan_visitors.csv

**데이터 실측 확인 (2026-07 다운로드본):**
  · 제목에 '시간별'이 있지만 **시간 컬럼은 없다.** 컬럼은 순번·국립공원·사무소·
    관리지구·탐방지역·일자·전체 탐방객수 뿐이다 → 시간대 곡선은 이 데이터로 못 만든다.
  · **설악산 한 곳**만 담겨 있다(국립공원 컬럼이 있지만 값은 전부 설악산).
  · 대신 기간이 2018-01-01 ~ 2026-03-31 로 8년치, 탐방지역 23곳으로 세분돼 있어
    요일·월·공휴일 계수는 충분히 안정적으로 뽑힌다.

따라서 이 스크립트가 **학습하는 것**은 요일·월·공휴일 계수이고,
시간대 곡선은 별도 근거(일출·코스 소요시간 물리 모델)로 두고 여기서 건드리지 않는다.

    python3 pipeline/train_crowd.py [--max-mape 0.45]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "seoraksan_visitors.csv"

# 사람 방문이 아닌 항목 — 단위가 달라 합치면 계수가 왜곡된다.
EXCLUDE_AREAS = {"불법입산객", "점봉산 불법입산객", "설악동차량"}

# 코로나 기간은 방문 패턴이 달라 계수 추정에서 뺀다.
# (8년치라 포함해도 요일 계수는 거의 같지만, 월 계수는 눈에 띄게 흔들린다)
COVID_START, COVID_END = date(2020, 2, 1), date(2022, 4, 30)


def load_daily(path: Path) -> dict[date, int]:
    rows = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
    daily: collections.Counter[date] = collections.Counter()
    for r in rows:
        if r["탐방지역"] in EXCLUDE_AREAS:
            continue
        daily[date.fromisoformat(r["일자"])] += int(r["전체 탐방객수"] or 0)
    return dict(daily)


def mean_one(values: dict) -> dict:
    m = sum(values.values()) / len(values)
    return {k: v / m for k, v in values.items()}


def fit(days: dict[date, int], holidays: set[str]) -> dict:
    """요일·월·공휴일 계수를 순차적으로 뽑는다.

    공휴일은 요일 효과와 섞이므로(대체로 평일에 걸린다) **평일만** 놓고
    공휴일 vs 비공휴일을 비교해 분리한다.
    """
    dow_raw = collections.defaultdict(list)
    for d, v in days.items():
        dow_raw[d.weekday()].append(v)
    dow = mean_one({k: statistics.mean(v) for k, v in sorted(dow_raw.items())})

    # 월 계수는 요일 구성 편차를 제거한 뒤 뽑는다(어떤 달은 토요일이 5번 들기도 한다).
    mon_raw = collections.defaultdict(list)
    for d, v in days.items():
        mon_raw[d.month].append(v / dow[d.weekday()])
    mon = mean_one({k: statistics.mean(v) for k, v in sorted(mon_raw.items())})

    weekday_holiday, weekday_plain = [], []
    for d, v in days.items():
        if d.weekday() >= 5:
            continue
        adjusted = v / (dow[d.weekday()] * mon[d.month])
        (weekday_holiday if d.isoformat() in holidays else weekday_plain).append(adjusted)

    holiday_factor = (statistics.mean(weekday_holiday) / statistics.mean(weekday_plain)
                      if weekday_holiday and weekday_plain else 1.0)

    return {
        "dow": [round(dow[i], 4) for i in range(7)],
        "month": [round(mon[i], 4) for i in range(1, 13)],
        "holidayFactor": round(holiday_factor, 3),
        "sampleDays": len(days),
        "dailyMean": round(statistics.mean(days.values())),
    }


def validate(days: dict[date, int], model: dict, holidays: set[str]) -> float:
    """홀드아웃 MAPE. 마지막 1년을 남겨 계수의 예측력을 잰다."""
    cutoff = max(days) - timedelta(days=365)
    train = {d: v for d, v in days.items() if d <= cutoff}
    test = {d: v for d, v in days.items() if d > cutoff}
    if len(test) < 30:
        return float("nan")

    fitted = fit(train, holidays)
    base = statistics.mean(train.values())
    errors = []
    for d, actual in test.items():
        if actual <= 0:
            continue
        pred = base * fitted["dow"][d.weekday()] * fitted["month"][d.month - 1]
        if d.isoformat() in holidays:
            pred *= fitted["holidayFactor"]
        errors.append(abs(pred - actual) / actual)
    return statistics.median(errors)   # 평균 대신 중앙값 — 폭설·특보로 0에 가까운 날이 섞인다


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mape", type=float, default=0.45)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "v1" / "crowd_fit.json")
    args = ap.parse_args()

    if not RAW.exists():
        print(f"{RAW} 없음 — fetch_visitor_stats.py 를 먼저 돌리세요.", file=sys.stderr)
        return 2

    holidays = set(json.loads((ROOT / "pipeline" / "holidays.json").read_text("utf-8"))) \
        if (ROOT / "pipeline" / "holidays.json").exists() else set()

    daily = load_daily(RAW)
    clean = {d: v for d, v in daily.items() if not (COVID_START <= d <= COVID_END)}

    fitted = fit(clean, holidays)
    mape = validate(clean, fitted, holidays)
    fitted["holdoutMedianAPE"] = round(mape, 4)
    fitted["source"] = "국립공원공단 설악산 일별 탐방객 통계 2018-2026 (코로나기 제외)"
    fitted["note"] = "시간대 곡선은 이 데이터로 학습 불가 — 원본에 시간 컬럼이 없음"

    print(f"표본 {fitted['sampleDays']:,}일 · 일평균 {fitted['dailyMean']:,}명")
    print("요일:", " ".join(f"{n}{v:.2f}" for n, v in zip("월화수목금토일", fitted["dow"])))
    print("월  :", " ".join(f"{i+1}월{v:.2f}" for i, v in enumerate(fitted["month"])))
    print(f"공휴일 계수 {fitted['holidayFactor']} · 홀드아웃 중앙 오차 {mape:.1%}")

    if mape > args.max_mape:
        print(f"\n오차가 임계치({args.max_mape:.0%})를 넘어 기존 모델을 유지합니다.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fitted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
