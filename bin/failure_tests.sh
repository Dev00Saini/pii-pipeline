#!/usr/bin/env bash
# failure_tests.sh: run the planned failure tests and report what happened.
#
#   bin/failure_tests.sh               tests 1-5 (about 30 seconds)
#   bin/failure_tests.sh --disk-full   also test 6 (needs sudo: mounts a tiny
#                                      temporary disk over output/ for a moment)
#
# Uses small made-up batches (batch_901..906) built from fake messages, and
# --no-spacy for speed: these tests check the plumbing (queueing, routing,
# locking, recovery), not detection quality. Everything they create is removed
# afterwards, and the placeholder map is restored to exactly how it was.

set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
export REDACT_ARGS="--no-spacy"
MAP="secrets/placeholder_map.json"
FAKE="data/maildir/_failtest"
INTAKE_LOG="logs/intake.log"
BACKUP="$(mktemp)"
pass=0; fail=0
RESULTS=()

cleanup() {
  mountpoint -q output 2>/dev/null && sudo umount output
  rm -rf "$FAKE" data/batches/batch_90[1-6].txt output/batch_90[1-6] output/batch_90[1-6].tmp \
         output/status/*/batch_90[1-6] data/incoming/batch_90[1-6]* data/incoming/*/batch_90[1-6]*
  if [[ -s "$BACKUP" ]]; then cp "$BACKUP" "$MAP"; elif [[ -f "$BACKUP.none" ]]; then rm -f "$MAP"; fi
  rm -f "$BACKUP" "$BACKUP.none"
  .venv/bin/python src/export_tracker.py > /dev/null 2>&1 || true   # tracker CSV back to real data
}
trap cleanup EXIT
if [[ -f "$MAP" ]]; then cp "$MAP" "$BACKUP"; else : > "$BACKUP"; touch "$BACKUP.none"; fi

check() {  # check <test name> <expected> <actual> <status: 0 = condition held>
  if [[ "$4" == 0 ]]; then pass=$((pass + 1)); s="PASS"; else fail=$((fail + 1)); s="FAIL"; fi
  RESULTS+=("$(printf '%-4s | %-42s | %-34s | %s' "$s" "$1" "$2" "$3")")
}
status_of() { cat "output/$1/STATUS" 2>/dev/null || echo "none"; }

# --- Fake messages (no real data) ---
mkdir -p "$FAKE" data/incoming logs
# Safety check for the intake bug found while writing these tests: with an
# empty queue, intake must not touch anything outside data/incoming/.
touch_count_before=$(ls -1 | wc -l)
for i in $(seq 1 30); do
  printf 'Message-ID: <%s.test>\nDate: Mon, 1 Jan 2001\nFrom: test.user%s@example.com\n\nTest body %s. Call 555-010-%04d.\n' \
    "$i" "$i" "$i" "$i" > "$FAKE/$i."
done
printf 'Message-ID: <bin>\n\x00\x01\x02\x03 binary garbage' > "$FAKE/garbage."
fake_manifest() { ls -1 "$FAKE"/[0-9]*. | head -"$2" > "data/batches/$1.txt"; }

# 0. Empty queue -> intake does nothing (and never touches project files)
bin/intake.sh; rc=$?
[[ "$rc" == 0 && "$(ls -1 | wc -l)" == "$touch_count_before" && -z "$(ls -A data/incoming/rejected 2>/dev/null)" ]]; ok=$?
check "0. empty queue" "no-op, project files untouched" "exit $rc, files in project: $(ls -1 | wc -l)/$touch_count_before" "$ok"

# 1. Queued batch with no manifest -> rejected, not retried forever
touch data/incoming/batch_901
bin/intake.sh
[[ -f data/incoming/rejected/batch_901 ]]; ok=$?
check "1. batch with no manifest" "rejected/ (exit 2)" \
  "$( [[ -f data/incoming/rejected/batch_901 ]] && echo 'rejected/' || echo 'not rejected')" "$ok"

