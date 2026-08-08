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

SNAPSHOT_TAG="${SNAPSHOT_TAG:-$(date +%Y%m%d_%H%M%S)}"
FETCH_DEST="${FETCH_DEST:-$SCRIPT_DIR/results/blue-snapshots/$SNAPSHOT_TAG}"
RSYNC_RSH="ssh -p $BLUE_PORT"

mkdir -p "$FETCH_DEST/general_reasoning" "$FETCH_DEST/logs"

echo "Fetching general-reasoning results from $BLUE_HOST:$BLUE_DIR"
rsync \
  --archive \
  --human-readable \
  --partial \
  --info=stats2,progress2 \
  --rsh="$RSYNC_RSH" \
  "$BLUE_HOST:$BLUE_DIR/general_reasoning/results/" \
  "$FETCH_DEST/general_reasoning/results/"

echo "Fetching LightThinker evaluation logs from $BLUE_HOST:~/logs"
rsync \
  --archive \
  --human-readable \
  --partial \
  --prune-empty-dirs \
  --include='lightthinker-*' \
  --exclude='*' \
  --info=stats2,progress2 \
  --rsh="$RSYNC_RSH" \
  "$BLUE_HOST:logs/" \
  "$FETCH_DEST/logs/"

echo "Fetch complete: $FETCH_DEST"
