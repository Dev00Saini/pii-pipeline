# Runbook

How to set up, run, monitor and recover the PII de-identification pipeline.
Everything runs inside Ubuntu (WSL2) from the repo folder, `~/pii-pipeline`.
Keep the repo on the Linux filesystem, not under `/mnt/c`: it is much faster,
and personal data never touches a synced Windows folder.

## 1. One-time setup

```bash
python3 -m venv .venv
.venv/bin/pip install spacy pytest openpyxl
.venv/bin/python -m spacy download en_core_web_sm
.venv/bin/python -m pytest -q          # all tests should pass
```

## 2. Build the batches (run once, in this order)

| Step | Command | Produces |
|---|---|---|
| Download, verify, unpack | `bin/setup.sh` | `data/maildir/` (checksum pinned in `data/CHECKSUM.txt`) |
| Profile the raw data | `bin/profile_data.sh` | counts and duplicate estimates (see `docs/data_profile.md`) |
| Fingerprint every message | `.venv/bin/python src/fingerprint.py` | `data/fingerprints.tsv`, `data/fingerprint_failures.txt` |
| Drop duplicates, split into batches | `bin/make_batches.sh` | `data/batches/batch_NNN.txt`, `batch_index.csv`, `duplicates_dropped.tsv` |
| Build the known-people list | `.venv/bin/python src/known_people.py` | `data/known_people.tsv` |

Every step is safe to rerun. Files listed in `data/fingerprint_failures.txt`
are not batched, so review them by hand: a file that silently drops out of a
PII pipeline is never checked for PII.

## 3. Run batches

**One batch by hand:**
```bash
bin/run_batch.sh 7          # also accepts 007 or batch_007
```
It takes the pipeline lock, redacts the batch, runs the independent leak check
(`bin/leak_check.sh`), routes the result, and updates the Excel tracker's CSV.

**Many batches, unattended (cron):**
```bash
bin/queue_pending.sh        # queue batches that have never run
bin/queue_pending.sh --all  # queue every batch (full re-run after a rule change)
crontab -e                  # add the line below
*/5 * * * * /home/<you>/pii-pipeline/bin/intake.sh >> /home/<you>/pii-pipeline/logs/cron.log 2>&1
```
`bin/intake.sh` works through `data/incoming/` oldest first, one batch at a time.

## 4. Check status

```bash
echo "left in queue: $(find data/incoming -maxdepth 1 -type f -name 'batch_*' ! -name '*.tries' | wc -l)"
tail -5 logs/batch_status.csv        # batch, status, finished, runtime_s, detail
ls output/status/*/                  # which batches are in which state
tail -20 logs/intake.log             # what intake did and why
```
For a dashboard, open the tracker workbook and use **Data > Refresh All**.
It reads `exports/batches.csv`, which holds counts only and no personal data.

## 5. What the results mean

`bin/run_batch.sh` exit codes and routing:

| Exit | State | Meaning | What to do |
|---|---|---|---|
| 0 | `done` | Redacted, no escalations, leak check clean | Nothing. Output can be released. |
| 10 | `needs_review` | Escalations or leak-check hits | Review before release (section 6). |
| 1 | `failed` | Redactor or leak check crashed | Read `logs/run.log`, fix, rerun the batch. Output is not trusted. |
| 2 | (none) | Bad batch number, or missing/empty manifest | Check `data/batches/`. Intake moves it to `data/incoming/rejected/`. |
| 75 | (none) | Another run holds the lock | Nothing. Intake leaves it queued and retries next tick. |
| 130 | (none) | Interrupted (Ctrl+C) | Rerun. Nothing half-written is published. |

How intake handles each code: 0/10 remove the queue file. 75 stops until the
next tick. 2 moves the file to `rejected/`. 1 or 130 retries, and after 3
failures moves it to `data/incoming/failed/`.

## 6. Review flagged items

Escalations (SSN-shaped and card-shaped numbers, ambiguous single-word names)
are left in place on purpose and logged to `output/batch_NNN/escalations.tsv`.

```bash
.venv/bin/python src/export_review_queue.py      # exports/review_queue.csv + review_sample.csv
```
These files contain real personal data. Keep them, and the review workbook,
inside Ubuntu (`review/`). Never copy them to OneDrive or GitHub.

For leak-check hits, see what was missed and why, with the output masked:
```bash
less output/batch_007/leak_samples.txt
.venv/bin/python src/explain_leak.py 007 phone 10
```

## 7. Recovery

| Problem | Fix |
|---|---|
| A batch failed | `tail -50 logs/run.log`, fix the cause, then `bin/run_batch.sh N`. Reruns are safe. |
| A queue file is in `data/incoming/failed/` | Fix the cause, then `mv data/incoming/failed/batch_N data/incoming/`. |
| A stale `output/batch_NNN.tmp/` | An interrupted run. It is never treated as finished. Delete it, or let the next run replace it. |
| `logs/run.log` keeps growing | Intake rotates it at 5 MB and keeps 3 old copies. |
| After changing a detection rule | `.venv/bin/python -m pytest -q`, then `bin/queue_pending.sh --all`. |

`secrets/placeholder_map.json` holds the mapping from placeholders back to real
values. It is written atomically with permissions 600 and must never be
committed or shared.

## 8. Test the failure handling

```bash
bin/failure_tests.sh               # tests 1-5, about 30 seconds
bin/failure_tests.sh --disk-full   # also the disk-full test (needs sudo)
```
Run these only when no batches are queued or running: the tests take the
pipeline lock and temporarily swap the placeholder map (restored afterwards).