# 2. Empty manifest -> rejected
: > data/batches/batch_902.txt; touch data/incoming/batch_902
bin/intake.sh
[[ -f data/incoming/rejected/batch_902 ]]; ok=$?
check "2. empty batch" "rejected/ (exit 2)" \
  "$( [[ -f data/incoming/rejected/batch_902 ]] && echo 'rejected/' || echo 'not rejected')" "$ok"

# 3. Binary garbage inside a batch -> other messages redacted, batch needs_review
{ fake_manifest batch_903 5; cat data/batches/batch_903.txt; echo "$FAKE/garbage."; } > /tmp/m903 && mv /tmp/m903 data/batches/batch_903.txt
bin/run_batch.sh 903 > /dev/null 2>&1
pf=$(.venv/bin/python -c 'import json;print(json.load(open("output/batch_903/stats.json"))["parse_failures"])' 2>/dev/null || echo "?")
[[ "$(status_of batch_903)" == needs_review && "$pf" == 1 ]]; ok=$?
check "3. garbage file inside a batch" "needs_review, 1 parse failure" "$(status_of batch_903), $pf parse failure(s)" "$ok"

# 4. Run killed mid-batch (like a crash) -> nothing published, retried and finished next run
fake_manifest batch_904 30; touch data/incoming/batch_904
set -m
PII_TEST_DELAY_S=0.15 bin/intake.sh & pg=$!
set +m
sleep 2; kill -KILL -- -"$pg" 2>/dev/null; wait "$pg" 2>/dev/null
after_kill="final=$( [[ -d output/batch_904 ]] && echo yes || echo no), queued=$( [[ -f data/incoming/batch_904 ]] && echo yes || echo no)"
bin/intake.sh
[[ "$after_kill" == "final=no, queued=yes" && "$(status_of batch_904)" != none && ! -d output/batch_904.tmp && ! -f data/incoming/batch_904 ]]; ok=$?
check "4. killed mid-batch, then next run" "nothing published; rerun completes" "after kill: $after_kill; rerun: $(status_of batch_904)" "$ok"

# 5. Overlapping runs -> second intake does nothing; direct second run refused (75)
fake_manifest batch_905 30; fake_manifest batch_906 3; touch data/incoming/batch_905
PII_TEST_DELAY_S=0.1 bin/intake.sh & first=$!
sleep 1
lines_before=$(wc -l < "$INTAKE_LOG")
bin/intake.sh; second_intake=$?
lines_after=$(wc -l < "$INTAKE_LOG")
bin/run_batch.sh 906 > /dev/null 2>&1; direct=$?
wait "$first"
[[ "$second_intake" == 0 && "$lines_after" == "$lines_before" && "$direct" == 75 ]]; ok=$?
check "5. two runs at the same time" "2nd intake no-op; direct run exit 75" \
  "2nd intake exit $second_intake, logged $((lines_after - lines_before)) lines; direct exit $direct" "$ok"

# 6. Disk full (optional) -> batch fails cleanly, nothing half-written published
if [[ "${1:-}" == "--disk-full" ]]; then
  rm -rf output/batch_906 output/status/*/batch_906
  for i in $(seq 1 30); do head -c 20000 /dev/zero | tr '\0' 'x' >> "$FAKE/$i."; done   # bigger messages
  fake_manifest batch_906 30
  sudo mount -t tmpfs -o size=100k tmpfs output
  bin/run_batch.sh 906 > /dev/null 2>&1; rc=$?
  published=$( [[ -f output/batch_906/stats.json ]] && echo yes || echo no)
  sudo umount output
  [[ "$rc" == 1 && "$published" == no ]]; ok=$?
  check "6. disk full while writing output" "failed (exit 1), nothing published" "exit $rc, published=$published" "$ok"
  grep -q "No space left" logs/run.log && echo "   (run.log shows: No space left on device)"
fi

echo
printf '%-4s | %-42s | %-34s | %s\n' "" "test" "expected" "actual"
printf '%s\n' "${RESULTS[@]}"
echo
echo "passed: $pass   failed: $fail"
(( fail == 0 ))
