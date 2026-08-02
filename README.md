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

## ⚠️ 현재 상태 (2026-08-03) — 자동 갱신은 멈춰 있다

**`data/v1/` 의 데이터는 파이프라인이 만든 것이 아니라 2026-07-27~28 에 손으로 넣은 것이다.**
앱은 그 데이터로 정상 동작하지만, 아래가 갖춰질 때까지 **자동 갱신은 되지 않는다.**

| 필요한 것 | 상태 | 막는 것 |
|---|---|---|
| `pipeline/collect_weather.py` | ✅ 있음 | — |
| `pipeline/train_crowd.py` | ✅ 있음 | — |
| `pipeline/validate.py` | ✅ 있음 | — |
| `requirements.txt` | ✅ 있음 | — |
| `pipeline/fetch_visitor_stats.py` | ❌ **미작성** | 공공데이터포털(국립공원공단 탐방객 API) 응답을 봐야 작성 가능 |
| `pipeline/build_mountains.py` | ❌ **미작성** | 공공데이터포털(산림청 산정보·100대명산) 〃 |
| `DATA_GO_KR_KEY` 시크릿 | ❌ 미등록 | 포털 점검 중 (2026-08 기준 로그인 불가) |

끊긴 사슬을 그림으로:
```
fetch_visitor_stats.py → data/raw/*.csv → train_crowd.py → crowd_fit.json
     ❌ 없음               ⚠️ gitignore      ✅ 있음
```
`data/raw/` 는 원본이 2.4MB 라 의도적으로 gitignore 다. 받아오는 스크립트가 없으니 CI 에는 입력이 없다.
**키만 등록해도 이 사슬은 이어지지 않는다.**

그래서 세 워크플로의 `schedule:` 은 **주석 처리해 두었다.** 3시간마다 실패해 월 240건의 빨간 X 를
쌓으면 진짜 고장이 그 속에 묻힌다. `workflow_dispatch` 는 살려 뒀으니 수동 실행은 된다.
포털이 열리면 위 표의 ❌ 를 채우고 크론 주석을 되돌린다.

## 워크플로

| 파일 | 주기 | 하는 일 | 상태 |
|---|---|---|---|
| `build-mountains.yml` | 월 1회 | 산 마스터 재빌드 | ⏸ 크론 정지 (스크립트 미작성) |
| `forecast-weather.yml` | 3시간 | 날씨·대기질·특보 → `forecast/<id>.json` | ⏸ 크론 정지 (키 미등록) |
| `train-crowd.yml` | 주 1회 + dispatch | 혼잡도 모델 학습·검증 | ⏸ 크론 정지 (스크립트 미작성) |
| (Pages 자동) | push | `data/v1/` → Pages | ✅ 동작 |

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
