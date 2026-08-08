#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLUE_ENV_FILE="${BLUE_ENV_FILE:-$SCRIPT_DIR/.env.blue}"

if [[ -f "$BLUE_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$BLUE_ENV_FILE"
  set +a
fi

: "${BLUE_HOST:?Set BLUE_HOST in $BLUE_ENV_FILE or the shell environment}"
: "${BLUE_PORT:?Set BLUE_PORT in $BLUE_ENV_FILE or the shell environment}"
: "${BLUE_DIR:?Set BLUE_DIR in $BLUE_ENV_FILE or the shell environment}"

REMOTE_HOST="$BLUE_HOST"
REMOTE_PORT="$BLUE_PORT"
REMOTE_DIR="$BLUE_DIR"
REMOTE_BARE_DIR="${BLUE_GIT_DIR:-${BLUE_DIR}.git}"

cd "$SCRIPT_DIR"

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
    git -C '$REMOTE_DIR' remote set-url origin \"\$bare_path\"
    git -C '$REMOTE_DIR' fetch origin '$BRANCH'
    git -C '$REMOTE_DIR' checkout '$BRANCH'
    git -C '$REMOTE_DIR' merge --ff-only 'origin/$BRANCH'
  fi
"

echo "Git sync complete at commit $(git rev-parse --short HEAD)."
