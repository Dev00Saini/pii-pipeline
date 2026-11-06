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