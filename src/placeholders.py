"""placeholders.py: give the same real value the same placeholder everywhere.

    "Phillip K Allen", "Phillip K. Allen", "PHILLIP ALLEN", "Phillip Allen/HOU/ECT"
        -> all [PERSON_00014]
    "John.Smith@enron.com", "john.smith@enron.com"  -> same [EMAIL_00203]
    "(713) 853-1234", "713.853.1234", "1-713-853-1234" -> same [PHONE_00057]

The map is the KEY that undoes the redaction, so it lives in secrets/
(gitignored) and is written atomically with owner-only permissions.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_DIR / "secrets" / "placeholder_map.json"

# Detector match type -> placeholder kind
KIND_OF = {"person": "person", "notes_addr": "person", "email": "email", "phone": "phone"}
PREFIX = {"person": "PERSON", "email": "EMAIL", "phone": "PHONE"}


def normalize_key(kind: str, value: str) -> str:
    """Reduce different spellings of the same value to one lookup key."""
    if kind == "person":
        tokens = [t.strip(".,'\"").casefold() for t in value.split()]
        tokens = [t for t in tokens if t]
        # Drop middle initials so "Phillip K Allen" == "Phillip Allen",
        # but keep a lone initial if it's all there is.
        no_initials = [t for t in tokens if len(t) > 1]
        return " ".join(no_initials or tokens)
    if kind == "email":
        return value.strip().lstrip(".'").casefold()   # 'a@b.com' == a@b.com
    if kind == "phone":
        number = re.split(r"(?i)\s*(?:x|ext\.?|extension)\s*\d", value)[0]  # drop extension
        digits = re.sub(r"\D", "", number)
        if len(digits) > 10 and not value.lstrip().startswith(("+", "00")):
            digits = digits[-10:]  # drop a US/short country-code prefix
        return digits
    raise ValueError(f"unknown kind: {kind}")


class PlaceholderMap:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text())
        else:
            data = {"counters": {}, "map": {}}
        self.counters: dict[str, int] = data["counters"]
        self.map: dict[str, dict[str, str]] = data["map"]

    def get(self, match_type: str, value: str) -> str:
        kind = KIND_OF[match_type]
        key = normalize_key(kind, value)
        table = self.map.setdefault(kind, {})
        if key not in table:
            n = self.counters.get(kind, 0) + 1
            self.counters[kind] = n
            table[key] = f"[{PREFIX[kind]}_{n:05d}]"
        return table[key]

    def save(self) -> None:
        """Write to a temp file, then rename: a crash mid-write can't corrupt the map."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".map-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"counters": self.counters, "map": self.map}, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
