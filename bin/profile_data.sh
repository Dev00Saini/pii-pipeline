#!/usr/bin/env bash
# profile_data.sh: count files, folders, and duplicates in the unpacked corpus.
#
# Writes:
#   data/checksums.md5     one "md5  path" line per message (reused on Day 2 for dedup)
#   data/profile_stats.txt the numbers below (stays in data/, which is gitignored,
#                          because the folder names are people's names)
#
# Usage:  bin/profile_data.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_DIR/data"
MAILDIR="$DATA_DIR/maildir"
CHECKSUMS="$DATA_DIR/checksums.md5"
STATS="$DATA_DIR/profile_stats.txt"
LOG_FILE="$REPO_DIR/logs/setup.log"

mkdir -p "$(dirname "$LOG_FILE")"
log() { printf '%s [profile] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

[[ -f "$DATA_DIR/.unpacked" ]] || die "corpus not unpacked yet; run bin/setup.sh first"
start=$(date +%s)

# --- Basic counts ---
n_files=$(find "$MAILDIR" -type f | wc -l)
n_users=$(find "$MAILDIR" -mindepth 1 -maxdepth 1 -type d | wc -l)
n_folders=$(find "$MAILDIR" -mindepth 1 -type d | wc -l)
size=$(du -sh "$MAILDIR" | cut -f1)
n_empty=$(find "$MAILDIR" -type f -empty | wc -l)

# --- Exact (byte-identical) duplicates ---
# -print0 / -0 / -z keep file names with spaces or odd characters intact.
log "hashing $n_files files (a few minutes)"
find "$MAILDIR" -type f -print0 | sort -z | xargs -0 md5sum > "$CHECKSUMS"
read -r dup_groups dup_extra < <(
  awk '{print $1}' "$CHECKSUMS" | sort | uniq -c |
  awk '$1 > 1 { groups++; extra += $1 - 1 } END { print groups+0, extra+0 }'
)

# --- Duplicates by Message-ID header (the same email saved in several folders) ---
# Byte-identical is the strict definition; Message-ID catches copies that differ
# only slightly (e.g. a header added by the folder they were filed in).
log "counting Message-ID duplicates"
find "$MAILDIR" -type f -print0 |
  xargs -0 grep -m1 -h -i '^Message-ID:' 2>/dev/null |
  tr -d '\r' | sort > "$DATA_DIR/message_ids.tmp" || true
n_with_id=$(wc -l < "$DATA_DIR/message_ids.tmp")
n_unique_id=$(uniq "$DATA_DIR/message_ids.tmp" | wc -l)
rm -f "$DATA_DIR/message_ids.tmp"

# --- Duplicates by header fingerprint (Date + From + Subject) ---
# The corpus files the same email in several folders. Each copy gets its own
# generated Message-ID and its own X-Folder header, so the two checks above
# miss them. Files use CRLF line endings, so strip \r before comparing.
log "counting header-fingerprint duplicates"
find "$MAILDIR" -type f -print0 |
  xargs -0 awk '
    FNR==1 { d=""; f=""; s="" }
    { sub(/\r$/, "") }
    /^Date:/    && d=="" { d=$0 }
    /^From:/    && f=="" { f=$0 }
    /^Subject:/ && s=="" { s=$0 }
    /^$/ { print d "|" f "|" s "\t" FILENAME; nextfile }
  ' > "$DATA_DIR/header_keys.tsv"
read -r fp_groups fp_extra < <(
  cut -f1 "$DATA_DIR/header_keys.tsv" | sort | uniq -c |
  awk '$1 > 1 { groups++; extra += $1 - 1 } END { print groups+0, extra+0 }'
)

# --- Biggest user folders (for your profile notes; stays local) ---
top_users=$(find "$MAILDIR" -mindepth 2 -type f | awk -F/ -v d="$MAILDIR" '
  { sub("^" d "/", ""); split($0, p, "/"); c[p[1]]++ }
  END { for (u in c) print c[u], u }' | sort -rn | head -5)

{
  echo "Enron corpus profile, $(date '+%Y-%m-%d %H:%M')"
  echo "message files:                 $n_files"
  echo "user folders:                  $n_users"
  echo "all folders (incl. subfolders): $n_folders"
  echo "size on disk:                  $size"
  echo "empty files:                   $n_empty"
  echo "exact duplicate groups:        $dup_groups"
  echo "extra exact copies:            $dup_extra"
  echo "files with a Message-ID:       $n_with_id"
  echo "unique Message-IDs:            $n_unique_id"
  echo "extra copies by Message-ID:    $(( n_with_id - n_unique_id ))"
  echo "fingerprint duplicate groups:  $fp_groups"
  echo "extra copies by fingerprint:   $fp_extra"
  echo "unique messages (fingerprint): $(( n_files - fp_extra ))"
  echo
  echo "largest user folders (files, folder):"
  echo "$top_users"
} | tee "$STATS"

log "profile written to $STATS in $(( $(date +%s) - start ))s"
