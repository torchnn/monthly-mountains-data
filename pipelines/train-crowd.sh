#!/bin/zsh
# train-crowd 를 대신한다. 매주 월요일 + 신호 갱신 직후(weekly-batch 가 직접 부른다).
source "${0:A:h}/_common.sh"
ensure_deps
py pipeline/fetch_visitor_stats.py          || exit $?
py pipeline/train_crowd.py --max-mape 0.45  || exit $?
commit_push "crowd: 모델 재학습" data/v1 data/raw
