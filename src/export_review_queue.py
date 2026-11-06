"""export_review_queue.py: build the human review queue from all batches.

Writes (to exports/, which is gitignored; these files contain REAL personal
data, so they stay inside Ubuntu and are never copied to OneDrive or GitHub):
  exports/review_queue.csv   every escalated item, all batches
  exports/review_sample.csv  a fixed random sample to review by hand (seed 42):
                             every SSN-/card-shaped item (up to 40) plus random
                             ambiguous-name items, spread across batches

item_id is a fingerprint of (file, field, type, text, context), so the same
item keeps the same ID after a batch is re-run. Decisions recorded against an
item_id in Excel therefore stay attached to the right item.

Usage: python3 src/export_review_queue.py [sample_size, default 150]
"""
from __future__ import annotations

import csv
import hashlib
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "exports"
REASON = {
    "person": "ambiguous name at sentence start",
    "ssn_like": "SSN-shaped number",
    "card_like": "card-number-shaped (passes checksum)",
}
COLUMNS = ["item_id", "batch", "type", "reason", "text", "context", "file", "field"]


def load_items() -> list[dict]:
    items = []
    for tsv in sorted((REPO / "output").glob("batch_[0-9]*/escalations.tsv")):
        with tsv.open(newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                key = "|".join(r[k] for k in ("file", "field", "type", "text", "context"))
                items.append({
                    "item_id": hashlib.sha1(key.encode()).hexdigest()[:10],
                    "batch": r["batch"], "type": r["type"],
                    "reason": REASON.get(r["type"], r["type"]),
                    "text": r["text"], "context": r["context"],
                    "file": r["file"], "field": r["field"],
                })
    # The same item can appear twice (e.g. a word repeated in one context): keep one.
    seen, unique = set(), []
    for it in items:
        if it["item_id"] not in seen:
            seen.add(it["item_id"])
            unique.append(it)
    return unique


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel reads accents correctly
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    items = load_items()
    OUT_DIR.mkdir(exist_ok=True)
    write(OUT_DIR / "review_queue.csv", items)

    rng = random.Random(42)
    numbers = [it for it in items if it["type"] != "person"]
    names = [it for it in items if it["type"] == "person"]
    sample = rng.sample(numbers, min(40, len(numbers)))
    sample += rng.sample(names, min(size - len(sample), len(names)))
    sample.sort(key=lambda it: (it["batch"], it["item_id"]))
    write(OUT_DIR / "review_sample.csv", sample)

    by_type = Counter(it["type"] for it in items)
    print(f"review queue: {len(items)} unique items  {dict(by_type)}")
    print(f"review sample: {len(sample)} items ({sum(1 for s in sample if s['type'] != 'person')} numbers, "
          f"{sum(1 for s in sample if s['type'] == 'person')} names) from "
          f"{len({s['batch'] for s in sample})} batches")
    words = Counter(it["text"].strip(".,'").title() for it in names)
    print("most common escalated words:", ", ".join(f"{w} {n}" for w, n in words.most_common(12)))
    print("files: exports/review_queue.csv, exports/review_sample.csv (real data: keep inside Ubuntu)")


if __name__ == "__main__":
    main()
