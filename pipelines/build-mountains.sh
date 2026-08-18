#!/bin/zsh
# build-mountains 를 대신한다. 매월 1일.
source "${0:A:h}/_common.sh"
ensure_deps
py pipeline/build_mountains.py                     || exit $?
py pipeline/validate.py data/v1/mountains.json     || exit $?
py pipeline/build_crowd_params.py --refresh        || exit $?
py pipeline/validate.py data/v1/crowd_model.json   || exit $?
commit_push "mountains: 마스터 재빌드" data/v1/mountains.json data/v1/crowd_model.json data/v1/manifest.json
