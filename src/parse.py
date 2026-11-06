"""parse.py: read one Enron message file into headers + body.

The corpus has two quirks this handles:
  * mixed line endings (CRLF and LF in the same file), normalized to LF
  * occasional bad bytes / odd charsets, decoded with errors="replace"

Use as a module:   from parse import parse_file
Use from the shell: python3 src/parse.py data/batches/batch_000.txt
  -> parses every file listed in a batch manifest, prints parsed/failed
     counts, and logs failures to logs/parse_errors.log
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from email.parser import BytesParser
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
ERROR_LOG = REPO_DIR / "logs" / "parse_errors.log"

# Headers the rest of the pipeline cares about (all lower-case keys).
KEEP_HEADERS = (
    "message-id", "date", "from", "to", "cc", "bcc", "subject",
    "x-from", "x-to", "x-cc", "x-bcc", "x-folder", "x-origin", "x-filename",
)


class ParseError(Exception):
    """Raised when a file can't be read as an email at all."""


@dataclass
class ParsedMessage:
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""


def _decode(payload: bytes, charset: str | None) -> str:
    """Decode bytes with the declared charset, falling back safely."""
    for enc in (charset, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            return payload.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def parse_file(path: str | Path) -> ParsedMessage:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ParseError(f"cannot read file: {e}") from e

    if not raw.strip():
        raise ParseError("empty file")
    if b"\x00" in raw[:1024]:
        raise ParseError("binary data (NUL bytes) in file")

    # Normalize mixed CRLF / LF line endings before parsing.
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    msg = BytesParser().parsebytes(raw)
    if not msg.keys():
        raise ParseError("no headers found")

    headers = {}
    for name in KEEP_HEADERS:
        value = msg.get(name)
        if value is not None:
            # Folded (multi-line) headers -> one line, whitespace collapsed.
            headers[name] = " ".join(str(value).split())

    # The corpus is plain text with attachments removed, but handle
    # multipart defensively by joining the text/plain parts.
    parts = msg.walk() if msg.is_multipart() else [msg]
    chunks = []
    for part in parts:
        if part.is_multipart() or part.get_content_type() not in ("text/plain", "text"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = str(part.get_payload()).encode("utf-8", errors="replace")
        chunks.append(_decode(payload, part.get_content_charset()))
    body = "\n".join(chunks)

    return ParsedMessage(path=str(path), headers=headers, body=body)


def parse_manifest(manifest: Path) -> tuple[int, int]:
    """Parse every path in a manifest file; return (parsed, failed)."""
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    parsed = failed = 0
    with manifest.open() as paths, ERROR_LOG.open("a") as log:
        for line in paths:
            p = line.rstrip("\n")
            if not p:
                continue
            try:
                parse_file(REPO_DIR / p if not Path(p).is_absolute() else p)
                parsed += 1
            except ParseError as e:
                failed += 1
                log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{manifest.name}\t{p}\t{e}\n")
    return parsed, failed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 src/parse.py <batch manifest>")
    ok, bad = parse_manifest(Path(sys.argv[1]))
    print(f"parsed: {ok}  failed: {bad}  (failures logged to {ERROR_LOG.relative_to(REPO_DIR)})")
    sys.exit(1 if ok == 0 else 0)
