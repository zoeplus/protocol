#!/usr/bin/env bash
set -euo pipefail

CALLER_BLUE_RESULTS_PATH="${BLUE_RESULTS_PATH-}"
CALLER_BLUE_RESULTS_DEST="${BLUE_RESULTS_DEST-}"
CALLER_BLUE_FETCH_DELETE="${BLUE_FETCH_DELETE-}"
CALLER_BLUE_LOG_PATTERN="${BLUE_LOG_PATTERN-}"
CALLER_FETCH_DEST="${FETCH_DEST-}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLUE_ENV_FILE="${BLUE_ENV_FILE:-$PROJECT_ROOT/.env.blue}"

usage() {
  cat <<'EOF'
Usage:
  ./fetch-blue.sh --remote-path PROJECT_RELATIVE_PATH [options]

Required:
  --remote-path PATH   Result directory relative to BLUE_DIR.

Options:
  --dest PATH          Exact local destination directory.
  --delete             Delete local entries absent from the remote directory.
  --log-pattern GLOB   Also fetch matching files from blue's ~/logs.
  -h, --help           Show this help.

Exported BLUE_RESULTS_PATH, BLUE_RESULTS_DEST, BLUE_FETCH_DELETE, and
BLUE_LOG_PATTERN remain supported. Values merely assigned in a parent shell
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
FETCH_DEST="${CALLER_FETCH_DEST:-$PROJECT_ROOT/results/blue-snapshots/$SNAPSHOT_TAG}"
BLUE_RESULTS_PATH="${CLI_RESULTS_PATH:-$CALLER_BLUE_RESULTS_PATH}"
BLUE_RESULTS_DEST="${CLI_RESULTS_DEST:-${CALLER_BLUE_RESULTS_DEST:-$FETCH_DEST/results}}"
BLUE_FETCH_DELETE="${CLI_FETCH_DELETE:-${CALLER_BLUE_FETCH_DELETE:-0}}"
BLUE_LOG_PATTERN="${CLI_LOG_PATTERN:-$CALLER_BLUE_LOG_PATTERN}"
RSYNC_RSH="ssh -p $BLUE_PORT"
RSYNC_DELETE_ARGS=()

if [[ -z "$BLUE_RESULTS_PATH" ]]; then
  echo "Error: result source is required; pass --remote-path or export BLUE_RESULTS_PATH." >&2
  usage >&2
  exit 2
fi
while [[ "$BLUE_RESULTS_PATH" == */ ]]; do
  BLUE_RESULTS_PATH="${BLUE_RESULTS_PATH%/}"
done
if [[ -z "$BLUE_RESULTS_PATH" || "$BLUE_RESULTS_PATH" == /* || "$BLUE_RESULTS_PATH" == "." || "/$BLUE_RESULTS_PATH/" == *"/../"* ]]; then
  echo "Error: --remote-path must be a non-empty path relative to BLUE_DIR without '..': $BLUE_RESULTS_PATH" >&2
  exit 2
fi
if [[ "$BLUE_FETCH_DELETE" != "0" && "$BLUE_FETCH_DELETE" != "1" ]]; then
  echo "Error: BLUE_FETCH_DELETE must be 0 or 1, got: $BLUE_FETCH_DELETE" >&2
  exit 2
fi

BLUE_RESULTS_DEST="$(realpath -m -- "$BLUE_RESULTS_DEST")"
if [[ "$BLUE_FETCH_DELETE" == "1" ]]; then
  if [[ "$BLUE_RESULTS_DEST" == "/" || "$BLUE_RESULTS_DEST" == "$HOME" || "$BLUE_RESULTS_DEST" == "$PROJECT_ROOT" ]]; then
    echo "Error: refusing --delete for broad destination: $BLUE_RESULTS_DEST" >&2
    exit 2
  fi
  RSYNC_DELETE_ARGS+=(--delete)
fi

echo "Resolved fetch:"
echo "  Remote: $BLUE_HOST:$BLUE_DIR/$BLUE_RESULTS_PATH/"
echo "  Local:  $BLUE_RESULTS_DEST/"
echo "  Delete: $BLUE_FETCH_DELETE"

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

echo "Verifying fetched tree with an rsync checksum dry run"
VERIFY_DIFF="$(
  rsync \
    --archive \
    --checksum \
    --delete \
    --dry-run \
    --itemize-changes \
    --rsh="$RSYNC_RSH" \
    "$BLUE_HOST:$BLUE_DIR/$BLUE_RESULTS_PATH/" \
    "$BLUE_RESULTS_DEST/"
)"
if [[ -n "$VERIFY_DIFF" ]]; then
  echo "Error: local result tree differs from the remote after fetch:" >&2
  printf '%s\n' "$VERIFY_DIFF" >&2
  exit 1
fi
echo "Verification complete: local and remote result trees match"

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

echo "Fetch complete: $BLUE_RESULTS_DEST"
