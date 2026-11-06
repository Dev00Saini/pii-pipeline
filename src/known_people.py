"""known_people.py: build a list of real people's names from the X- headers.

X-From / X-To / X-cc / X-bcc hold display names ("Phillip K Allen",
"Meg St. John" <...>, "John Arnold/HOU/ECT@ECT"). Collecting them across the
corpus gives a list of known names that can be matched in message BODIES,
catching names the statistical model (spaCy) misses.

Usage:  python3 src/known_people.py
Reads:  data/unique_paths.txt  (from bin/make_batches.sh)
Writes: data/known_people.tsv  name <TAB> count   (real names: data/ is gitignored)
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse import ParseError, parse_file  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
PATHS = REPO_DIR / "data" / "unique_paths.txt"
OUT = REPO_DIR / "data" / "known_people.tsv"

PARTICLES = {"de", "del", "della", "da", "di", "du", "van", "von", "der", "den", "la", "le"}
# Words that mark a header entry as an organization/list, not a person.
NOT_PERSON = {
    "inc", "corp", "corporation", "llc", "ltd", "co", "company", "group", "team",
    "dept", "department", "enron", "energy", "services", "associates", "committee",
    "mailbox", "announcements", "desk", "staff", "all", "employees", "office",
    "news", "newsletter", "admin", "administrator", "support", "help", "info",
    "the", "and", "of", "for", "on", "behalf", "undisclosed", "recipients", "list",
    # Round 5 (batch_000 review): newsletters/publications appear as senders,
    # e.g. "Gas Daily".
    "daily", "weekly", "monthly", "report", "digest", "alert", "alerts", "journal",
    "times", "post", "online", "update", "updates", "bulletin", "gas", "power",
}
TOKEN_RE = re.compile(r"[A-Z][A-Za-z'-]*\.?|[A-Z]\.")


def _valid_token(tok: str) -> bool:
    if tok.casefold() in PARTICLES:
        return True
    if not TOKEN_RE.fullmatch(tok):
        return False
    letters = tok.strip(".'-")
    return not (len(letters) > 1 and letters.isupper())  # skip ALL-CAPS words


def names_from_header(value: str) -> list[str]:
    """Extract plausible person names from one X- header value."""
    v = re.sub(r"<[^>]*>", " ", value)            # <address> parts
    v = re.sub(r"\([^)]*\)", " ", v)              # (comments)
    v = v.replace('"', " ")
    found = []
    for part in re.split(r"[;,]", v):
        # Notes suffix first ("Arnold/HOU/ECT@ECT" would otherwise look like an
        # email address and take the last name with it), then bare addresses.
        part = re.sub(r"/[A-Za-z0-9&/-]+(?:@\S+)?", " ", part)  # Notes /HOU/ECT@ECT
        part = re.sub(r"\S+@\S+", " ", part)      # bare email addresses
        tokens = part.split()
        if not 2 <= len(tokens) <= 5:
            continue
        if any(t.strip(".").casefold() in NOT_PERSON for t in tokens):
            continue
        if not all(_valid_token(t) for t in tokens):
            continue
        if tokens[0].casefold() in PARTICLES or tokens[-1].casefold() in PARTICLES:
            continue
        name = " ".join(tokens)
        found.append(name)
        # Variant without middle initials: "Phillip K Allen" -> "Phillip Allen"
        core = [t for t in tokens if len(t.strip(".")) > 1]
        if 2 <= len(core) < len(tokens):
            found.append(" ".join(core))
    return found


def _names_in_file(rel: str) -> list[str]:
    try:
        h = parse_file(REPO_DIR / rel).headers
    except ParseError:
        return []
    out = []
    for k in ("x-from", "x-to", "x-cc", "x-bcc"):
        if h.get(k):
            out.extend(names_from_header(h[k]))
    return out


def main() -> None:
    if not PATHS.exists():
        sys.exit("missing data/unique_paths.txt; run bin/make_batches.sh first")
    paths = [p for p in PATHS.read_text().split("\n") if p]
    print(f"reading X- headers from {len(paths)} unique messages with {os.cpu_count()} processes...")
    counts: Counter[str] = Counter()
    with ProcessPoolExecutor() as pool:
        for names in pool.map(_names_in_file, paths, chunksize=500):
            counts.update(names)
    with OUT.open("w") as f:
        for name, n in counts.most_common():
            f.write(f"{name}\t{n}\n")
    print(f"distinct names: {len(counts)}")
    print(f"seen 2+ times:  {sum(1 for n in counts.values() if n >= 2)}")
    print(f"written to {OUT.relative_to(REPO_DIR)}  (real names: stays local)")


if __name__ == "__main__":
    main()
