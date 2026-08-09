# 인수인계 — monthly-mountains-data (2026-08-10)

앱이 읽는 정적 데이터를 만들어 GitHub Pages 로 배포하는 레포.
전체 그림은 [앱 레포의 docs/HANDOFF.md](https://github.com/torchnn/monthly-mountains/blob/main/docs/HANDOFF.md).

## 🚧 [PR #2](https://github.com/torchnn/monthly-mountains-data/pull/2) 가 열려 있다 — 머지가 곧 배포다

머지하는 순간 **Pages 가 300개를 서빙**하고, 그때부터 signals 수집기가 300개를 돌고,
예보가 3시간마다 300개 파일을 커밋한다(회당 0.9MB). 배포된 마스터는 아직 24개다.
세 레포 중 **이걸 가장 먼저** 머지해야 한다(로스터가 여기서 나온다).

✅ 웹 사진 103장 저작권 검토는 2026-08-10 에 끝났다(문제 없음).

⚠️ **이 레포의 main 은 스스로 움직인다.** `daily-signals`·`forecast-weather` 가 main 에 직접
커밋하므로 작업 브랜치는 가만히 있어도 뒤처지고 생성물에서 충돌한다 — 실제로 PR 을 열자마자
`data/v1/signals/*.json` 25개가 충돌했다. 해소법은 앱 레포 HANDOFF **함정 20**.
**브랜치는 짧게 살리고 빨리 머지할 것.**

## ✅ `DATA_GO_KR_KEY` 등록 완료 (2026-08-08)

**디코딩 키**를 등록해야 한다 — `collect_weather.py` 가 `serviceKey` 를 requests params 로
넘겨 다시 URL 인코딩하므로, 인코딩 키를 넣으면 이중 인코딩으로 인증에 실패한다.

```bash
gh secret set DATA_GO_KR_KEY --repo torchnn/monthly-mountains-data --body "<디코딩 키>"
```

**세 워크플로 모두 크론이 켜져 있고 미구현 스크립트는 없다**(2026-08-09 기준).

### 파일데이터 2건 — 변환본을 커밋해 뒀다

원본은 다운로드에 로그인이 필요해 CI 가 못 받는다. `data/raw/`(gitignore)에 풀고
가벼운 JSON 으로 바꿔 레포에 넣었다. **CI 는 변환본만 읽는다.**

| 원본 | 스크립트 | 산출물 | 상태 |
|---|---|---|---|
| 전국등산로표준데이터 (265MB) | `build_trail_index.py` | `pipeline/trails.json` (1.9MB) | ✅ 산 2,932개 · 코스 7,759개 |
| 국립공원 공원경계 (SHP) | `build_park_index.py` | `pipeline/park_buffer_3km.json` | ⚠️ 경계가 아니라 **3km 버퍼** |

```bash
unzip mountain.zip -d data/raw/trails
python3 pipeline/build_trail_index.py       # → trails.json
python3 pipeline/build_trail_index.py --match  # 시드 매칭률 확인 (18/24)
python3 pipeline/build_park_index.py        # → park_buffer_3km.json
python3 pipeline/geo.py                     # 좌표 변환 자기검사 (GPX 정답 대비 0.01cm)
```

⚠️ 세 가지 함정이 있다. 앱 레포 HANDOFF 의 **함정 10·11·12** 를 반드시 읽을 것:
등산로 GPX 고도는 전부 0 · 공원경계는 3km 버퍼 · 등산로 원본에 동명이산이 있다.

## 현재 배포 상태

```
https://torchnn.github.io/monthly-mountains-data/data/v1/
  manifest.json       ✅
  mountains.json      ✅ 300개 (`seed: false`) — build_mountains.py 산출
                         사진 273 · 코스 292 · story 296
  crowd_model.json    ✅ 실측 학습본 · 산 300/300 · 월 곡선 237종
  photos/<id>.jpg     ✅ 웹 수집분 103장 (23MB · 장당 222KB) — 저작권 검토 대상
  signals/<id>.json   ✅ 300개 (signals 레포가 push)
  restaurants/<id>.json ✅ (signals 레포가 push · 네이버 기준 + 구글 단건 보강)
  forecast/<id>.json  ✅ 3시간마다 갱신
```

### 사진 — 원천 두 개, 권리 상태가 다르다

| 원천 | 개수 | 권리 |
|---|---:|---|
| 관광공사 `firstimage` | 170 | ✅ 공공누리 1유형 — 재배포 가능 |
| 웹(DuckDuckGo 이미지) | 103 | ✅ 제3자 저작물 — **2026-08-10 사람이 전수 검토, 문제 없음** |
| 없음 | 27 | 앱이 능선 일러스트로 떨어진다 |

```bash
python3 pipeline/fetch_web_photos.py            # 사진 없는 산만, 산당 질의 1회
python3 pipeline/fetch_web_photos.py --review   # 출처 목록 (저작권 검토용)
python3 pipeline/fetch_web_photos.py --apply-only   # 대장 → 마스터 반영만 (복구용)
```

⚠️ `--apply-only` 가 있는 이유: 죽인 줄 알았던 `build_mountains.py` 가 나중에 끝나면서
마스터를 덮어 사진 URL 103개가 사라진 적이 있다. `pkill` 은 래퍼만 죽인다.
대장(`pipeline/web_photos.json`)을 따로 두는 것도 그래서다. 앱 레포 HANDOFF **함정 15·16·17** 참고.

⚠️ **Pages 는 레포 루트를 서빙**하므로 URL 에 `data/` 가 들어간다.
앱의 `DataStore.remoteBase` 가 이 경로와 맞아야 한다.

## 워크플로

| 파일 | 주기 | 상태 |
|---|---|---|
| `build-mountains.yml` | 매월 1일 03:00 KST | ✅ 크론 활성 |
| `forecast-weather.yml` | 3시간마다 | ✅ 크론 활성 |
| `train-crowd.yml` | 매주 월 04:00 KST + signals push | ✅ 크론 활성 |
| `publish-pages.yml` | push | ❌ 미작성 (지금은 Pages 기본 동작에 의존) |

**미구현 스크립트 없음.** 2026-08-09 에 `fetch_visitor_stats.py` 까지 작성해
`fetch → train_crowd` 체인이 끝까지 돈다(계수가 기존 학습값과 일치하는 것으로 확인).

⚠️ 산 300개면 `forecast-weather` 가 회차마다 300개 파일을 커밋한다(회당 0.9MB · 하루 8회).
레포가 꾸준히 커지므로 커지면 예보를 orphan 브랜치로 옮기는 걸 고려할 것.

### `build_mountains.py`

```bash
python3 pipeline/build_mountains.py                          # 300개
python3 pipeline/build_mountains.py --limit 40 --no-photo     # 빠른 시험
python3 pipeline/build_crowd_params.py --refresh              # ← 빼먹으면 혼잡도가 평평해진다
python3 pipeline/validate.py data/v1/                         # 디렉터리를 주면 교차검사까지
```
- 조인은 **100대명산 `mtnCd` ↔ `trails.json` 코드**가 1순위(82/100), 없을 때만 `find_for()`
- `ascentM`·`kmaMountainCode` 는 원천이 없어 항상 null (함정 10, 산악예보 미사용)
- `parkType` 은 `NATIONAL_PARKS` 손 매핑 — 좌표 판정 불가(함정 11). 없는 산은 `none`
- 기존 `mountains.json` 의 **id 를 이름으로 승계**한다. id 는 즐겨찾기 저장 키라 바뀌면 안 된다
- 원천 응답은 `data/raw/api_cache/`(gitignore)에 캐시. 사진만 캐시하지 않는다
- 코스 우선순위는 **`curated_courses.json` > 라우팅 > 이름 묶음**.
  ⚠️ 직전 생성물(`prev`)을 손입력으로 쓰면 안 된다 — 자기가 만든 걸 되먹어 보정이 영영 안 먹는다
- 난이도는 코스 거리의 **중앙값**을 표고로 상한 건다(최댓값을 쓰면 63m 초록봉이 '어려움'이 됐다)

### `build_crowd_params.py` — 300개 산의 혼잡도 파라미터

`build_mountains.py` 뒤에 **반드시 돌린다**(워크플로에도 넣어 뒀다). 안 돌리면 파라미터 없는
산이 앱의 `fallback`(baseIndex 45 · 월 곡선 default)으로 떨어져 혼잡도가 전부 같아진다.

- `_absorb_signals()` — `data/v1/signals/*.json` 의 `monthProfile` 을 읽어 `SEARCH_TO_VISIT`(0.689)를
  곱하고 `confidence: "medium"` 으로 올린다. **signals 를 배포 모델에 잇는 유일한 고리다**
- `_search_popularity()` — `baseIndex` 서열을 데이터랩 검색량으로 매긴다(손입력 24개와 상관 +0.81).
  절대값 환산은 하지 않고, 지명 오염 때문에 상위 2%를 자른다
- `EST_MIN, EST_MAX = 8.0, 22.0` — 추정치는 손입력 최솟값(마니산 20.6) 언저리를 넘지 않아야 한다
- `--refresh` 는 `confidence: low` 항목만 버리고 다시 만든다. 실측·손입력은 건드리지 않는다

## 이미 확보된 것

- `pipeline/crowd_fit.json` — 설악산 실측 계수(요일·월·공휴일). 손으로 고치지 말고 재학습
- `pipeline/flagship_species.json` — 국립공원 깃대종 23개 공원 46종. **인증키 불필요**
  (knps.or.kr 공개 페이지에서 수집). `build_mountains.py` 가 이걸 써서 `species` 를 채운다
- `pipeline/holidays.json` — 2018~2027 공휴일 142일
- `pipeline/train_crowd.py` — 실측 학습기. `--max-mape` 로 임계 초과 시 기존 모델 유지
- `pipeline/make_dev_samples.py` — 앱 번들에 스키마 표본을 넣어 Swift 디코더와의
  계약을 검증한다. **스키마를 바꾸면 반드시 다시 돌릴 것**
- `pipeline/geo.py` — 좌표 변환(TM 역변환)과 점-다각형 판정. **외부 의존성 없음.**
  `python3 pipeline/geo.py` 로 자기검사(원본이 같은 지점을 투영좌표·WGS84 둘 다로 주므로
  실측 대조가 된다 — 303개 지점 최대 오차 0.01cm)
- `pipeline/trails.json` — 산 2,932개의 코스·들머리. `build_mountains.py` 가 이걸 쓴다.
  매칭은 반드시 `build_trail_index.find_for()` 로 (동명이산 함정)
- `pipeline/curated_courses.json` — 손으로 적은 24개 산 41개 코스 + 한 줄 소개 + 봉우리.
  라우팅보다 우선한다. **여기가 손입력의 유일한 출처다** — 직전 산출물을 손입력 취급하지 말 것
- `pipeline/fetch_visitor_stats.py` — 국립공원 탐방객 CSV(15107577). 등산로·공원경계와 달리
  **로그인 없이 직접 링크로 받힌다.** 현재 `atchFileId` 를 긁고 실패하면 상수로 떨어진다
- `pipeline/fetch_web_photos.py` + `web_photos.json` — 위 '사진' 절 참고
- `pipeline/validate.py` — 스키마뿐 아니라 **값의 범위**도 본다. 표고 50~2000m ·
  코스 25km/600분/0.8~6.0km·h · `baseIndex` 0 초과 100 이하. 인자로 `data/v1/` 디렉터리를 주면
  마스터와 혼잡도 모델의 **커버리지 교차검사**까지 한다(빠진 산을 잡는 건 이것뿐이다)

## 주의

- 전 워크플로에 `timeout-minutes` 를 걸어 두었다. 분 소모 사고의 최대 원인은
  평상시 사용량이 아니라 행(hang)이다 — 기본값 360분짜리 잡 하나가 예산을 태운다
- public 레포지만 fork PR 워크플로에는 시크릿이 전달되지 않는다.
  `pull_request_target` 은 쓰지 않는다
