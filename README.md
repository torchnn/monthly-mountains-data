# monthly-mountains-data (public)

[이달의 산](https://github.com/torchnn/monthly-mountains) 앱이 읽는 **공공데이터 파이프라인**.
GitHub Actions 가 공공 API 를 호출해 정적 JSON 을 만들고 GitHub Pages 로 배포한다.
앱에는 API 키가 들어가지 않는다.

## 왜 public 인가

여기서 다루는 건 전부 공공데이터(산림청·국립공원공단·기상청·한국환경공단)라
이용허락범위가 제한없음/공공누리이고 가공물 공개 배포에 문제가 없다.

실질적인 이유는 **Actions 분**이다. 3시간마다 도는 날씨 워크플로가 월 600분을 먹는데
public 레포는 실행 시간이 무제한이라 그 600분이 0이 된다.
(GitHub Free 는 private 레포에 Pages 를 못 붙이므로 배포도 여기서 한다.)

네이버 관련 수집은 재배포 제약이 있어 [monthly-mountains-signals](https://github.com/torchnn/monthly-mountains-signals)(private)
에서 돌고, **파생 산출물만** 이 레포로 push 된다.

## 워크플로

| 파일 | 주기 | 하는 일 |
|---|---|---|
| `build-mountains.yml` | 월 1회 | 산 마스터 재빌드 |
| `forecast-weather.yml` | 3시간 | 날씨·대기질·특보 → `forecast/<id>.json` |
| `train-crowd.yml` | 주 1회 + dispatch | 혼잡도 모델 학습·검증 |
| `publish-pages.yml` | push | `data/v1/` → Pages |

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
| `DATA_GO_KR_KEY` | [공공데이터포털](https://www.data.go.kr) — 산정보·100대명산·산악예보·단기예보·에어코리아·TourAPI |

public 레포지만 [fork PR 워크플로에는 시크릿이 전달되지 않는다](https://docs.github.com/en/actions/reference/security/secure-use).
추가로 fork PR 워크플로 승인을 필수로 걸고 `pull_request_target` 은 쓰지 않는다.
