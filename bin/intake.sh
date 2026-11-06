#!/usr/bin/env bash
# intake.sh: process queued batches. Meant to run from cron every few minutes.
#
#   Queue a batch:  touch data/incoming/batch_007     (or: bin/queue_pending.sh)
#   Run by hand:    bin/intake.sh
#   Cron (every 5 minutes):
#     */5 * * * * /home/<you>/pii-pipeline/bin/intake.sh >> /home/<you>/pii-pipeline/logs/cron.log 2>&1
#
# For each queue file (oldest first) it runs bin/run_batch.sh and then:
#   exit 0 / 10  (done / needs_review)  -> removes the queue file
#   exit 75      (pipeline busy)        -> leaves it queued, stops until next run
#   exit 2       (bad batch / manifest) -> moves it to data/incoming/rejected/
#   exit 1, 130  (failed / interrupted) -> retries next run; after 3 failures
#                                          moves it to data/incoming/failed/
# Only one intake runs at a time (its own lock), so a long run started by one
# cron tick isn't duplicated by the next tick.
# Also rotates logs/run.log when it passes 5 MB (keeps 3 old copies).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUEUE="$REPO_DIR/data/incoming"
LOG_FILE="$REPO_DIR/logs/intake.log"
RUN_LOG="$REPO_DIR/logs/run.log"
MAX_TRIES=3
mkdir -p "$QUEUE/rejected" "$QUEUE/failed" "$REPO_DIR/logs"

log() { printf '%s [intake] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

exec 8>"$REPO_DIR/logs/intake.lock"
if ! flock -n 8; then
  exit 0   # another intake is still working through the queue: nothing to do
fi

# --- Log rotation: run.log -> run.log.1 -> .2 -> .3 ---
if [[ -f "$RUN_LOG" ]] && (( $(stat -c %s "$RUN_LOG") > 5 * 1024 * 1024 )); then
  for i in 2 1; do [[ -f "$RUN_LOG.$i" ]] && mv "$RUN_LOG.$i" "$RUN_LOG.$((i + 1))"; done
  mv "$RUN_LOG" "$RUN_LOG.1"
  log "rotated run.log"
fi

# Queue items, oldest first. find (not ls): with no matches ls would list the
# CURRENT folder instead, and intake would "process" project files. Retry
# counters (batch_007.tries) aren't queue items.
items=()
while IFS= read -r f; do items+=("$f"); done < <(
  find "$QUEUE" -maxdepth 1 -type f -name 'batch_*' ! -name '*.tries' -printf '%T@ %p\n' | sort -n | cut -d' ' -f2-
)
(( ${#items[@]} > 0 )) || exit 0
log "queue has ${#items[@]} item(s)"

for item in "${items[@]}"; do
  [[ -f "$item" ]] || continue
  name="$(basename "$item")"
  set +e
  "$REPO_DIR/bin/run_batch.sh" "$name" > /dev/null 2>&1
  rc=$?
  set -e
  case "$rc" in
    0|10)
      rm -f "$item" "$item.tries"
      log "$name finished (exit $rc)" ;;
    75)
      log "$name: pipeline busy (exit 75); will retry next run"
      exit 0 ;;
    2)
      mv "$item" "$QUEUE/rejected/$name"
      log "$name rejected (exit 2: bad batch id or manifest)" ;;
    *)
      tries=$(( $(cat "$item.tries" 2>/dev/null || echo 0) + 1 ))
      echo "$tries" > "$item.tries"
      if (( tries >= MAX_TRIES )); then
        mv "$item" "$QUEUE/failed/$name"; rm -f "$item.tries"
        log "$name failed $tries times (last exit $rc); moved to failed/"
      else
        log "$name failed (exit $rc), attempt $tries of $MAX_TRIES; will retry next run"
      fi ;;
  esac
done
log "queue pass complete"
