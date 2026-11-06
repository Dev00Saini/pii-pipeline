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