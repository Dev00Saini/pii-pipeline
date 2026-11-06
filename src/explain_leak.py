"""explain_leak.py: why did the redactor miss this leak?

For each leak-check hit, re-runs the detectors on the ORIGINAL message and
reports which detectors matched at that spot (or that none did).

Output is MASKED so it can be shared: letters/digits become * except the first
character of the leak, punctuation and spacing are kept. Context shows the
shape around the leak, e.g.  "***.7**-***-****"  reveals a "." right before
a phone number.

Usage:  python3 src/explain_leak.py 000 phone 10     (batch, check, how many)
        python3 src/explain_leak.py 000 known_name 10 --no-spacy
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from names import SPACY_MAX_CHARS, NameDetector  # noqa: E402
from parse import parse_file  # noqa: E402
from redact import SCAN_HEADERS, _no_spacy, _resolve_overlaps, batch_id, header_name_matches  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def mask(s: str, keep_first: bool = False) -> str:
    out = re.sub(r"[A-Za-z0-9]", "*", s)
    if keep_first and s:
        out = s[0] + out[1:]
    return out.replace("\n", "⏎").replace("\t", "⇥")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--no-spacy"]
    if len(args) != 3:
        sys.exit(__doc__)
    bid, check, limit = batch_id(args[0]), args[1], int(args[2])
    det = NameDetector.from_file(use_spacy="--no-spacy" not in sys.argv)
    report = REPO / "output" / bid / "leak_report.tsv"
    seen, shown = set(), 0
    for line in report.read_text().split("\n")[1:]:
        if shown >= limit:
            break
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] != check or (parts[1], parts[2]) in seen:
            continue
        seen.add((parts[1], parts[2]))
        rel, leak = parts[1], parts[2]
        msg = parse_file(REPO / "data" / "maildir" / rel)
        fields = {k: v for k, v in msg.headers.items() if k in SCAN_HEADERS}
        fields["body"] = msg.body
        field = next((k for k, v in fields.items() if leak in v), None)
        shown += 1
        print(f"--- #{shown} {check} in {rel}  leak: {mask(leak, keep_first=True)}")
        if field is None:
            print("    leak text not found verbatim in the original (spans a line break, or")
            print("    was created by redaction, e.g. leftover pieces around a placeholder)")
            continue
        text = fields[field]
        i = text.index(leak)
        print(f"    field: {field}   context: {mask(text[max(0, i - 15):i])}[{mask(leak, True)}]{mask(text[i + len(leak):i + len(leak) + 15])}")
        if field == "body":
            doc = det.nlp(text[:SPACY_MAX_CHARS]) if det.use_spacy else None
            ms = det.detect_all(text, doc)
            raw = det._known_matches(text) + (det._spacy_matches(doc) if doc is not None else [])
        else:
            ms = _no_spacy(det, text)
            if field.startswith("x-"):
                ms = _resolve_overlaps(ms + header_name_matches(text))
            raw = []
        j = i + len(leak)
        kept = [m for m in ms if m.start < j and m.end > i]
        dropped = [m for m in raw if m.start < j and m.end > i and m not in kept]
        if not kept:
            print("    NO detector match kept at this spot")
        for m in kept:
            cover = "covers all" if m.start <= i and m.end >= j else "covers part"
            print(f"    kept:    {m.type}/{m.action} ({cover}): {mask(m.text, True)}")
        for m in dropped:
            print(f"    dropped by overlap rule: {m.type}/{m.action}: {mask(m.text, True)}")


if __name__ == "__main__":
    main()
