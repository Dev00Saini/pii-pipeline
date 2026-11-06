#!/usr/bin/env bash
# leak_check.sh: independent re-scan of a redacted batch for anything that
# still looks personal.
#
#   bin/leak_check.sh 000        (also accepts 0 or batch_000)
#
# Deliberately built with DIFFERENT tools from the Python redactor (grep/awk,
# simpler patterns, a different regex engine, a direct lookup against the
# known-people list), so a bug in the redactor's detectors can't also hide
# the leak from this check.
#
# Checks:
#   email       anything shaped like an email address
#   phone       US-style phone numbers: (713) 853-1234, 713-853-1234, 713.853.1234
#   notes_addr  Lotus Notes style: First Last/HOU/ECT, Name/Corp/Enron@Enron
#               (ALL-CAPS hits without "@", e.g. MM/DD/YY, are reported as
#               notes_caps for information only: mostly codes, not people)
#   known_name  any full name from data/known_people.tsv (seen 2+ times)
#   mailbox     dropped headers that name the mailbox owner (X-Folder, X-Origin,
#               X-FileName) or a Notes mailbox file name (*.nsf)
# Not checked on purpose: escalated items (SSN-like, card-like, ambiguous
# single-word names) are left in place by design until a human reviews them.
#
# Writes (in output/batch_NNN/):
#   leak_report.tsv   check <TAB> file <TAB> matched text   (every hit)
#   leak_samples.txt  up to 20 examples per check
#   leaks.json        counts per check
# Exit codes: 0 clean, 3 possible leaks found, 2 usage / missing input, 1 error

set -euo pipefail
export LC_ALL=C

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -ne 1 ]]; then echo "usage: bin/leak_check.sh <batch number>" >&2; exit 2; fi
raw="${1#batch_}"
[[ "$raw" =~ ^[0-9]+$ ]] || { echo "not a batch number: $1" >&2; exit 2; }
BID="batch_$(printf '%03d' "$((10#$raw))")"
OUT="$REPO_DIR/output/$BID"
MSG="$OUT/messages"
[[ -d "$MSG" ]] || { echo "no redacted output at output/$BID/messages" >&2; exit 2; }

REPORT="$OUT/leak_report.tsv"
SAMPLES="$OUT/leak_samples.txt"
SUMMARY="$OUT/leaks.json"
KNOWN="$REPO_DIR/data/known_people.tsv"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# grep exits 1 when it finds nothing. Here that's success, not an error;
# only exit 2+ (a real grep failure) should stop the script.
g() { local rc=0; grep "$@" || rc=$?; (( rc <= 1 )) || { echo "grep failed (exit $rc)" >&2; return 2; }; }

# "path:match" lines from grep -rHo  ->  "check<TAB>relative path<TAB>match"
to_tsv() {
  awk -v check="$1" -v prefix="$MSG/" '{
    if (index($0, prefix) == 1) $0 = substr($0, length(prefix) + 1)
    i = index($0, ":")
    print check "\t" substr($0, 1, i - 1) "\t" substr($0, i + 1)
  }'
}

printf 'check\tfile\tmatch\n' > "$REPORT"

g -rHoP '(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}' "$MSG" \
  | to_tsv email >> "$REPORT"
g -rHoP '(?<![\d-])(?:\(\d{3}\) ?|\d{3}[-. ])\d{3}[-. ]\d{4}(?![\d-])' "$MSG" \
  | to_tsv phone >> "$REPORT"
# Notes-shaped hits: with "@" or a lowercase letter -> notes_addr (counted).
# ALL CAPS with no "@" (MM/DD/YY, ENA/EIM/EGM) -> notes_caps: mostly codes,
# reported for information only and not counted as leaks.
g -rHoP "[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]*){0,3}(?:/[A-Za-z]{2,}){1,3}@[A-Za-z]{2,}|[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]*){0,3}(?:/[A-Z]{2,}){2,3}(?![A-Za-z/])" "$MSG" \
  | to_tsv notes_addr \
  | awk -F'\t' 'BEGIN { OFS = "\t" } { if ($3 !~ /@/ && $3 !~ /[a-z]/) $1 = "notes_caps"; print }' >> "$REPORT"
# .nsf names inside a web/file path (".../auction.nsf") are shared Notes
# databases, not a person's mailbox, so only stand-alone ones count (round 3).
g -rHoP '^[ \t>]*X-(Folder|Origin|FileName):(?! \[REMOVED\]$).*|(?<![/\w.-])[A-Za-z0-9_-]+\.nsf' "$MSG" \
  | to_tsv mailbox >> "$REPORT"

if [[ -s "$KNOWN" ]]; then
  # Full names (2+ words) seen at least twice: whole-word, case-sensitive, fixed strings.
  awk -F'\t' '$2 >= 2 && $1 ~ / / { print $1 }' "$KNOWN" > "$tmp/names.txt"
  g -rHowF -f "$tmp/names.txt" "$MSG" | to_tsv known_name >> "$REPORT"
else
  echo "warning: $KNOWN missing; known_name check skipped" >&2
fi

# --- Counts, samples, summary ---
messages=$(find "$MSG" -type f | wc -l)
declare -A n
total=0
: > "$SAMPLES"
for c in email phone notes_addr known_name mailbox notes_caps; do
  n[$c]=$(awk -F'\t' -v c="$c" 'NR > 1 && $1 == c' "$REPORT" | wc -l)
  [[ "$c" == notes_caps ]] || total=$(( total + n[$c] ))   # notes_caps: info only
  if (( n[$c] > 0 )); then
    echo "== $c (${n[$c]} hits; first 20)" >> "$SAMPLES"
    awk -F'\t' -v c="$c" 'NR > 1 && $1 == c { print $2 "\t" $3 }' "$REPORT" | head -20 >> "$SAMPLES"
  fi
done
files_with=$(awk -F'\t' 'NR > 1 && $1 != "notes_caps" { print $2 }' "$REPORT" | sort -u | wc -l)
per_k=$(awk -v t="$total" -v m="$messages" 'BEGIN { printf "%.1f", (m ? 1000 * t / m : 0) }')

printf '{"batch": "%s", "messages": %d, "files_with_hits": %d, "total": %d, "per_1000_messages": %s, "email": %d, "phone": %d, "notes_addr": %d, "known_name": %d, "mailbox": %d, "notes_caps_info": %d}\n' \
  "$BID" "$messages" "$files_with" "$total" "$per_k" \
  "${n[email]}" "${n[phone]}" "${n[notes_addr]}" "${n[known_name]}" "${n[mailbox]}" "${n[notes_caps]}" > "$SUMMARY"

echo "leak check $BID: messages=$messages hits=$total (${per_k}/1k) files_with_hits=$files_with" \
     "email=${n[email]} phone=${n[phone]} notes_addr=${n[notes_addr]} known_name=${n[known_name]} mailbox=${n[mailbox]}" \
     "(info: notes_caps=${n[notes_caps]})"

(( total == 0 )) && exit 0
exit 3
