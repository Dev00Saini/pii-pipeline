# Data Profile: Enron Email Corpus

Fill this in from `data/profile_stats.txt` and by reading real messages. Counts only:
no names, addresses or message text from the data go in this file (it gets committed).

## Source
- Version: May 7, 2015 (CMU CALO Project)
- Downloaded: 2026-11-05
- Pinned SHA-256: b3da1b3fe0369ec3140bb4fbce94702c33b7da810ec15d718b3fadf5cd748ca7

## Counts
| Measure | Value |
|---|---|
| Message files |517,401 |
| User folders |150 |
| All folders |3,499 |
| Size on disk |2.6 GB (423 MB compressed) |
| Empty files |0 |
| Exact duplicate groups / extra copies |0 / 0 |
| Extra copies by Message-ID |0 (every file has a unique Message-ID) |

## What the duplicates tell us
Why do byte-identical duplicates and Message-ID duplicates give different numbers?
Which definition should Day 2 use for dedup, and why?

## Where personal information appears
Describe the patterns you saw, without copying real values. For example:
"display names in X-From / X-To", "phone numbers in signatures in three formats".

- Headers:
- Signatures:
- Phone number formats seen:
- Forwarded chains:
- Anything surprising:

## Problems hit during setup
What went wrong, and how you fixed it (download, speed, disk space, cron, etc.).
