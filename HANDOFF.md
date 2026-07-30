# 인수인계 — monthly-mountains-data (2026-07-30)

앱이 읽는 정적 데이터를 만들어 GitHub Pages 로 배포하는 레포.
전체 그림은 [앱 레포의 docs/HANDOFF.md](https://github.com/torchnn/monthly-mountains/blob/main/docs/HANDOFF.md).

## 🔴 최대 블로커: `DATA_GO_KR_KEY` 미등록

일요일(2026-08-02)까지 공공데이터포털 활용이 불가능하다. 이 키가 없으면
`build-mountains` · `forecast-weather` · `train-crowd` 세 워크플로가 전부 못 돈다.

신청할 8개 API 목록과 절차는 앱 레포 HANDOFF 에 정리돼 있다. 요약하면
`data.go.kr → 데이터찾기 → 데이터목록 → 검색 → 오픈API 탭 → 활용신청`,
키는 `마이페이지 → 인증키 발급현황`. **계정당 키 하나**로 8개 전부 커버된다.

```bash
gh secret set DATA_GO_KR_KEY --repo torchnn/monthly-mountains-data --body "<키>"
```

**추가로 사람이 직접 받아야 하는 파일데이터**(다운로드에 로그인 세션 필요 — 스크립트로 안 됨):
- 전국등산로표준데이터 (2,919건, GPX) → 코스·누적상승고도
- 국립공원 공원경계 (SHP) → `parkType` 판정

## 현재 배포 상태

```
https://torchnn.github.io/monthly-mountains-data/data/v1/
  manifest.json       ✅
  mountains.json      ✅ 24개 (시드) — 키가 있으면 300개
  crowd_model.json    ✅ 실측 학습본
  signals/<id>.json   ✅ 25개 (signals 레포가 push)
  restaurants/<id>.json ✅ (signals 레포가 push · 네이버 기준 + 구글 단건 보강)
  forecast/<id>.json  ❌ 키 필요
```

⚠️ **Pages 는 레포 루트를 서빙**하므로 URL 에 `data/` 가 들어간다.
앱의 `DataStore.remoteBase` 가 이 경로와 맞아야 한다.

## 워크플로

| 파일 | 주기 | 상태 |
|---|---|---|
| `build-mountains.yml` | 월 1회 | ⚠️ `build_mountains.py` **미구현** |
| `forecast-weather.yml` | 3시간 | ✅ `collect_weather.py` 있음 (키 필요) |
| `train-crowd.yml` | 주 1회 | ⚠️ `fetch_visitor_stats.py` 미구현. `train_crowd.py` 는 있음 |
| `publish-pages.yml` | push | ❌ 미작성 (지금은 Pages 기본 동작에 의존) |

**미구현 스크립트** — 키가 생기면 실제 응답을 보며 작성해야 한다:
`build_mountains.py`, `validate.py`, `fetch_visitor_stats.py`

## 이미 확보된 것

- `pipeline/crowd_fit.json` — 설악산 실측 계수(요일·월·공휴일). 손으로 고치지 말고 재학습
- `pipeline/flagship_species.json` — 국립공원 깃대종 23개 공원 46종. **인증키 불필요**
  (knps.or.kr 공개 페이지에서 수집). `build_mountains.py` 가 이걸 써서 `species` 를 채운다
- `pipeline/holidays.json` — 2018~2027 공휴일 142일
- `pipeline/train_crowd.py` — 실측 학습기. `--max-mape` 로 임계 초과 시 기존 모델 유지
- `pipeline/make_dev_samples.py` — 앱 번들에 스키마 표본을 넣어 Swift 디코더와의
  계약을 검증한다. **스키마를 바꾸면 반드시 다시 돌릴 것**

## 주의

- 전 워크플로에 `timeout-minutes` 를 걸어 두었다. 분 소모 사고의 최대 원인은
  평상시 사용량이 아니라 행(hang)이다 — 기본값 360분짜리 잡 하나가 예산을 태운다
- public 레포지만 fork PR 워크플로에는 시크릿이 전달되지 않는다.
  `pull_request_target` 은 쓰지 않는다
