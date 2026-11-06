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