"""redact.py: write a redacted copy of every message in one batch.

    python3 src/redact.py 007            # or batch_007
    python3 src/redact.py 007 --no-spacy # patterns + known-people list only (fast test run)

For each message:
  * headers that name people (From, To, Cc, Bcc, X-From, X-To, X-cc, X-bcc,
    Subject) and the body are scanned; "redact" matches are replaced with
    consistent placeholders ([PERSON_00014], [EMAIL_00203], [PHONE_00057])
  * "escalate" matches (ssn_like, card_like, ambiguous single-word names) are
    LEFT IN PLACE and logged to escalations.tsv for human review; a batch
    with escalations is not released until they're reviewed
  * X-Folder, X-Origin and X-FileName are DROPPED: they contain mailbox
    owners' names (e.g. "\\Jeff_Dasovich_Dec2000\\...", "jdasovic.nsf")

Outputs (written to output/batch_NNN.tmp/, renamed to output/batch_NNN/ only
when complete, so a crash never leaves a half-written batch looking finished):
  output/batch_NNN/messages/<user>/<folder>/<file>   redacted messages
  output/batch_NNN/stats.json                        counts, runtime
  output/batch_NNN/escalations.tsv                   items for human review
The placeholder map (secrets/placeholder_map.json) is saved only after the
batch output is complete.

Exit codes: 0 ok, 2 usage / missing manifest, 1 unexpected error.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import re  # noqa: E402

from detect import Match, _resolve_overlaps  # noqa: E402
from known_people import names_from_header  # noqa: E402
from names import SPACY_MAX_CHARS, NameDetector  # noqa: E402
from parse import ParseError, ParsedMessage, parse_file  # noqa: E402
from placeholders import KIND_OF, PlaceholderMap  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
MAILDIR_PREFIX = "data/maildir/"

# Output header order. Headers not listed (X-Folder, X-Origin, X-FileName) are dropped.
OUT_HEADERS = ["message-id", "date", "from", "to", "cc", "bcc", "subject",
               "x-from", "x-to", "x-cc", "x-bcc"]
SCAN_HEADERS = {"from", "to", "cc", "bcc", "subject", "x-from", "x-to", "x-cc", "x-bcc"}
HEADER_NAMES = {"message-id": "Message-ID", "date": "Date", "from": "From", "to": "To",
                "cc": "Cc", "bcc": "Bcc", "subject": "Subject", "x-from": "X-From",
                "x-to": "X-To", "x-cc": "X-cc", "x-bcc": "X-bcc"}
CONTEXT = 40  # characters of context saved around each escalation


def redact_text(text: str, matches: list[Match], pmap: PlaceholderMap,
                counts: Counter, escalations: list, where: dict) -> str:
    """Replace 'redact' matches with placeholders; log 'escalate' matches."""
    out, pos = [], 0
    for m in sorted(matches, key=lambda m: m.start):
        if m.action == "escalate":
            counts[f"escalate_{m.type}"] += 1
            ctx = " ".join(text[max(0, m.start - CONTEXT):m.end + CONTEXT].split())
            escalations.append({**where, "type": m.type, "text": " ".join(m.text.split()), "context": ctx})
            continue
        if m.type not in KIND_OF:
            continue
        out.append(text[pos:m.start])
        out.append(pmap.get(m.type, m.value or m.text))
        counts[f"redacted_{KIND_OF[m.type]}"] += 1
        pos = m.end
    out.append(text[pos:])
    return "".join(out)


def redact_message(msg: ParsedMessage, det: NameDetector, pmap: PlaceholderMap,
                   counts: Counter, escalations: list, rel: str, doc=None) -> str:
    lines = []
    for key in OUT_HEADERS:
        value = msg.headers.get(key)
        if value is None:
            continue
        if key in SCAN_HEADERS:
            # Headers: patterns + known-people list (no spaCy needed: the list
            # was built from these very headers).
            ms = _no_spacy(det, value)
            if key.startswith("x-"):
                # Names in X- headers are matched directly, not only via the
                # known list (a spelling might be missing from it).
                ms = _resolve_overlaps(ms + header_name_matches(value))
            value = redact_text(value, ms, pmap, counts, escalations, {"file": rel, "field": key})
        lines.append(f"{HEADER_NAMES[key]}: {value}")
    body_matches = det.detect_all(msg.body, doc=doc)
    body = redact_text(msg.body, body_matches, pmap, counts, escalations, {"file": rel, "field": "body"})
    return "\n".join(lines) + "\n\n" + body


def header_name_matches(value: str) -> list[Match]:
    out = []
    for name in sorted(set(names_from_header(value)), key=len, reverse=True):
        for mm in re.finditer(re.escape(name), value):
            out.append(Match("person", name, mm.start(), mm.end(), "redact", name))
    return out


def _no_spacy(det: NameDetector, text: str) -> list[Match]:
    """detect_all without spaCy, for short header values."""
    was = det.use_spacy
    det.use_spacy = False
    try:
        return det.detect_all(text)
    finally:
        det.use_spacy = was


def batch_id(arg: str) -> str:
    digits = arg.removeprefix("batch_")
    if not digits.isdigit():
        raise ValueError(f"not a batch id: {arg!r}")
    return f"batch_{int(digits):03d}"


def run(bid: str, use_spacy: bool = True) -> dict:
    manifest = REPO_DIR / "data" / "batches" / f"{bid}.txt"
    final_dir = REPO_DIR / "output" / bid
    tmp_dir = REPO_DIR / "output" / f"{bid}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)          # leftovers from an interrupted run
    (tmp_dir / "messages").mkdir(parents=True)

    started = time.time()
    det = NameDetector.from_file(use_spacy=use_spacy)
    pmap = PlaceholderMap()
    counts: Counter = Counter()
    escalations: list[dict] = []
    failures: list[str] = []

    rels, msgs = [], []
    for rel in manifest.read_text().split("\n"):
        if not rel:
            continue
        try:
            msgs.append(parse_file(REPO_DIR / rel))
            rels.append(rel)
        except ParseError as e:
            failures.append(f"{rel}\t{e}")

    docs = (det.nlp.pipe((m.body[:SPACY_MAX_CHARS] for m in msgs), batch_size=64)
            if use_spacy else (None for _ in msgs))
    for rel, msg, doc in zip(rels, msgs, docs):
        text = redact_message(msg, det, pmap, counts, escalations, rel, doc)
        dest = tmp_dir / "messages" / rel.removeprefix(MAILDIR_PREFIX)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    with (tmp_dir / "escalations.tsv").open("w") as f:
        f.write("item_id\tbatch\tfile\tfield\ttype\ttext\tcontext\n")
        for i, e in enumerate(escalations, 1):
            row = [f"{bid}-{i:05d}", bid, e["file"], e["field"], e["type"], e["text"], e["context"]]
            f.write("\t".join(c.replace("\t", " ") for c in row) + "\n")
    if failures:
        (tmp_dir / "parse_failures.txt").write_text("\n".join(failures) + "\n")

    stats = {
        "batch": bid,
        "messages_in_manifest": len(rels) + len(failures),
        "messages_redacted": len(rels),
        "parse_failures": len(failures),
        "redacted": {k.removeprefix("redacted_"): v for k, v in sorted(counts.items()) if k.startswith("redacted_")},
        "escalations": {k.removeprefix("escalate_"): v for k, v in sorted(counts.items()) if k.startswith("escalate_")},
        "escalations_total": len(escalations),
        "spacy": use_spacy,
        "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "runtime_s": round(time.time() - started, 1),
    }
    (tmp_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")

    # Publish: replace any previous output for this batch, then save the map.
    if final_dir.exists():
        shutil.rmtree(final_dir)
    tmp_dir.rename(final_dir)
    pmap.save()
    return stats


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--no-spacy"]
    if len(args) != 1:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        bid = batch_id(args[0])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if not (REPO_DIR / "data" / "batches" / f"{bid}.txt").exists():
        print(f"no manifest for {bid}", file=sys.stderr)
        return 2
    stats = run(bid, use_spacy="--no-spacy" not in sys.argv)
    print(json.dumps({k: stats[k] for k in ("batch", "messages_redacted", "parse_failures",
                                             "redacted", "escalations_total", "runtime_s")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
