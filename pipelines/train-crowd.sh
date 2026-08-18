#!/bin/zsh
# train-crowd 를 대신한다. 매주 월요일 + 신호 갱신 직후(weekly-batch 가 직접 부른다).
source "${0:A:h}/_common.sh"
# weekly-batch 가 이 스크립트를 옆 레포에서 직접 부른다. 그때는 러너의 잠금이
# 닿지 않으므로 여기서 직접 레포를 잠근다 (forecast-weather 와 겹치는 것을 막는다).
repo_lock train-crowd || exit 0
ensure_deps
py pipeline/fetch_visitor_stats.py          || exit $?
py pipeline/train_crowd.py --max-mape 0.45  || exit $?
commit_push "crowd: 모델 재학습" data/v1 data/raw
