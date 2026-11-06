"""names.py: find people's names in free text.

Two methods, combined:
  1. known-people list (data/known_people.tsv, built from X- headers): exact
     matches of 2-5 word names in the text, e.g. "Phillip Allen". High precision.
  2. spaCy's statistical model (en_core_web_sm), PERSON entities: catches names
     the list doesn't have ("talk to Sara", "Thanks, Jeff").

Rules for spaCy results:
  - looks like an org, code, or address (digits, @, /, ALL CAPS, org words) -> ignored
  - single word that is also a common English word ("Will", "May", "Bill")
    -> ESCALATE to human review, never auto-redacted
  - anything else -> redact

Usage from the shell (counts + timing for one batch; samples go to data/):
  python3 src/names.py data/batches/batch_000.txt
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect import Match, _resolve_overlaps, detect  # noqa: E402
from known_people import NOT_PERSON, PARTICLES  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
KNOWN_PATH = REPO_DIR / "data" / "known_people.tsv"
SPACY_MAX_CHARS = 100_000  # longer bodies are truncated for spaCy only (patterns still see everything)

# Single words that are both first names and ordinary English words.
AMBIGUOUS = {
    "will", "may", "bill", "grant", "mark", "rose", "jack", "frank", "gene", "price",
    "hope", "joy", "june", "april", "august", "faith", "summer", "dawn", "art", "rich",
    "chase", "drew", "lance", "pat", "sue", "don", "ray", "dean", "miles", "wade",
    "brook", "page", "sky", "rob", "al", "ed", "max", "guy", "chip", "sandy", "carol",
    "penny", "bob", "terry", "jean", "rod", "bud", "buck", "duke", "earl", "king",
    "young", "long", "white", "black", "brown", "green", "gray", "hall", "lane", "ward",
}

# Leak-check round 2: a name word can't END with "-" or "'" and can't run on
# through a dot, so "'Scott Josey'", "John Brindle- VP" and "Brad McKay.Xyz"
# still yield "Scott Josey", "John Brindle", "Brad McKay".
_TOK = r"[A-Z](?:[A-Za-z'-]*[A-Za-z])?\.?"
_PART = "(?:" + "|".join(sorted(PARTICLES)) + ")"
CAP_RUN_RE = re.compile(rf"{_TOK}(?:[ \t]+(?:{_PART}[ \t]+){{0,2}}{_TOK})+")


def name_key(text: str) -> str:
    return " ".join(t.strip(".-'").casefold() for t in text.split())


# Words spaCy mislabels as PERSON in email (round 5, batch_000 review).
NOT_A_NAME = {
    "subject", "portfolio", "formulas", "re", "fw", "fwd", "thanks", "thank you",
    "regards", "hello", "hi", "dear", "attached", "attachment", "please", "cc",
    "bcc", "sent", "forwarded", "original message", "importance", "fyi", "asap",
}


def _sentence_initial_with_more_text(before: str, after: str) -> bool:
    """True if the word starts a sentence AND more words follow on its line.

    That's where ordinary words get capitalized ("May I ask", "Will you").
    A word alone on its line ("Thanks,\nFrank") is a sign-off: a name.
    """
    line_before = before.rsplit("\n", 1)[-1]
    starts_sentence = (line_before.strip() == ""
                       or re.search(r"[.!?:]\s*$", line_before) is not None)
    more_text = re.match(r"[ \t]*[A-Za-z]", after.split("\n", 1)[0]) is not None
    return starts_sentence and more_text


def classify_spacy_person(text: str, before: str = "", after: str = "") -> str | None:
    """Return 'redact', 'escalate', or None (ignore) for a spaCy PERSON entity.

    before/after = the text around the entity, used to judge single words
    like "Frank" or "May" by context (round 5: the word-list-only rule sent
    ~600 real names per batch to review).
    """
    t = " ".join(text.split())
    if t.strip(".,'").casefold() in NOT_A_NAME:
        return None
    if len(t) < 2 or re.search(r"[\d@/\\_#]", t):
        return None
    tokens = t.split()
    letters = re.sub(r"[^A-Za-z]", "", t)
    if len(letters) > 1 and letters.isupper():
        return None                     # ALL CAPS: usually an acronym or org
    if any(tok.strip(".,'").casefold() in NOT_PERSON for tok in tokens):
        return None
    if not tokens[0][:1].isupper():
        return None
    if len(tokens) == 1 and t.strip(".,'").casefold() in AMBIGUOUS:
        return "escalate" if _sentence_initial_with_more_text(before, after) else "redact"
    return "redact"


# Header words spaCy sometimes glues onto a name from the next line, as in
# "John\nSubject:" or "Jennifer\nSent:" (round 6, batch_000 review).
HEADER_WORDS = {"subject", "sent", "to", "from", "cc", "bcc", "date", "re", "fw", "fwd"}


def trim_header_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink [start, end) so it doesn't end with header words like 'Subject'."""
    while True:
        span = text[start:end]
        m = re.search(r"(\s+)(\S+)\s*$", span)
        if not m or m.group(2).strip(":").casefold() not in HEADER_WORDS:
            break
        end = start + m.start(1)
    if text[start:end].strip(":").casefold() in HEADER_WORDS:
        return start, start  # the whole entity was a header word
    return start, end


