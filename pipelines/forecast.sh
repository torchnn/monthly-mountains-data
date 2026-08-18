#!/bin/zsh
# forecast-weather 를 대신한다. 3시간마다.
#
# **로컬로 옮긴 이유가 이 잡이다.** GitHub 러너가 받는 Azure IP 의 25~75% 가
# apis.data.go.kr 에 아예 못 붙었다(2026-08-18 표본: IP 8개 중 2개가 0/30).
# 같은 순간 이 맥(KT 회선)에서는 10ms 에 붙는다.
source "${0:A:h}/_common.sh"
ensure_deps
py pipeline/collect_weather.py
rc=$?
# 종료코드 3 = 포털에 못 붙었다. 받은 만큼은 커밋하고 넘어간다.
[ "$rc" = "0" ] || [ "$rc" = "3" ] || exit "$rc"
commit_push "forecast: $(date -u +%Y-%m-%dT%H:%MZ)" data/v1/forecast data/v1/manifest.json
exit 0
