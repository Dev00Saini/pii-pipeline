"""fingerprint.py: content fingerprint for every message, for deduplication.

Day 1 found that copies of the same email (filed in several folders) have
different Message-ID and X-Folder headers, so byte-level and Message-ID checks
miss them. A Date + From + Subject fingerprint found ~51% copies.

This script uses a STRICTER fingerprint: Date + From + To + Cc + Subject + body
(whitespace-normalized), and deliberately ignores the per-copy headers
(Message-ID, X-Folder, X-Origin, X-FileName). It also recomputes the Day 1
header-only fingerprint so the two can be compared.

Usage:  python3 src/fingerprint.py
Writes: data/fingerprints.tsv          strict_fp <TAB> header_fp <TAB> path
        data/fingerprint_failures.txt  files that could not be parsed. These are
                                       NOT batched, so they must be reviewed by
                                       hand: a file that silently drops out of a
                                       PII pipeline is never checked for PII.
        (data/ is gitignored)
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse import ParseError, parse_file  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
MAILDIR = REPO_DIR / "data" / "maildir"
OUT = REPO_DIR / "data" / "fingerprints.tsv"
FAILED_OUT = REPO_DIR / "data" / "fingerprint_failures.txt"


def _norm(text: str) -> str:
    """Collapse whitespace so trivial spacing differences don't split copies."""
    return " ".join(text.split())


def fingerprint(rel_path: str) -> tuple[str, str, str] | tuple[None, None, str]:
    try:
        m = parse_file(REPO_DIR / rel_path)
    except ParseError:
        return None, None, rel_path
    h = m.headers
    header_key = "|".join(h.get(k, "") for k in ("date", "from", "subject"))
    strict_key = "|".join(
        [_norm(h.get(k, "")) for k in ("date", "from", "to", "cc", "subject")]
        + [_norm(m.body)]
    )
    sha = lambda s: hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()
    return sha(strict_key), sha(header_key), rel_path


def main() -> None:
    if not MAILDIR.is_dir():
        sys.exit("data/maildir not found; run bin/setup.sh first")

    paths = sorted(
        str(Path(root, f).relative_to(REPO_DIR))
        for root, _, files in os.walk(MAILDIR) for f in files
    )
    print(f"fingerprinting {len(paths)} files using {os.cpu_count()} processes...")

    strict, header, failed = Counter(), Counter(), []
    with ProcessPoolExecutor() as pool, OUT.open("w") as out:
        for s, hk, p in pool.map(fingerprint, paths, chunksize=500):
            if s is None:
                failed.append(p)
                continue
            out.write(f"{s}\t{hk}\t{p}\n")
            strict[s] += 1
            header[hk] += 1

    FAILED_OUT.write_text("".join(f"{p}\n" for p in failed))

    total = sum(strict.values())
    print(f"files fingerprinted:            {total}")
    print(f"files that failed to parse:     {len(failed)}")
    print(f"unique by header fingerprint:   {len(header)}  (Day 1 method)")
    print(f"unique by strict fingerprint:   {len(strict)}  (adds To, Cc, body)")
    print(f"extra copies (strict):          {total - len(strict)}")
    print(f"written to {OUT.relative_to(REPO_DIR)}")
    if failed:
        print(f"REVIEW NEEDED: {len(failed)} unparseable files listed in "
              f"{FAILED_OUT.relative_to(REPO_DIR)} (not included in batches)")


if __name__ == "__main__":
    main()
