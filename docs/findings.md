# Findings

## Duplicate removal (Days 1–2)
| Method | Unique emails | Notes |
|---|---|---|
| Byte-identical files | 517,401 (0 duplicates) | Copies differ in per-folder headers |
| Message-ID | 517,401 (0 duplicates) | IDs were generated per file |
| Date + From + Subject | 251,727 | Merges 2,994 emails that are actually different |
| **Date + From + To + Cc + Subject + body** | **254,721** | Used for batching |

About 51% of files (262,680) are copies of another email filed in a different folder.
The header-only fingerprint would have merged 2,994 distinct emails, and those would
never have been checked for personal information, so the stricter fingerprint is used.

## Detector tuning on batch_000 (5,000 emails)
Reviewed 10 random matches per type by hand after each change.

| Round | Change | Result |
|---|---|---|
| 0 | First version | card_like: 14 flags, all false (zero-padded IDs, dates, a UK phone number) |
| 1 | Card shape rules (starts 3–6, standard grouping); international phones | card_like 14 → 2; phone 2,723 → 2,767 |
| 2 | Join Notes names wrapped as "First \n Last/ORG" | single-word names 1,226 (18.5%) → ___ |

Decision: all phone numbers are redacted, including toll-free business numbers.
Safer than trying to tell business and personal numbers apart.

| 2 | Join Notes names wrapped as "First \n Last/ORG" | single-word names 1,226 (18.5%) → 112 (1.7%) |
| 3 | Reject look-alikes: name must have lowercase letters; no-@ org parts must be ALL CAPS | Notes names 6,613 → ___; single-word 112 → ___ |

## Name detection (Day 4, batch_000)
Known-people list: 38,181 names from X-From/X-To/X-cc headers. spaCy adds names
the list can't match (first or last names alone). 18 of 20 random spaCy names were real people.

| Round | Change | Result |
|---|---|---|
| 4 | Notes names: particles ("del"), wrap after an initial | single-word Notes names 39 → 34 (0.5%) |
| 5 | Escalate ambiguous words (Will, May, Mark) only at sentence start; ignore header words; drop newsletters from list | escalations 602 → 62 per batch (−90%) |
| 6 | Trim header words glued on from the next line ("John\nSubject"); speed fix | glued header words ~1,260 → 0; 35 → 48 emails/s |

Decision: public figures are redacted like everyone else, for consistency.
Known limitation: in two-column forwarded headers, a first name stranded on another
line is not caught by the Notes detector.

## Independent leak check (Day 6, batches 000–002, 15,000 emails)
`bin/leak_check.sh` re-scans redacted output with grep/awk only: different patterns,
a different regex engine, and a direct lookup against the known-people list, so a
redactor bug can't hide its own leak. `src/explain_leak.py` shows (masked) which
detector matched at each leak, or that none did.

| Round | Fix (cause found with the explain tool) | Hits 000 / 001 / 002 | Total | per 1k |
|---|---|---|---|---|
| 0 | Baseline | 960 / 1,762 / 681 | 3,403 | 227 |
| 1 | Emails in Outlook quotes ('a@b.com') or starting with "."; longest match wins overlaps (an escalated word no longer blocks a longer redaction); ALL-CAPS Notes names with @ | 161 / 297 / 181 | 639 | 43 |
| 2 | Header names with quotes, "- Title", ".Suffix"; Notes with 2 domains / 5 org parts; phones glued to a word or with a country code | 26 / 61 / 76 | 163 | 11 |
| 3 | Possessives ("John Smith's"); phones with a word glued after; ignore .nsf inside URLs | 16 / 45 / 28 | 89 | 6 |
| 4 | Names joined by hyphens ("Interview-Rick Buy"); Notes with 3 domains / "_"; X-Folder lines inside forwarded bodies | __ / __ / __ | __ | __ |

**Result: 3,403 → __ hits (−__%)**, while the check itself got stricter (known-people list 38,181 → 39,705 names).

Known limitations: X.400-style addresses with underscores instead of spaces
(`Tom_Smith_NA/...`); a name glued to lowercase letters before it; first names
stranded on another line in two-column forwarded headers. Escalated items
(SSN-like, card-like, ambiguous single names) are left in place by design until
reviewed (Day 9).
## Full-corpus run (Day 8, re-run Day 9 with final code)

