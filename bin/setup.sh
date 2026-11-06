#!/usr/bin/env bash
# setup.sh: download, verify, and unpack the Enron email corpus.
#
# Safe to rerun: skips the download if the archive exists, verifies the
# checksum every time, and only unpacks if a previous unpack didn't finish.
#
# Usage:  bin/setup.sh
# Test override:  ENRON_URLS="file:///path/fake.tgz" bin/setup.sh

set -euo pipefail   # stop on any error, unset variable, or failed pipe stage

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_DIR/data"
ARCHIVE="$DATA_DIR/enron_mail_20150507.tgz"
CHECKSUM_FILE="$DATA_DIR/CHECKSUM.txt"
MAILDIR="$DATA_DIR/maildir"
DONE_MARKER="$DATA_DIR/.unpacked"
LOG_FILE="$REPO_DIR/logs/setup.log"

# CMU's page has used both file names over the years, so try each in order.
URLS=${ENRON_URLS:-"https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz https://www.cs.cmu.edu/~enron/enron_mail_20150507.tgz"}

mkdir -p "$DATA_DIR" "$(dirname "$LOG_FILE")"

log() { printf '%s [setup] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

start=$(date +%s)
log "starting setup in $REPO_DIR"

# --- 0. Warn if running on the Windows drive (very slow with ~500K files) ---
case "$REPO_DIR" in
  /mnt/*) log "WARNING: repo is on the Windows drive. Move it to ~/ inside Ubuntu; file operations here will be very slow." ;;
esac

# --- 1. Required tools ---
for cmd in curl tar sha256sum find; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd (try: sudo apt install $cmd)"
done

# --- 2. Download (skipped if the archive already exists) ---
if [[ -f "$ARCHIVE" ]]; then
  log "archive already present, skipping download"
else
  downloaded=0
  for url in $URLS; do
    log "downloading $url"
    # Download to a .part file so an interrupted download never looks complete.
    if curl -fL --retry 3 --retry-delay 5 -o "$ARCHIVE.part" "$url"; then
      mv "$ARCHIVE.part" "$ARCHIVE"
      downloaded=1
      break
    fi
    log "download failed: $url"
    rm -f "$ARCHIVE.part"
  done
  [[ $downloaded -eq 1 ]] || die "could not download the corpus from any URL"
fi
log "archive size: $(du -h "$ARCHIVE" | cut -f1)"

# --- 3. Checksum: pin on first download, verify on every run after ---
# CMU doesn't publish a checksum, so the first download's SHA-256 becomes the
# reference. Any later change to the archive (corruption, a different version)
# stops the pipeline instead of silently producing different numbers.
actual=$(sha256sum "$ARCHIVE" | awk '{print $1}')
if [[ -f "$CHECKSUM_FILE" ]]; then
  expected=$(awk '{print $1}' "$CHECKSUM_FILE")
  if [[ "$actual" != "$expected" ]]; then
    die "checksum mismatch (expected $expected, got $actual). The archive changed or is corrupt. If you deliberately replaced it, delete $CHECKSUM_FILE and rerun to re-pin."
  fi
  log "checksum OK ($actual)"
else
  echo "$actual  $(basename "$ARCHIVE")" > "$CHECKSUM_FILE"
  log "no published checksum; pinned first-download SHA-256 $actual"
fi

# --- 4. Unpack (into a temp folder, then move, so a half-finished unpack is never used) ---
if [[ -f "$DONE_MARKER" && -d "$MAILDIR" ]]; then
  log "already unpacked, skipping"
else
  tmp="$DATA_DIR/unpack_tmp"
  rm -rf "$tmp" "$MAILDIR" "$DONE_MARKER"
  mkdir -p "$tmp"
  log "unpacking (can take several minutes)"
  tar -xzf "$ARCHIVE" -C "$tmp"

  # The archive should contain exactly one top-level folder (normally maildir/).
  mapfile -t top < <(find "$tmp" -mindepth 1 -maxdepth 1)
  [[ ${#top[@]} -eq 1 && -d "${top[0]}" ]] || die "expected one top-level folder in the archive, found ${#top[@]} entries"
  mv "${top[0]}" "$MAILDIR"
  rmdir "$tmp"
  touch "$DONE_MARKER"
  log "unpacked to $MAILDIR"
fi

# --- 5. Quick sanity check ---
n_files=$(find "$MAILDIR" -type f | wc -l)
[[ $n_files -gt 0 ]] || die "maildir contains no files"
log "message files: $n_files"
log "setup finished in $(( $(date +%s) - start ))s. Next: bin/profile_data.sh"
