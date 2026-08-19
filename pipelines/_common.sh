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

# ── 레포 잠금 ───────────────────────────────────────────────────────────────
# 잠금이 잡(라벨) 단위라 **같은 레포를 쓰는 두 잡이 동시에** 돌 수 있었다.
# 둘 다 시작할 때 git fetch/merge 를 하므로 .git/index.lock 에서 하나가 죽는다.
# weekly-batch 는 여기 train-crowd.sh 를 옆 레포에서 직접 부르기까지 해서, 그때는
# 러너(run.sh)의 잠금이 아예 닿지 않는다. 그래서 잠금을 레포 안에 둔다 —
# 누가 부르든 같은 파일을 놓고 다툰다. .git 안이라 git 이 추적하지 않는다.
#
# trap 은 **반드시 최상위에서** 건다. zsh 는 함수 안에서 건 EXIT trap 을
# 셸이 끝날 때가 아니라 **그 함수가 끝날 때** 실행한다(bash 와 다르다).
# 처음에 함수 안에 뒀더니 repo_lock 이 반환되는 순간 잠금이 지워져서,
# 걸어 놓고도 두 번째 잡이 그대로 들어왔다.
_repo_lock_dir="$REPO/.git/pipeline.lock"
_repo_lock_held=0
_repo_lock_release() { [ "$_repo_lock_held" = 1 ] && rm -rf "$_repo_lock_dir"; return 0 }
trap _repo_lock_release EXIT INT TERM

repo_lock() {
  # 러너(run.sh)가 이 레포를 이미 잠갔으면 그냥 통과한다. 안 그러면 자기 자신과 교착한다 —
  # run.sh 가 잠금을 쥔 채 train-crowd.sh 를 부르고, 그 안에서 같은 잠금을 또 기다려서
  # 300초 상한에 걸렸다("같은 레포를 'train-crowd' 가 쓰는 중 — 300초째 기다립니다").
  # weekly-batch 처럼 **다른 레포**에서 부를 때는 값이 안 맞으므로 정상적으로 잠근다.
  if [ "${PIPELINE_REPO_LOCKED:-}" = "$REPO" ]; then
    return 0
  fi
  local waited=0 limit=${REPO_LOCK_WAIT:-1800} owner who
  while ! mkdir "$_repo_lock_dir" 2>/dev/null; do
    owner=$(cat "$_repo_lock_dir/pid" 2>/dev/null)
    who=$(cat "$_repo_lock_dir/who" 2>/dev/null)
    if [ -z "$owner" ] || ! kill -0 "$owner" 2>/dev/null; then
      echo "죽은 레포 잠금을 치웁니다 (${who:-?}, pid ${owner:-?})"
      rm -rf "$_repo_lock_dir"; continue
    fi
    if [ "$waited" -ge "$limit" ]; then
      echo "!! 같은 레포를 '${who:-?}' 가 ${limit}초 넘게 쓰고 있어 이번 회차를 건너뜁니다"
      return 2
    fi
    [ $((waited % 300)) -eq 0 ] && echo "같은 레포를 '${who:-?}' 가 쓰는 중 — ${waited}초째 기다립니다"
    sleep 15; waited=$((waited + 15))
  done
  _repo_lock_held=1
  print -r -- $$ > "$_repo_lock_dir/pid"
  print -r -- "${1:-$(basename $0)}" > "$_repo_lock_dir/who"
  return 0
}
