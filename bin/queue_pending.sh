#!/usr/bin/env bash
# queue_pending.sh: queue every batch that hasn't produced output yet.
#   bin/queue_pending.sh          -> queues not-run batches
#   bin/queue_pending.sh --all    -> queues every batch (full re-run)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$REPO_DIR/data/incoming"
n=0
for m in "$REPO_DIR"/data/batches/batch_[0-9]*.txt; do
  b="$(basename "$m" .txt)"
  if [[ "${1:-}" == "--all" || ! -f "$REPO_DIR/output/$b/STATUS" ]]; then
    touch "$REPO_DIR/data/incoming/$b"; n=$((n + 1)); sleep 0.01   # keep queue order
  fi
done
echo "queued $n batch(es) in data/incoming/"
