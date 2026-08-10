#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLUE_ENV_FILE="${BLUE_ENV_FILE:-$PROJECT_ROOT/.env.blue}"

if [[ -f "$BLUE_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$BLUE_ENV_FILE"
  set +a
fi

: "${BLUE_HOST:?Set BLUE_HOST in $BLUE_ENV_FILE or the shell environment}"
: "${BLUE_PORT:?Set BLUE_PORT in $BLUE_ENV_FILE or the shell environment}"
: "${BLUE_DIR:?Set BLUE_DIR in $BLUE_ENV_FILE or the shell environment}"

SNAPSHOT_TAG="${SNAPSHOT_TAG:-$(date +%Y%m%d_%H%M%S)}"
FETCH_DEST="${FETCH_DEST:-$PROJECT_ROOT/results/blue-snapshots/$SNAPSHOT_TAG}"
BLUE_RESULTS_PATH="${BLUE_RESULTS_PATH:-results}"
BLUE_RESULTS_DEST="${BLUE_RESULTS_DEST:-$FETCH_DEST/results}"
BLUE_FETCH_DELETE="${BLUE_FETCH_DELETE:-0}"
BLUE_LOG_PATTERN="${BLUE_LOG_PATTERN:-}"
RSYNC_RSH="ssh -p $BLUE_PORT"
RSYNC_DELETE_ARGS=()

if [[ "$BLUE_FETCH_DELETE" == "1" ]]; then
  RSYNC_DELETE_ARGS+=(--delete)
fi

mkdir -p "$BLUE_RESULTS_DEST"

echo "Fetching project results from $BLUE_HOST:$BLUE_DIR/$BLUE_RESULTS_PATH"
rsync \
  --archive \
  --human-readable \
  --partial \
  "${RSYNC_DELETE_ARGS[@]}" \
  --info=stats2,progress2 \
  --rsh="$RSYNC_RSH" \
  "$BLUE_HOST:$BLUE_DIR/$BLUE_RESULTS_PATH/" \
  "$BLUE_RESULTS_DEST/"

if [[ -n "$BLUE_LOG_PATTERN" ]]; then
  mkdir -p "$FETCH_DEST/logs"
  echo "Fetching matching logs from $BLUE_HOST:~/logs ($BLUE_LOG_PATTERN)"
  rsync \
    --archive \
    --human-readable \
    --partial \
    --prune-empty-dirs \
    --include="$BLUE_LOG_PATTERN" \
    --exclude='*' \
    --info=stats2,progress2 \
    --rsh="$RSYNC_RSH" \
    "$BLUE_HOST:logs/" \
    "$FETCH_DEST/logs/"
fi

echo "Fetch complete: $FETCH_DEST"
