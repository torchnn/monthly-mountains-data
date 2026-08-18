"""진행률을 한 줄씩 찍는다.

로그만 보고 "지금 몇 %인지" 알 수 있게 하려고 넣었다. 2026-08-19 에 weekly-batch 가
한 시간 도는 동안 진척을 못 봐서, 살았는지 죽었는지 CPU 시간으로 확인해야 했다.

stderr 로 찍는다 — stdout 은 파이썬이 모아 뒀다가 한꺼번에 내보내는 일이 있다.
(`run.sh` 가 PYTHONUNBUFFERED=1 을 주지만, 직접 돌릴 때도 보이게 하려고.)
"""
from __future__ import annotations

import sys
import time


def track(items, label: str = "", every: int | None = None, out=sys.stderr):
    """`for x in track(mountains, "예보"):` 처럼 감싼다.

    every 를 안 주면 5% 마다(최소 1개) 찍는다. 마지막 한 줄은 항상 찍는다.
    """
    seq = list(items)
    total = len(seq)
    if total == 0:
        print(f"  {label} 0개 — 할 일이 없습니다", file=out, flush=True)
        return
    step = every or max(1, total // 20)
    t0 = time.time()
    for i, x in enumerate(seq, 1):
        yield x
        if i % step == 0 or i == total:
            el = time.time() - t0
            eta = (el / i) * (total - i)
            print(f"  {label} {i}/{total} ({i * 100 // total}%)"
                  f" · 경과 {int(el // 60)}분 {int(el % 60)}초"
                  + (f" · 남은 예상 {int(eta // 60)}분" if i < total else " · 끝"),
                  file=out, flush=True)