class NameDetector:
    def __init__(self, known: set[str] | None = None, use_spacy: bool = True):
        self.known = {name_key(n) for n in (known or set())}
        self.use_spacy = use_spacy
        self._nlp = None

    @classmethod
    def from_file(cls, path: Path = KNOWN_PATH, min_count: int = 1, use_spacy: bool = True):
        known = set()
        if path.exists():
            for line in path.read_text().split("\n"):
                if "\t" in line:
                    name, n = line.rsplit("\t", 1)
                    if int(n) >= min_count:
                        known.add(name)
        return cls(known, use_spacy)

    @property
    def nlp(self):
        if self._nlp is None:
            import spacy
            # Only the named-entity recognizer is needed: skip the rest for speed.
            self._nlp = spacy.load("en_core_web_sm",
                                   disable=["parser", "lemmatizer", "tagger", "attribute_ruler"])
        return self._nlp

    def _known_matches(self, text: str) -> list[Match]:
        out = []
        for run in CAP_RUN_RE.finditer(text):
            toks = []
            for m in re.finditer(r"[^\s-]+", run.group()):
                # Leak-check round 4: split on hyphens too, so a name joined to a
                # neighbouring word ("Interview-Rick Buy", "Re--Brian Hoskins",
                # "Debbie Brown-CEO") is still found. Candidates are checked
                # using the ORIGINAL text of the span, so hyphenated surnames
                # ("Mary Smith-Jones") still match as a unit.
                tok, s, e = m.group(), run.start() + m.start(), run.start() + m.end()
                # Round 3: possessives. "John Smith's" matches "John Smith",
                # and the "'s" stays in the text.
                if tok[-2:] in ("'s", "\u2019s"):
                    tok, e = tok[:-2], e - 2
                if tok:
                    toks.append((tok, s, e))
            i = 0
            while i < len(toks):
                hit = None
                for n in range(min(6, len(toks) - i), 1, -1):   # longest first
                    cand = toks[i:i + n]
                    if name_key(text[cand[0][1]:cand[-1][2]]) in self.known:
                        hit = cand
                        break
                if hit:
                    s, e = hit[0][1], hit[-1][2]
                    out.append(Match("person", text[s:e], s, e, "redact", " ".join(text[s:e].split())))
                    i += len(hit)
                else:
                    i += 1
        return out

    def _spacy_matches(self, doc) -> list[Match]:
        out = []
        text = doc.text  # spaCy rebuilds doc.text on every access: read it once (round 6)
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            start, end = trim_header_words(text, ent.start_char, ent.end_char)
            if end <= start:
                continue
            span = text[start:end]
            action = classify_spacy_person(span, text[max(0, start - 200):start], text[end:end + 200])
            if action:
                out.append(Match("person", span, start, end, action, " ".join(span.split())))
        return out

    def detect(self, text: str, doc=None) -> list[Match]:
        """Names only. Pass a pre-computed spaCy doc to reuse nlp.pipe batching."""
        found = self._known_matches(text)
        if self.use_spacy:
            if doc is None:
                doc = self.nlp(text[:SPACY_MAX_CHARS])
            found += self._spacy_matches(doc)
        return found

    def _refine_notes(self, m: Match) -> Match:
        """Trim a leading non-name word off a Notes match using the known list.

        detect.py's Notes pattern can absorb a capitalized word before the name
        ("Ask Phillip Allen/HOU/ECT"), which would delete "Ask" and give the
        person a different placeholder. If a shorter tail of the name is a
        known person, start the match there (Day 5, found in redactor tests).
        """
        if m.type != "notes_addr" or name_key(m.value) in self.known:
            return m
        toks = list(re.finditer(r"\S+", m.text))
        words = m.value.split()
        for i in range(1, len(words) - 1):          # keep at least 2 words
            tail = " ".join(words[i:])
            if name_key(tail) in self.known:
                new_start = m.start + toks[i].start()
                return Match(m.type, m.text[toks[i].start():], new_start, m.end, m.action, tail)
        return m

    def detect_all(self, text: str, doc=None) -> list[Match]:
        """Pattern detectors + names, overlaps resolved (longest / escalations win)."""
        patterns = [self._refine_notes(m) for m in detect(text)]
        return _resolve_overlaps(patterns + self.detect(text, doc))


