#!/usr/bin/env python3
"""한글 산 이름 → 안정적인 slug(앱의 `Mountain.id`).

id 는 파일명(`forecast/<id>.json`)이자 즐겨찾기 저장 키다. **한 번 나간 id 는 바꾸면 안 된다** —
바꾸면 사용자의 즐겨찾기가 통째로 끊긴다. 그래서 `build_mountains.py` 는 기존
`mountains.json` 의 id 를 이름으로 찾아 그대로 승계하고, 새 산에만 여기를 쓴다.

국어의 로마자 표기법(개정)을 따르되 연음만 처리한다. 시드 24개를 완전히 재현하지는
못한다(시드는 설악산=seoraksan 처럼 연음을 적용한 것과 불암산=bulamsan 처럼 적용하지
않은 것이 섞여 있다) — 그래서 재현이 아니라 **승계**가 원칙이다.
"""
from __future__ import annotations

import re

BASE = 0xAC00
LAST = 0xD7A3

CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj",
       "ch", "k", "t", "p", "h"]
JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
        "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
# 종성. 인덱스 0 은 받침 없음.
JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "l", "l", "l", "l", "l", "l",
        "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]
# 받침이 다음 음절 초성('ㅇ')으로 넘어갈 때의 소리. 위 표는 음절 끝소리라 다르다.
JONG_LIAISON = ["", "g", "kk", "ks", "n", "nj", "nh", "d", "r", "lg", "lm", "lb",
                "ls", "lt", "lp", "lh", "m", "b", "bs", "s", "ss", "ng", "j",
                "ch", "k", "t", "p", "h"]


def _decompose(ch: str) -> tuple[int, int, int] | None:
    code = ord(ch)
    if not BASE <= code <= LAST:
        return None
    code -= BASE
    return code // 588, (code % 588) // 28, code % 28


def romanize(text: str) -> str:
    """한글 문자열 → 로마자. 한글이 아닌 문자는 버린다."""
    syllables = [_decompose(ch) for ch in text]
    out = []
    for i, syl in enumerate(syllables):
        if syl is None:
            continue
        cho, jung, jong = syl
        nxt = syllables[i + 1] if i + 1 < len(syllables) else None

        onset = CHO[cho]
        # 앞 음절 받침이 이 음절로 넘어왔으면 초성 'ㅇ'(빈 소리) 자리를 대신 채운다.
        prev = syllables[i - 1] if i > 0 else None
        if cho == 11 and prev and prev[2]:
            onset = JONG_LIAISON[prev[2]]

        coda = ""
        if jong:
            # 다음 음절이 'ㅇ' 으로 시작하면 받침은 그쪽으로 넘어가므로 여기서는 비운다.
            if not (nxt and nxt[0] == 11):
                coda = JONG[jong]

        out.append(onset + JUNG[jung] + coda)
    return "".join(out)


def slug(name: str) -> str:
    """산 이름 → id. '북한산_백운대' 처럼 밑줄이 붙은 원본 이름도 받는다."""
    base = name.split("_")[0].strip()
    s = romanize(base)
    s = re.sub(r"[^a-z0-9]+", "", s.lower())
    return s or re.sub(r"[^a-z0-9]+", "", name.lower())


if __name__ == "__main__":
    # 시드 이름으로 눈으로 확인 — 완전 일치가 목표가 아니라 '읽을 만한 안정적 키'가 목표다.
    for n in ["북한산", "설악산", "관악산", "청계산", "수락산", "인왕산", "불암산",
              "지리산", "한라산", "덕유산", "소백산", "치악산", "속리산", "계룡산",
              "내장산", "무등산", "팔공산", "월악산", "가야산", "주왕산", "마니산",
              "북한산_백운대", "도봉산", "오대산", "태백산"]:
        print(f"  {n:<12} → {slug(n)}")
