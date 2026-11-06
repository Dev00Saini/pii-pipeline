"""detect.py: pattern-based detectors for personal information.

Each detector returns Match objects: (type, text, start, end, action, value).
  action = "redact"   -> replaced automatically later (Day 5)
  action = "escalate" -> sent to the human review queue, never auto-redacted
  value  = the part that identifies the person (used for consistent
           placeholders on Day 4); for a Notes address it's just the name

Types:
  email        standard addresses, any domain (not just @enron.com)
  notes_addr   Lotus Notes style: "First M Last/HOU/ECT@ECT", "First Last/HOU/ECT"
  phone        US numbers: (713) 853-1234, 713-853-1234, 713.853.1234,
               +1 713 853 1234, with optional extension; international numbers
               starting with + or 00; 7-digit local numbers
               only when labeled ("Phone: 853-1234")
  ssn_like     ###-##-#### in valid SSN ranges            -> escalate
  card_like    13-16 digits, card-shaped (starts 3-6, standard grouping),
               passing the Luhn checksum                  -> escalate

Usage from the shell (counts per type for one batch; samples go to data/):
  python3 src/detect.py data/batches/batch_000.txt
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Match:
    type: str
    text: str
    start: int
    end: int
    action: str = "redact"
    value: str = ""


# --- Email ---------------------------------------------------------------
# Local part allows . _ % + ' - ; domain must end in a 2+ letter TLD.
# The domain can't end in a dot, so "a@b.com." at a sentence end stops at .com
# Leak-check round 1: the local part may START with quotes or dots, as in
# Outlook's 'jana.morse@dynegy.com' and corpus oddities like .ward@enron.com.
# (The old pattern refused to start after ' or ., so those leaked entirely.)
# Round 2: also a leading "+" (second half of a long encoded address wrapped
# onto a new line).
EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"[.'+]*[A-Za-z0-9][A-Za-z0-9._%+'-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    r"(?![\w-])"
)

# --- Lotus Notes addresses -------------------------------------------------
# Name: 1-4 capitalized words or initials ("Vince J Kaminski", "Mary-Ann O'Neil").
# Words are separated by a space, or by "space + line break": Lotus Notes wraps
# long recipient lists mid-name, leaving "Scott \nMills/HOU/ECT@ECT" (batch_000
# review: 1,226 of 6,613 body names were cut to just the last name). A line
# break WITHOUT the trailing space is not joined, so "Thanks\nJohn Arnold/..."
# doesn't absorb "Thanks".
# Then either 2-3 "/ORG" segments with optional "@DOMAIN" (Name/HOU/ECT@ECT,
# Name/HOU/ECT), or one segment plus "@DOMAIN" (Name/Enron@EnronXGate).
# Round 4 (batch_000 review): lowercase particles ("Peter del Vecchio") and a
# wrap right after an initial with indentation ("Monica L.\n     Brown/...").
# A line ending in a lone capital + period is clearly mid-name, so that's safe.
_TOK = r"[A-Z][A-Za-z'.-]*"
_PART = r"(?:de|del|della|da|di|du|van|von|der|den|la|le|st\.)"
_SEP = r"(?: | \n|(?<=\b[A-Z]\.)\n[ \t]*)"
_NAME = rf"{_TOK}(?:{_SEP}(?:{_PART} ){{0,2}}{_TOK}){{0,3}}"
_SEG = r"[A-Za-z0-9&-]{2,}"
# Leak-check round 2: up to 5 org parts (Name/ROL/NOR/US/Reuters@Moneynet) and
# an optional second domain (Name/Corp/Enron@Enron@ENRON).
NOTES_RE = re.compile(
    rf"(?<![\w/])(?P<name>{_NAME})"
    rf"(?:(?:/{_SEG}){{2,5}}(?:@{_SEG}){{0,2}}|/{_SEG}(?:@{_SEG}){{1,2}})"
    r"(?![\w/@])"
)

# --- Phone numbers ---------------------------------------------------------
_EXT = r"(?:\s*(?:x|ext\.?|extension)\s*\d{1,5})?"
PHONE_RE = re.compile(
    # Leak-check round 2: a WORD may touch the number ("Office713-345-3251" in
    # signature tables), so only digits, ".", "$", "/", "_", "-" block it; and
    # a short country code may precede it ("44.207.783.4040").
    r"(?<![\d$/_-])(?<!\d\.)"         # not glued to digits, $, dates, decimals ("Tel.713" is OK)
    r"(?:\+?\d{1,3}[\s.-])?"          # optional country code
    r"(?:\(\d{3}\)\s?|\d{3}[\s.-])"  # area code: (713) or 713- / 713. / 713␠
    r"\d{3}[\s.-]\d{4}"
    + _EXT +
    r"(?![\w-]|\.\d)"
)
# International: "+44 20 7783 6777" or "0044 207 78 36777" (+ or 00, then a
# 1-3 digit country code, then 7-12 more digits in groups).
INTL_PHONE_RE = re.compile(
    r"(?<![\w.$/+-])(?:\+|00)[1-9]\d{0,2}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?![\w-]|\.\d)"
)
# 7-digit local numbers are too ambiguous alone (prices, IDs), so only when labeled.
LABELED_LOCAL_RE = re.compile(
    r"(?i)\b(?:phone|ph|tel|telephone|fax|cell|mobile|office|pager|direct)\b"
    r"[\s.:#-]*(?P<num>(?<!\d)\d{3}[\s.-]\d{4}" + _EXT + r")(?![\w-]|\.\d)"
)

# --- Escalate-only patterns -------------------------------------------------
SSN_RE = re.compile(r"(?<![\w-])(\d{3})-(\d{2})-(\d{4})(?![\w-])")
CARD_RE = re.compile(r"(?<![\w-])(?:\d[ -]?){12,15}\d(?![\w-])")
# Real card numbers start with 3-6 and are written either as one run of digits
# or in the standard groupings (4-4-4-4, 4-6-5 for Amex). This rules out
# zero-padded IDs ("000000000077131") and runs of dates ("30 2001 2000 2001").
CARD_GROUPINGS = {(16,), (15,), (14,), (13,), (4, 4, 4, 4), (4, 6, 5), (4, 4, 4, 1), (4, 4, 4, 2), (4, 4, 4, 3)}


def _valid_ssn(area: str, group: str, serial: str) -> bool:
    return not (area in ("000", "666") or area.startswith("9")
                or group == "00" or serial == "0000")


def _luhn_ok(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        double = not double
    return total % 10 == 0


def detect(text: str) -> list[Match]:
    found: list[Match] = []

    for m in EMAIL_RE.finditer(text):
        found.append(Match("email", m.group(), m.start(), m.end(), "redact", m.group().lower()))

    for m in NOTES_RE.finditer(text):
        # Normalize "Scott \nMills" -> "Scott Mills" so placeholders stay consistent.
        name = " ".join(m.group("name").split())
        # Round 3 (batch_000 review): reject look-alikes such as a form's
        # "MM/DD/YY" or a slash list "Rate/Term/Downpayment".
        #  - a real name has lowercase letters ("MM" doesn't)
        #  - without "@DOMAIN", org parts must be ALL CAPS (/HOU/ECT); mixed-case
        #    parts (/Corp/Enron) only occur in real addresses with "@Enron"
        orgs = m.group()[len(m.group("name")):]
        # Leak-check round 1: an ALL-CAPS name is fine when "@DOMAIN" follows
        # ("JEFF SHIVELY/ENRON@Gateway"); without "@" it's usually a code.
        if not re.search(r"[a-z]", name) and "@" not in orgs:
            continue
        if "@" not in orgs and not all(seg.isupper() for seg in orgs.strip("/").split("/")):
            continue
        found.append(Match("notes_addr", m.group(), m.start(), m.end(), "redact", name))

    for m in PHONE_RE.finditer(text):
        found.append(Match("phone", m.group(), m.start(), m.end(), "redact",
                           re.sub(r"\D", "", m.group())))
    for m in INTL_PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        is_00 = m.group().startswith("00")
        # An unseparated "00..." run is far more likely an ID than a phone.
        if is_00 and not re.search(r"[\s.()-]", m.group()):
            continue
        if 10 <= len(digits) - (2 if is_00 else 0) <= 15:
            found.append(Match("phone", m.group(), m.start(), m.end(), "redact", digits))
    for m in LABELED_LOCAL_RE.finditer(text):
        s, e = m.span("num")
        found.append(Match("phone", m.group("num"), s, e, "redact", re.sub(r"\D", "", m.group("num"))))

    for m in SSN_RE.finditer(text):
        if _valid_ssn(*m.groups()):
            found.append(Match("ssn_like", m.group(), m.start(), m.end(), "escalate", m.group()))

    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        groups = tuple(len(g) for g in re.split(r"[ -]", m.group()))
        if (13 <= len(digits) <= 16 and digits[0] in "3456"
                and groups in CARD_GROUPINGS and _luhn_ok(digits)):
            found.append(Match("card_like", m.group(), m.start(), m.end(), "escalate", digits))

    return _resolve_overlaps(found)


def _resolve_overlaps(matches: list[Match]) -> list[Match]:
    """Where matches overlap, keep the LONGEST; escalations win only ties.

    Leak-check round 1: escalations used to win outright, so an ambiguous word
    inside a longer address ("Mark" in "Mark Torres/Corp/Enron@ENRON") was left
    in place for review and the whole address went unredacted.
    """
    ranked = sorted(matches, key=lambda m: (-(m.end - m.start), m.action != "escalate", m.start))
    kept: list[Match] = []
    for m in ranked:
        if all(m.end <= k.start or m.start >= k.end for k in kept):
            kept.append(m)
    return sorted(kept, key=lambda m: m.start)


# --- Shell entry point: summarize one batch ---------------------------------
def _summarize(manifest: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from parse import ParseError, parse_file

    repo = Path(__file__).resolve().parent.parent
    sample_path = repo / "data" / f"detect_samples_{manifest.stem}.tsv"
    counts, msgs_with = Counter(), Counter()
    n = 0
    with manifest.open() as paths, sample_path.open("w") as samples:
        for line in paths:
            rel = line.rstrip("\n")
            try:
                msg = parse_file(repo / rel)
            except ParseError:
                continue
            n += 1
            # Headers that hold people's names/addresses, plus the body.
            fields = {k: msg.headers.get(k, "") for k in
                      ("from", "to", "cc", "bcc", "x-from", "x-to", "x-cc", "x-bcc")}
            fields["body"] = msg.body
            seen_types = set()
            for field, text in fields.items():
                for m in detect(text):
                    counts[m.type] += 1
                    seen_types.add(m.type)
                    samples.write(f"{m.type}\t{field}\t{m.action}\t{m.text}\t{rel}\n")
            for t in seen_types:
                msgs_with[t] += 1

    print(f"messages scanned: {n}")
    print(f"{'type':<12}{'matches':>10}{'messages':>10}")
    for t in ("email", "notes_addr", "phone", "ssn_like", "card_like"):
        print(f"{t:<12}{counts[t]:>10}{msgs_with[t]:>10}")
    print(f"every match listed in {sample_path.relative_to(repo)} (stays local: data/ is gitignored)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 src/detect.py <batch manifest>")
    _summarize(Path(sys.argv[1]))
