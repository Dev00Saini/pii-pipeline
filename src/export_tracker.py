"""export_tracker.py: write the CSV the Excel tracker reads (exports/batches.csv).

One row per batch in data/batches/batch_index.csv, including batches not run
yet (status "not_run"), so the tracker shows overall progress. Values come
from each batch's stats.json, leaks.json and STATUS file.

Counts and statuses only: no personal information goes into this file.

Python never writes the Excel workbook itself. The workbook pulls this CSV in
with Power Query (Data > Refresh All), so formulas, PivotTables and formatting
built by hand are never overwritten.

Usage: python3 src/export_tracker.py      (run_batch.sh calls it after every batch)
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "data" / "batches" / "batch_index.csv"
OUT = REPO / "exports" / "batches.csv"

COLUMNS = [
    "batch_id", "status", "messages", "parse_failures",
    "emails_redacted", "people_redacted", "phones_redacted",
    "escalations_total", "escalations_person", "escalations_ssn", "escalations_card",
    "leak_hits", "leak_email", "leak_phone", "leak_notes", "leak_known_name", "leak_mailbox",
    "mailbox_lines_removed", "started", "finished", "runtime_s", "used_spacy",
]


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def row_for(batch_id: str, manifest_count: int) -> dict:
    out_dir = REPO / "output" / batch_id
    stats, leaks = _load(out_dir / "stats.json"), _load(out_dir / "leaks.json")
    status_file = out_dir / "STATUS"
    status = status_file.read_text().strip() if status_file.exists() else ("redacted" if stats else "not_run")
    red, esc = stats.get("redacted", {}), stats.get("escalations", {})
    has_leaks = bool(leaks)
    return {
        "batch_id": batch_id,
        "status": status,
        "messages": stats.get("messages_redacted", manifest_count if not stats else 0),
        "parse_failures": stats.get("parse_failures", ""),
        "emails_redacted": red.get("email", 0) if stats else "",
        "people_redacted": red.get("person", 0) if stats else "",
        "phones_redacted": red.get("phone", 0) if stats else "",
        "escalations_total": stats.get("escalations_total", ""),
        "escalations_person": esc.get("person", 0) if stats else "",
        "escalations_ssn": esc.get("ssn_like", 0) if stats else "",
        "escalations_card": esc.get("card_like", 0) if stats else "",
        "leak_hits": leaks.get("total", "") if has_leaks else "",
        "leak_email": leaks.get("email", "") if has_leaks else "",
        "leak_phone": leaks.get("phone", "") if has_leaks else "",
        "leak_notes": leaks.get("notes_addr", "") if has_leaks else "",
        "leak_known_name": leaks.get("known_name", "") if has_leaks else "",
        "leak_mailbox": leaks.get("mailbox", "") if has_leaks else "",
        "mailbox_lines_removed": stats.get("removed_mailbox_lines", ""),
        "started": stats.get("started", ""),
        "finished": stats.get("finished", ""),
        "runtime_s": stats.get("runtime_s", ""),
        "used_spacy": {True: "yes", False: "no"}.get(stats.get("spacy"), ""),
    }


def main() -> None:
    with INDEX.open() as f:
        batches = [(r["batch_id"], int(r["file_count"])) for r in csv.DictReader(f)]
    rows = [row_for(b, n) for b, n in batches]

    # Write atomically: Excel may be reading the old file during a refresh.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, prefix=".batches-", suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, OUT)
    run = sum(1 for r in rows if r["status"] != "not_run")
    print(f"exported {len(rows)} batches ({run} run) to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
