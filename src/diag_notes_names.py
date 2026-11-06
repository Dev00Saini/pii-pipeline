"""diag_notes_names.py: how many Notes names in a batch are a single word?

A single-word name usually means the detector cut it short (e.g. a first name
lost to line wrapping). Run before and after a detector change to measure it.

Usage:  python3 src/diag_notes_names.py data/batches/batch_000.txt [--show N]
        --show N prints the 40 characters before N examples (contains real
        data: read it on screen, don't paste it anywhere)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect import detect  # noqa: E402
from parse import ParseError, parse_file  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) not in (2, 4):
        sys.exit(__doc__)
    show = int(sys.argv[3]) if len(sys.argv) == 4 else 0
    total = single = shown = 0
    for rel in Path(sys.argv[1]).read_text().split("\n"):
        if not rel:
            continue
        try:
            body = parse_file(REPO / rel).body
        except ParseError:
            continue
        for m in detect(body):
            if m.type != "notes_addr":
                continue
            total += 1
            if " " not in m.value:
                single += 1
                if shown < show:
                    print(repr(body[max(0, m.start - 40):m.end]))
                    shown += 1
    pct = 100 * single / total if total else 0
    print(f"notes names in body: {total}   single-word: {single} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