All 51 batches were queued with `bin/queue_pending.sh --all` and processed
unattended by cron (`bin/intake.sh`). Final run finished 2026-11-06 10:18.
Every batch was redacted with the same code.

| Measure | Result |
|---|---|
| Batches run | 51 of 51, 0 failed |
| Emails processed | 254,721 (unique, after dropping 262,680 copies) |
| Email addresses redacted | 2,901,943 |
| Names redacted | 3,365,631 |
| Phone numbers redacted | 147,368 |
| Items escalated for human review | 2,928 (4,561 before the Day 9 rule change) |
| Independent leak-check hits | 1,247 (4.9 per 1,000 emails) |
| Average time per batch | 1.6 minutes |

Every batch ends in `needs_review` because every batch has at least one
escalated item, which by design must be looked at before release.

## Failure tests (Day 8)

`bin/failure_tests.sh`, run on the real setup: 6 of 6 passed.

| Test | Expected | Result |
|---|---|---|
| 0. Empty queue | no-op, project files untouched | pass |
| 1. Batch with no manifest | moved to rejected/ (exit 2) | pass |
| 2. Empty batch | moved to rejected/ (exit 2) | pass |
| 3. Garbage file inside a batch | needs_review, 1 parse failure | pass |
| 4. Killed mid-batch, then next run | nothing published; rerun completes | pass |
| 5. Two runs at the same time | second intake no-op; direct run exit 75 | pass |

Writing these tests found two real bugs. Intake used `ls` on the queue, and
with an empty queue it listed the project folder instead and moved README.md
and pytest.ini into rejected/ (fixed with `find`). The test script also read
the wrong exit code, so no test could fail (fixed, and verified by breaking a
test on purpose).

## Human review of escalated items (Day 9)

A fixed random sample of 150 escalated items (seed 42, drawn from 47
batches, weighted toward SSN- and card-shaped numbers) was reviewed by hand in Excel. Each
item was judged only from its context: Confirmed PII, False positive, or Needs
escalation.

| | Reviewed | Confirmed PII | False-positive rate |
|---|---|---|---|
| All | 150 | 120 | 13% |
| Names | 109 | | 9% |
| Numbers (SSN- and card-shaped) | 41 | | 22% |

What the review showed:
- **Most escalated names are real people.** At the start of a sentence, Bob,
  Brown, Drew, Frank, Pat, Rob, Rod and Sue were a real person in every
  reviewed case (3 or more each, 44 items, 0 false positives). Escalating
  them only cost review time.
- **Some words really are ambiguous.** Bill (3 of 10 false), Mark (4 of 32),
  Ed, Don and Max had false positives. Duke is often Duke Energy, a company.
  These stay escalated.
- **Number false positives cluster.** 4 of the 9 were slices of lists of
  sequential IDs ("3083 3084 3085 3086") that pass the card checksum by
  coincidence.

## Rule change from the review (Day 9)

1. The 8 words above are now redacted at the start of a sentence instead of
   escalated. The trade-off is deliberate: an occasional ordinary word gets
   redacted too, and in de-identification hiding too much is the safer error.
2. A card-shaped match made of 4-digit groups that count upward by 1 to 10 is
   no longer escalated. Real card numbers are still caught (tested).

Measured on the full re-run:

| | Before | After | Change |
|---|---|---|---|
| Escalations (all) | 4,561 | 2,928 | −1,633 (−36%) |
| Unique review-queue items | 4,551 | 2,919 | −1,632 (−36%) |
| Name items | 4,475 | 2,848 | −1,627 |
| Card-shaped items | 39 | 34 | −5 |
| SSN-shaped items | 37 | 37 | 0 |
| Names redacted | 3,364,003 | 3,365,631 | +1,628 |
| Leak-check hits | 1,247 | 1,247 | 0 |

The name items that left the queue reappear almost one-for-one as redacted
names, and the leak check found nothing new, so the change moved work off the
human reviewer without letting anything through.

Limitation: the review sample measures how often *escalated* items are real
PII. It does not measure how much PII the pipeline misses overall (recall);
that would need a separate hand-labeled sample from batches never used for
tuning, which this project has not done.
