#!/usr/bin/env bash
# run_batch.sh: run one batch through the pipeline and route the result.
#
#   bin/run_batch.sh 007        (also accepts 7 or batch_007)
#
# Steps: lock -> redact (Python) -> leak check (Day 6, skipped if not
# installed yet) -> route to done / needs_review / failed.
#
# Routing (operator view: ls output/status/<state>/):
#   done          redacted, no escalations, no leaks
#   needs_review  escalations or leak-check hits: a human must look first
#   failed        the redactor or leak check crashed; output not trusted
#
# Exit codes: 0 done, 10 needs_review, 1 failed, 2 usage error,
#             75 another run holds the lock (try again later), 130 interrupted
#
# Safe to rerun: the redactor writes to a temp folder and only publishes a
# complete batch, so an interrupted run leaves nothing half-finished.
#
# Env: PYTHON (default .venv/bin/python), REDACT_ARGS (e.g. --no-spacy)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/logs/run.log"
LOCK_FILE="$REPO_DIR/logs/pipeline.lock"
STATUS_CSV="$REPO_DIR/logs/batch_status.csv"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"

mkdir -p "$REPO_DIR/logs"
log() { printf '%s [run_batch %s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${BID:-?}" "$*" | tee -a "$LOG_FILE"; }

# --- Arguments ---
if [[ $# -ne 1 ]]; then
  echo "usage: bin/run_batch.sh <batch number, e.g. 007>" >&2
  exit 2
fi
raw="${1#batch_}"
if [[ ! "$raw" =~ ^[0-9]+$ ]]; then
  echo "not a batch number: $1" >&2
  exit 2
fi
BID="batch_$(printf '%03d' "$((10#$raw))")"
MANIFEST="$REPO_DIR/data/batches/$BID.txt"
OUT_DIR="$REPO_DIR/output/$BID"
if [[ ! -f "$MANIFEST" ]]; then
  log "ERROR: no manifest at data/batches/$BID.txt"
  exit 2
fi
if [[ ! -s "$MANIFEST" ]]; then
  log "ERROR: manifest data/batches/$BID.txt is empty"
  exit 2
fi
command -v "$PYTHON" >/dev/null || { log "ERROR: python not found at $PYTHON (create .venv first)"; exit 2; }

# --- Lock: only one pipeline run at a time (cron on Day 8 relies on this) ---
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another run holds the lock; not starting (exit 75)"
  exit 75
fi

trap 'log "interrupted; partial output discarded on next run"; exit 130' INT TERM

route() {  # route <state> <exit code> <detail>
  local state="$1" code="$2" detail="$3"
  rm -f "$REPO_DIR"/output/status/*/"$BID"
  mkdir -p "$REPO_DIR/output/status/$state"
  touch "$REPO_DIR/output/status/$state/$BID"
  [[ -d "$OUT_DIR" ]] && echo "$state" > "$OUT_DIR/STATUS"
  [[ -f "$STATUS_CSV" ]] || echo "batch,status,finished,runtime_s,detail" > "$STATUS_CSV"
  echo "$BID,$state,$(date '+%Y-%m-%dT%H:%M:%S'),$(( $(date +%s) - START )),$detail" >> "$STATUS_CSV"
  log "routed to $state ($detail)"
  # Refresh the CSV the Excel tracker reads. A failed export must not change
  # the batch's result, so it's only logged.
  "$PYTHON" "$REPO_DIR/src/export_tracker.py" >> "$LOG_FILE" 2>&1 || log "warning: tracker export failed"
  exit "$code"
}

START=$(date +%s)
log "start ($(wc -l < "$MANIFEST") messages)"

# --- 1. Redact ---
cd "$REPO_DIR"
# shellcheck disable=SC2086  # REDACT_ARGS is intentionally word-split
if ! "$PYTHON" src/redact.py "$BID" ${REDACT_ARGS:-} >> "$LOG_FILE" 2>&1; then
  route failed 1 "redactor crashed; see logs/run.log"
fi
[[ -f "$OUT_DIR/stats.json" ]] || route failed 1 "redactor finished but stats.json is missing"

escalations=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["escalations_total"])' "$OUT_DIR/stats.json")
parse_failures=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["parse_failures"])' "$OUT_DIR/stats.json")
log "redacted; escalations=$escalations parse_failures=$parse_failures"

# --- 2. Leak check (Day 6). Exit 0 = clean, 3 = leaks found, anything else = broken ---
leaks=0
if [[ -x "$REPO_DIR/bin/leak_check.sh" ]]; then
  set +e
  "$REPO_DIR/bin/leak_check.sh" "$BID" >> "$LOG_FILE" 2>&1
  lc=$?
  set -e
  case "$lc" in
    0) log "leak check clean" ;;
    3) leaks=1; log "leak check found possible leaks" ;;
    *) route failed 1 "leak check crashed (exit $lc)" ;;
  esac
else
  log "leak check not installed yet (Day 6); skipping"
fi

# --- 3. Route ---
if (( escalations > 0 || leaks > 0 || parse_failures > 0 )); then
  route needs_review 10 "escalations=$escalations leaks=$leaks parse_failures=$parse_failures"
fi
route done 0 "clean"
