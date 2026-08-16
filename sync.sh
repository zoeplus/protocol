#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${HOST:?Set HOST in $ENV_FILE or the shell environment}"
: "${PORT:?Set PORT in $ENV_FILE or the shell environment}"
: "${DIR:?Set DIR in $ENV_FILE or the shell environment}"

REMOTE_HOST="$HOST"
REMOTE_PORT="$PORT"
REMOTE_DIR="$DIR"
REMOTE_BARE_DIR="${GIT_DIR:-${DIR}.git}"

cd "$PROJECT_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: commit or stash local changes before syncing." >&2
  exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  echo "Error: detached HEAD cannot be synced." >&2
  exit 1
fi

echo "Preparing Git repository on $REMOTE_HOST:$REMOTE_BARE_DIR"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
  if [ -e '$REMOTE_DIR' ] && [ ! -d '$REMOTE_DIR/.git' ]; then
    echo 'Error: $REMOTE_DIR exists but is not a Git checkout.' >&2
    echo 'Fetch its results, then rename or remove it before bootstrapping Git.' >&2
    exit 2
  fi
  if [ ! -d '$REMOTE_BARE_DIR' ]; then
    git init --bare '$REMOTE_BARE_DIR'
  fi
"

echo "Pushing $BRANCH to $REMOTE_HOST:$REMOTE_BARE_DIR"
GIT_SSH_COMMAND="ssh -p $REMOTE_PORT" \
GIT_LFS_SKIP_PUSH=1 \
  git push "$REMOTE_HOST:$REMOTE_BARE_DIR" \
  "HEAD:refs/heads/$BRANCH"

echo "Updating working checkout $REMOTE_HOST:$REMOTE_DIR"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
  git --git-dir='$REMOTE_BARE_DIR' symbolic-ref HEAD 'refs/heads/$BRANCH'
  if [ ! -d '$REMOTE_DIR/.git' ]; then
    GIT_LFS_SKIP_SMUDGE=1 git clone '$REMOTE_BARE_DIR' '$REMOTE_DIR'
  else
    bare_path='$REMOTE_BARE_DIR'
    case \"\$bare_path\" in
      /*) ;;
      *) bare_path=\"\$HOME/\$bare_path\" ;;
    esac
    if git -C '$REMOTE_DIR' remote get-url origin >/dev/null 2>&1; then
      git -C '$REMOTE_DIR' remote set-url origin \"\$bare_path\"
    else
      git -C '$REMOTE_DIR' remote add origin \"\$bare_path\"
    fi
    git -C '$REMOTE_DIR' fetch origin '$BRANCH'
    git -C '$REMOTE_DIR' checkout '$BRANCH'
    git -C '$REMOTE_DIR' merge --ff-only 'origin/$BRANCH'
  fi
"

echo "Git sync complete at commit $(git rev-parse --short HEAD)."
