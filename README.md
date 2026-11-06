# PII De-identification Pipeline

A Linux pipeline (Bash + Python) that removes personal information from a
large public research email dataset, verifies the result with an independent
check, routes uncertain items to a human reviewer, and tracks operations in
Excel.

**Data:** the [Enron Email Dataset](https://www.cs.cmu.edu/~enron/) (CMU, May
2015 version): 517,401 email files from 150 users. Raw data, outputs, review
files and the placeholder map are never committed (see `.gitignore`).

## Results (full corpus)

| | |
|---|---|
| Emails processed | 254,721 unique (51% of files were copies, removed first) |
| Redacted | 2,901,943 email addresses, 3,365,631 names, 147,368 phone numbers |
| Batches | 51 of 51 run unattended by cron, 0 failed, 1.6 min per batch |
| Independent leak check | 1,247 hits (4.9 per 1,000 emails); tuning cut hits on the first 15,000 emails from 3,403 to 41 (−98.8%) |
| Human review | 150-item sample reviewed in Excel; the rule change it led to cut items needing review from 4,561 to 2,928 (−36%) with no new leaks |
| Failure handling | 6 of 6 automated failure tests pass (kill mid-batch, overlapping runs, empty or bad batches, corrupt files) |

Details and the story behind each number: [`docs/findings.md`](docs/findings.md).

## How it works

```
raw emails ──► dedup ──► batches ──► redact ──► leak check ──► route
 517,401      fingerprint  51 × 5,000   Python      grep/awk      done / needs_review / failed
                                         │
                                         └─► uncertain items ──► review queue ──► Excel review
```

1. **Intake and profiling** (`bin/setup.sh`, `bin/profile_data.sh`). Download
   with a pinned checksum. Profiling found that copies of an email differ only
   in per-folder headers, so byte and Message-ID checks find no duplicates.
2. **Deduplication** (`src/fingerprint.py`, `bin/make_batches.sh`). A content
   fingerprint (date, sender, recipients, subject, body) keeps one copy of each
   email. A header-only fingerprint would have wrongly merged 2,994 distinct
   emails, which would then never have been checked for PII.
3. **Detection and redaction** (`src/detect.py`, `src/names.py`,
   `src/redact.py`). Regular expressions for email addresses, Lotus Notes
   addresses and phone numbers; spaCy plus a list of known people built from
   the email headers for names. The same person always gets the same
   placeholder (`[PERSON_00014]`). SSN- and card-shaped numbers and ambiguous
   words like "Mark" or "Bill" are flagged for review instead of guessed.
4. **Independent leak check** (`bin/leak_check.sh`). Re-scans the output with
   different tools (grep/awk, simpler patterns), so a bug in the redactor
   can't also hide its own leaks. `src/explain_leak.py` shows why a leak was
   missed, with the text masked.
5. **Operations** (`bin/run_batch.sh`, `bin/intake.sh`). One batch at a time
   under a lock, crash-safe publishing (temp folder, then rename), clear exit
   codes, routing, a cron-driven queue with retries, and log rotation.
6. **Review and tracking (Excel).** An operations workbook reads
   `exports/batches.csv` through Power Query (status, throughput, leak rates,
   PivotTable). A separate review workbook, kept inside Linux because it holds
   real data, records decisions with dropdowns, XLOOKUP and COUNTIFS.

## Run it

See [`RUNBOOK.md`](RUNBOOK.md) for setup, running, monitoring and recovery.

```bash
bin/setup.sh && .venv/bin/python src/fingerprint.py && bin/make_batches.sh
.venv/bin/python src/known_people.py
bin/run_batch.sh 0            # one batch
bin/queue_pending.sh          # or queue them all for cron
.venv/bin/python -m pytest -q
```

## Limitations

- The leak check catches patterns it knows. It cannot prove that nothing was
  missed, and overall recall has not been measured on a hand-labeled sample.
- Known gaps: X.400-style underscore addresses, a name glued to lowercase text
  before it, and first names stranded in two-column forwarded headers.
- Escalated items are left in place until reviewed, so no batch is
  release-ready without a human pass.

## Stack

Bash (flock, cron, grep, awk, find), Python 3 (spaCy, pytest), Excel (Power
Query, structured tables, XLOOKUP, COUNTIFS, PivotTables), Ubuntu on WSL2, git.
