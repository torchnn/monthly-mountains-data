#!/bin/zsh
# 로컬 파이프라인 공통 — GitHub Actions 의 setup-python·pip·커밋 단계 자리.
set -uo pipefail
REPO="${0:A:h:h}"
cd "$REPO"

py() { python3 "$@"; }

ensure_deps() {
  # Actions 는 회차마다 pip install 했다. 여기선 없을 때만 넣는다(매번 하면 느리다).
  local marker=".pipeline-deps-ok"
  if [ ! -f "$marker" ] || [ requirements.txt -nt "$marker" ]; then
    python3 -m pip install -q -r requirements.txt && touch "$marker"
  fi
}

commit_push() {   # commit_push "메시지" 경로...
  local msg="$1"; shift
  git add "$@"
  git diff --cached --quiet && { echo "변경 없음"; return 0; }
  git -c user.name="local-pipeline" \
      -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit -q -m "$msg"
  git push -q || { git pull -q --rebase --autostash && git push -q; }
}
