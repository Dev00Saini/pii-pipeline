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

_TOK = r"[A-Z][A-Za-z'.-]*"
_PART = "(?:" + "|".join(sorted(PARTICLES)) + ")"
CAP_RUN_RE = re.compile(rf"{_TOK}(?:[ \t]+(?:{_PART}[ \t]+){{0,2}}{_TOK})+")


def name_key(text: str) -> str:
    return " ".join(t.strip(".").casefold() for t in text.split())


def classify_spacy_person(text: str) -> str | None:
    """Return 'redact', 'escalate', or None (ignore) for a spaCy PERSON entity."""
    t = " ".join(text.split())
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
    if len(tokens) == 1:
        return "escalate" if t.strip(".,'").casefold() in AMBIGUOUS else "redact"
    return "redact"


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
            toks = [(m.group(), run.start() + m.start(), run.start() + m.end())
                    for m in re.finditer(r"\S+", run.group())]
            i = 0
            while i < len(toks):
                hit = None
                for n in range(min(5, len(toks) - i), 1, -1):   # longest first
                    cand = toks[i:i + n]
                    if name_key(" ".join(c[0] for c in cand)) in self.known:
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
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            action = classify_spacy_person(ent.text)
            if action:
                out.append(Match("person", ent.text, ent.start_char, ent.end_char, action,
                                 " ".join(ent.text.split())))
        return out

    def detect(self, text: str, doc=None) -> list[Match]:
        """Names only. Pass a pre-computed spaCy doc to reuse nlp.pipe batching."""
        found = self._known_matches(text)
        if self.use_spacy:
            if doc is None:
                doc = self.nlp(text[:SPACY_MAX_CHARS])
            found += self._spacy_matches(doc)
        return found

    def detect_all(self, text: str, doc=None) -> list[Match]:
        """Pattern detectors + names, overlaps resolved (longest / escalations win)."""
        return _resolve_overlaps(detect(text) + self.detect(text, doc))


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
                samples.write(f"known_list\tredact\t{m.text}\t{rel}\n")
            for m in spacy_hits:
                counts[f"spacy_{m.action}"] += 1
                samples.write(f"spacy\t{m.action}\t{m.text}\t{rel}\n")
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