# --- Shell entry point: summarize one batch ---------------------------------
def _summarize(manifest: Path) -> None:
    from parse import ParseError, parse_file

    det = NameDetector.from_file()
    print(f"known names loaded: {len(det.known)}")
    rels, bodies = [], []
    for rel in manifest.read_text().split("\n"):
        if not rel:
            continue
        try:
            bodies.append(parse_file(REPO_DIR / rel).body)
            rels.append(rel)
        except ParseError:
            continue

    start = time.time()
    counts, sample_path = Counter(), REPO_DIR / "data" / f"names_samples_{manifest.stem}.tsv"
    truncated = sum(1 for b in bodies if len(b) > SPACY_MAX_CHARS)
    docs = det.nlp.pipe((b[:SPACY_MAX_CHARS] for b in bodies), batch_size=64)
    with sample_path.open("w") as samples:
        for rel, body, doc in zip(rels, bodies, docs):
            known = det._known_matches(body)
            spacy_hits = det._spacy_matches(doc)
            for m in known:
                counts["known_list"] += 1
                samples.write(f"known_list\tredact\t{' '.join(m.text.split())}\t{rel}\n")
            for m in spacy_hits:
                counts[f"spacy_{m.action}"] += 1
                samples.write(f"spacy\t{m.action}\t{' '.join(m.text.split())}\t{rel}\n")
            # Names found by spaCy that the list missed (how much spaCy adds)
            k_spans = [(m.start, m.end) for m in known]
            counts["spacy_only"] += sum(
                1 for m in spacy_hits if all(m.end <= s or m.start >= e for s, e in k_spans))
    secs = time.time() - start

    print(f"messages: {len(bodies)}  ({truncated} bodies truncated to {SPACY_MAX_CHARS:,} chars for spaCy)")
    print(f"known-list matches:       {counts['known_list']}")
    print(f"spaCy names -> redact:    {counts['spacy_redact']}")
    print(f"spaCy names -> escalate:  {counts['spacy_escalate']}")
    print(f"spaCy names not on list:  {counts['spacy_only']}")
    print(f"time: {secs:.0f}s ({len(bodies) / secs:.0f} messages/s)")
    print(f"every match listed in {sample_path.relative_to(REPO_DIR)} (stays local)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 src/names.py <batch manifest>")
    _summarize(Path(sys.argv[1]))
