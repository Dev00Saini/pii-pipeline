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