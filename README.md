# monthly-mountains-data (public)

[이달의 산](https://github.com/torchnn/monthly-mountains) 앱이 읽는 **공공데이터 파이프라인**.
GitHub Actions 가 공공 API 를 호출해 정적 JSON 을 만들고 GitHub Pages 로 배포한다.
앱에는 API 키가 들어가지 않는다.

## 왜 public 인가

torchnn 레포의 **기본값은 private** 이다. 이 레포가 예외인 이유는 순서대로:

1. **배포 수단이 이것뿐** — GitHub Free 는 private 레포에 Pages 를 못 붙인다.
   앱이 읽을 정적 JSON 을 내보내려면 public 이어야 한다.
2. **원천이 전부 공공데이터** (산림청·국립공원공단·기상청·한국환경공단) — 이용허락범위가
   제한없음/공공누리라 가공물 공개 배포에 문제가 없다.
3. **코드를 봐도 새로 드러나는 게 없다** — 호출하는 API 사용법이 전부 공개 문서다.
4. 앱 로직·수익화 코드·계정 식별자·시크릿이 없다.

> ⚠️ **Actions 분 절감은 public 사유가 아니다.** 비용은 증분화·주기 조정·타임아웃으로 푼다.
> (이전 판 README 는 "실질적인 이유는 Actions 분" 이라고 적었는데, 그 논리를 따르면
> 비싼 private 파이프라인을 전부 공개해야 한다는 결론이 나온다 — 잘못된 기준이었다.)

네이버 관련 수집은 재배포 제약이 있어 [monthly-mountains-signals](https://github.com/torchnn/monthly-mountains-signals)(private)
에서 돌고, **파생 산출물만** 이 레포로 push 된다.

## 현재 상태 (2026-08-09) — 사슬이 이어졌다

인증키를 발급받아 등록했고, 미작성 스크립트도 없다. 자동 갱신이 돈다.

| 스크립트 | 상태 |
|---|---|
| `collect_weather.py` | ✅ 날씨·대기질·특보 |
| `build_mountains.py` | ✅ 산 마스터 300개 |
| `build_crowd_params.py` | ✅ 산별 혼잡도 파라미터 확장 |
| `fetch_visitor_stats.py` | ✅ 탐방객 통계 CSV 수신 |
| `train_crowd.py` · `validate.py` | ✅ |
| `DATA_GO_KR_KEY` 시크릿 | ✅ 등록 — **디코딩 키**여야 한다 |

이어진 사슬:
```
fetch_visitor_stats.py → data/raw/*.csv  → train_crowd.py       → crowd_fit.json
build_mountains.py     → mountains.json → build_crowd_params.py → crowd_model.json
```
`data/raw/` 는 gitignore 다. 탐방객 CSV 는 로그인이 필요 없어 CI 가 직접 받지만,
등산로·공원경계 원본은 세션이 필요해 **사람이 받아 로컬에서 변환본을 커밋**한다
(`pipeline/trails.json` · `pipeline/park_buffer_3km.json`).

## 워크플로

| 파일 | 주기 | 하는 일 | 상태 |
|---|---|---|---|
| `build-mountains.yml` | 매월 1일 03:00 KST | 산 마스터 재빌드 + 혼잡도 파라미터 | ✅ 활성 |
| `forecast-weather.yml` | 3시간마다 | 날씨·대기질·특보 → `forecast/<id>.json` | ✅ 활성 |
| `train-crowd.yml` | 매주 월 04:00 KST + dispatch | 혼잡도 모델 학습·검증 | ✅ 활성 |
| (Pages 자동) | push | `data/v1/` → Pages | ✅ 동작 |

⚠️ 산 300개면 `forecast-weather` 가 회차마다 300개 파일을 커밋한다(회당 0.9MB · 하루 8회).
레포 증가가 문제되면 예보를 orphan 브랜치로 옮기는 걸 고려할 것.

전 워크플로에 `timeout-minutes` 를 건다. 분 소모 사고의 최대 원인은 평상시 사용량이 아니라
행(hang)이다 — 기본값 360분짜리 잡 하나가 예산을 통째로 태운다.

## 배포 산출물 (`data/v1/`)

| 파일 | 갱신 | 내용 |
|---|---|---|
| `mountains.json` | 월 1회 | 산 마스터(이름·표고·봉우리·코스·난이도·깃대종·들머리) |
| `crowd_model.json` | 주 1회 | 혼잡도 계수(시간곡선·요일·월·날씨·산별 파라미터) |
| `forecast/<id>.json` | 3시간 | 날씨·대기질·특보·통제·일별 혼잡 지수 |
| `restaurants/<id>.json` | 2주 | 맛집 (signals 레포에서 push) |
| `manifest.json` | 매 갱신 | 버전·갱신 시각 |

## 로컬 실행

```bash
pip install requests
export DATA_GO_KR_KEY=...       # 공공데이터포털 인증키

python3 pipeline/build_mountains.py
python3 pipeline/collect_weather.py

# 키 없이 스키마만 확인
python3 pipeline/collect_weather.py --dry-run --only bukhansan
```

## 스키마 계약

파이프라인 출력과 앱의 Swift 디코더가 어긋나면 앱은 조용히 빈 화면을 보여준다.
이를 막기 위해 표본 파일을 앱 번들에 넣어 DEBUG 에서 assert 로 잡는다.

```bash
python3 pipeline/make_dev_samples.py   # 형제 디렉터리 ../monthly_mountains 에 씀
```

스키마를 바꾸면 **이 스크립트를 다시 돌리고 앱을 DEBUG 로 띄워** 확인한다.

## 시크릿

| 이름 | 발급처 |
|---|---|
| `DATA_GO_KR_KEY` | [공공데이터포털](https://www.data.go.kr) — 산정보·100대명산·봉우리POI·단기예보·기상특보·에어코리아·TourAPI |

**디코딩 키**를 등록한다. requests 의 params 로 넘기면 라이브러리가 다시 URL 인코딩하므로
인코딩 키를 넣으면 이중 인코딩으로 인증에 실패한다.
기상청 산악예보는 포털에 없어 쓰지 않는다(`kmaMountainCode` 는 계속 null, 단기예보 격자로 간다).

public 레포지만 [fork PR 워크플로에는 시크릿이 전달되지 않는다](https://docs.github.com/en/actions/reference/security/secure-use).
추가로 fork PR 워크플로 승인을 필수로 걸고 `pull_request_target` 은 쓰지 않는다.
