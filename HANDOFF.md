# 인수인계 — monthly-mountains-data (2026-08-08)

앱이 읽는 정적 데이터를 만들어 GitHub Pages 로 배포하는 레포.
전체 그림은 [앱 레포의 docs/HANDOFF.md](https://github.com/torchnn/monthly-mountains/blob/main/docs/HANDOFF.md).

## ✅ `DATA_GO_KR_KEY` 등록 완료 (2026-08-08)

**디코딩 키**를 등록해야 한다 — `collect_weather.py` 가 `serviceKey` 를 requests params 로
넘겨 다시 URL 인코딩하므로, 인코딩 키를 넣으면 이중 인코딩으로 인증에 실패한다.

```bash
gh secret set DATA_GO_KR_KEY --repo torchnn/monthly-mountains-data --body "<디코딩 키>"
```

`forecast-weather` 는 지금 바로 돈다(24개 산 실측 확인). 나머지 둘은 스크립트가 없다.

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
  crowd_model.json    ✅ 실측 학습본
  signals/<id>.json   ✅ 25개 (signals 레포가 push)
  restaurants/<id>.json ✅ (signals 레포가 push · 네이버 기준 + 구글 단건 보강)
  forecast/<id>.json  ✅ 생성 가능 — 크론만 되살리면 된다
```

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
python3 pipeline/validate.py data/v1/mountains.json
```
- 조인은 **100대명산 `mtnCd` ↔ `trails.json` 코드**가 1순위(82/100), 없을 때만 `find_for()`
- `ascentM`·`kmaMountainCode` 는 원천이 없어 항상 null (함정 10, 산악예보 미사용)
- `parkType` 은 `NATIONAL_PARKS` 손 매핑 — 좌표 판정 불가(함정 11). 없는 산은 `none`
- 기존 `mountains.json` 의 **id 를 이름으로 승계**한다. id 는 즐겨찾기 저장 키라 바뀌면 안 된다
- 원천 응답은 `data/raw/api_cache/`(gitignore)에 캐시. 사진만 캐시하지 않는다

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

## 주의

- 전 워크플로에 `timeout-minutes` 를 걸어 두었다. 분 소모 사고의 최대 원인은
  평상시 사용량이 아니라 행(hang)이다 — 기본값 360분짜리 잡 하나가 예산을 태운다
- public 레포지만 fork PR 워크플로에는 시크릿이 전달되지 않는다.
  `pull_request_target` 은 쓰지 않는다
