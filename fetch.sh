#!/usr/bin/env bash
set -euo pipefail

CALLER_RESULTS_PATH="${RESULTS_PATH-}"
CALLER_RESULTS_DEST="${RESULTS_DEST-}"
CALLER_FETCH_DELETE="${FETCH_DELETE-}"
CALLER_LOG_PATTERN="${LOG_PATTERN-}"
CALLER_FETCH_DEST="${FETCH_DEST-}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

usage() {
  cat <<'EOF'
Usage:
  ./fetch.sh --remote-path PROJECT_RELATIVE_PATH [options]

Required:
  --remote-path PATH   Result directory relative to DIR.

Options:
  --dest PATH          Exact local destination directory.
  --delete             Delete local entries absent from the remote directory.
  --log-pattern GLOB   Also fetch matching files from remote's ~/logs.
  -h, --help           Show this help.

Exported RESULTS_PATH, RESULTS_DEST, FETCH_DELETE, and
LOG_PATTERN remain supported. Values merely assigned in a parent shell
without export cannot be inherited by this script.
EOF
}

CLI_RESULTS_PATH=""
CLI_RESULTS_DEST=""
CLI_FETCH_DELETE=""
CLI_LOG_PATTERN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-path)
      [[ $# -ge 2 ]] || { echo "Error: --remote-path requires a value." >&2; exit 2; }
      CLI_RESULTS_PATH="$2"
      shift 2
      ;;
    --dest)
      [[ $# -ge 2 ]] || { echo "Error: --dest requires a value." >&2; exit 2; }
      CLI_RESULTS_DEST="$2"
      shift 2
      ;;
    --delete)
      CLI_FETCH_DELETE=1
      shift
      ;;
    --log-pattern)
      [[ $# -ge 2 ]] || { echo "Error: --log-pattern requires a value." >&2; exit 2; }
      CLI_LOG_PATTERN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${HOST:?Set HOST in $ENV_FILE or the shell environment}"
: "${PORT:?Set PORT in $ENV_FILE or the shell environment}"
: "${DIR:?Set DIR in $ENV_FILE or the shell environment}"

SNAPSHOT_TAG="${SNAPSHOT_TAG:-$(date +%Y%m%d_%H%M%S)}"
FETCH_DEST="${CALLER_FETCH_DEST:-$PROJECT_ROOT/results/snapshots/$SNAPSHOT_TAG}"
RESULTS_PATH="${CLI_RESULTS_PATH:-$CALLER_RESULTS_PATH}"
RESULTS_DEST="${CLI_RESULTS_DEST:-${CALLER_RESULTS_DEST:-$FETCH_DEST/results}}"
FETCH_DELETE="${CLI_FETCH_DELETE:-${CALLER_FETCH_DELETE:-0}}"
LOG_PATTERN="${CLI_LOG_PATTERN:-$CALLER_LOG_PATTERN}"
RSYNC_RSH="ssh -p $PORT"
RSYNC_DELETE_ARGS=()

if [[ -z "$RESULTS_PATH" ]]; then
  echo "Error: result source is required; pass --remote-path or export RESULTS_PATH." >&2
  usage >&2
  exit 2
fi
while [[ "$RESULTS_PATH" == */ ]]; do
  RESULTS_PATH="${RESULTS_PATH%/}"
done
if [[ -z "$RESULTS_PATH" || "$RESULTS_PATH" == /* || "$RESULTS_PATH" == "." || "/$RESULTS_PATH/" == *"/../"* ]]; then
  echo "Error: --remote-path must be a non-empty path relative to DIR without '..': $RESULTS_PATH" >&2
  exit 2
fi
if [[ "$FETCH_DELETE" != "0" && "$FETCH_DELETE" != "1" ]]; then
  echo "Error: FETCH_DELETE must be 0 or 1, got: $FETCH_DELETE" >&2
  exit 2
fi

RESULTS_DEST="$(realpath -m -- "$RESULTS_DEST")"
if [[ "$FETCH_DELETE" == "1" ]]; then
  if [[ "$RESULTS_DEST" == "/" || "$RESULTS_DEST" == "$HOME" || "$RESULTS_DEST" == "$PROJECT_ROOT" ]]; then
    echo "Error: refusing --delete for broad destination: $RESULTS_DEST" >&2
    exit 2
  fi
  RSYNC_DELETE_ARGS+=(--delete)
fi

echo "Resolved fetch:"
echo "  Remote: $HOST:$DIR/$RESULTS_PATH/"
echo "  Local:  $RESULTS_DEST/"
echo "  Delete: $FETCH_DELETE"

mkdir -p "$RESULTS_DEST"

echo "Fetching project results from $HOST:$DIR/$RESULTS_PATH"
rsync \
  --archive \
  --human-readable \
  --partial \
  "${RSYNC_DELETE_ARGS[@]}" \
  --info=stats2,progress2 \
  --rsh="$RSYNC_RSH" \
  "$HOST:$DIR/$RESULTS_PATH/" \
  "$RESULTS_DEST/"

echo "Verifying fetched tree with an rsync checksum dry run"
VERIFY_DIFF="$(
  rsync \
    --archive \
    --checksum \
    --delete \
    --dry-run \
    --itemize-changes \
    --rsh="$RSYNC_RSH" \
    "$HOST:$DIR/$RESULTS_PATH/" \
    "$RESULTS_DEST/"
)"
if [[ -n "$VERIFY_DIFF" ]]; then
  echo "Error: local result tree differs from the remote after fetch:" >&2
  printf '%s\n' "$VERIFY_DIFF" >&2
  exit 1
fi
echo "Verification complete: local and remote result trees match"

if [[ -n "$LOG_PATTERN" ]]; then
  mkdir -p "$FETCH_DEST/logs"
  echo "Fetching matching logs from $HOST:~/logs ($LOG_PATTERN)"
  rsync \
    --archive \
    --human-readable \
    --partial \
    --prune-empty-dirs \
    --include="$LOG_PATTERN" \
    --exclude='*' \
    --info=stats2,progress2 \
    --rsh="$RSYNC_RSH" \
    "$HOST:logs/" \
    "$FETCH_DEST/logs/"
fi

echo "Fetch complete: $RESULTS_DEST"
