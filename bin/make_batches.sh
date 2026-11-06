#!/usr/bin/env bash
# make_batches.sh: build duplicate-free batch manifests from data/fingerprints.tsv
#
# For each strict fingerprint, keeps ONE copy (the first path in sorted order,
# so reruns always pick the same file) and drops the rest. The kept paths are
# split into numbered manifests of BATCH_SIZE paths each. A batch is a LIST of
# paths, not copied files.
#
# Writes:
#   data/unique_paths.txt         one kept path per line
#   data/duplicates_dropped.tsv   dropped_path <TAB> kept_path  (audit trail)
#   data/batches/batch_NNN.txt    the manifests
#   data/batches/batch_index.csv  batch_id,file_count
#
# Usage:  bin/make_batches.sh            (BATCH_SIZE=5000 by default)
#         BATCH_SIZE=2000 bin/make_batches.sh

set -euo pipefail
export LC_ALL=C   # byte-order sorting: same order on every machine, and faster

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_DIR/data"
FP="$DATA_DIR/fingerprints.tsv"
BATCH_DIR="$DATA_DIR/batches"
BATCH_SIZE="${BATCH_SIZE:-5000}"
LOG_FILE="$REPO_DIR/logs/batches.log"

mkdir -p "$(dirname "$LOG_FILE")"
log() { printf '%s [batches] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

[[ -s "$FP" ]] || die "missing $FP; run: python3 src/fingerprint.py"
[[ "$BATCH_SIZE" =~ ^[0-9]+$ && "$BATCH_SIZE" -gt 0 ]] || die "BATCH_SIZE must be a positive integer"

# --- Keep the first path per fingerprint; record what was dropped ---
# Sort by fingerprint, then path, so "first" is deterministic.
sort -t $'\t' -k1,1 -k3,3 "$FP" |
  awk -F'\t' -v kept="$DATA_DIR/unique_paths.unsorted" -v dropped="$DATA_DIR/duplicates_dropped.tsv" '
    BEGIN { printf "" > dropped }
    $1 != prev { keep = $3; print $3 > kept; prev = $1; next }
    { print $3 "\t" keep > dropped }
  '
sort "$DATA_DIR/unique_paths.unsorted" > "$DATA_DIR/unique_paths.txt"
rm -f "$DATA_DIR/unique_paths.unsorted"

n_in=$(wc -l < "$FP")
n_kept=$(wc -l < "$DATA_DIR/unique_paths.txt")
n_dropped=$(wc -l < "$DATA_DIR/duplicates_dropped.tsv")
(( n_kept + n_dropped == n_in )) || die "kept ($n_kept) + dropped ($n_dropped) != input ($n_in)"
log "input: $n_in  kept: $n_kept  dropped duplicates: $n_dropped"

# --- Split into manifests (rebuilt from scratch each run) ---
rm -rf "$BATCH_DIR"
mkdir -p "$BATCH_DIR"
split -l "$BATCH_SIZE" -d -a 3 --additional-suffix=.txt "$DATA_DIR/unique_paths.txt" "$BATCH_DIR/batch_"

echo "batch_id,file_count" > "$BATCH_DIR/batch_index.csv"
for f in "$BATCH_DIR"/batch_*.txt; do
  id=$(basename "$f" .txt)
  echo "$id,$(wc -l < "$f")" >> "$BATCH_DIR/batch_index.csv"
done

# --- Checks: every kept path is in exactly one batch ---
n_batched=$(cat "$BATCH_DIR"/batch_*.txt | wc -l)
n_distinct=$(cat "$BATCH_DIR"/batch_*.txt | sort -u | wc -l)
(( n_batched == n_kept ))   || die "batched paths ($n_batched) != kept paths ($n_kept)"
(( n_distinct == n_batched )) || die "a path appears in more than one batch"

n_batches=$(( $(wc -l < "$BATCH_DIR/batch_index.csv") - 1 ))
log "wrote $n_batches batches of up to $BATCH_SIZE paths to data/batches/"
