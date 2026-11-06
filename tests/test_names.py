"""Tests for src/names.py and src/known_people.py.

Most tests use the known-people list only (no spaCy). The last test is a
smoke test that runs spaCy itself; it's skipped if spaCy isn't installed.
"""
import pytest

from known_people import names_from_header
from names import NameDetector, classify_spacy_person, trim_header_words


# --- known_people: extracting names from X- headers --------------------------
@pytest.mark.parametrize("header, expected", [
    ("Phillip K Allen", ["Phillip K Allen", "Phillip Allen"]),
    ('"Meg St. John" <mstjohn@Haas.Berkeley.EDU>', ["Meg St. John"]),
    ("John Arnold/HOU/ECT@ECT, Scott Neal/HOU/ECT@ECT", ["John Arnold", "Scott Neal"]),
    ("Peter del Vecchio <pdel@enron.com>", ["Peter del Vecchio"]),
])
def test_names_from_header(header, expected):
    assert names_from_header(header) == expected


@pytest.mark.parametrize("header", [
    "Gas Daily",                      # newsletter as sender (round 5)
    "Enron Announcements",            # org word
    "<all.houston@enron.com>",        # address only
    "ENRON NORTH AMERICA",            # all caps
    "Undisclosed Recipients",
    "pete",                           # one lowercase word
])
def test_header_entries_that_are_not_people(header):
    assert names_from_header(header) == []


# --- known-list matching in bodies --------------------------------------------
@pytest.fixture
def det():
    return NameDetector({"Phillip K Allen", "Phillip Allen", "Peter del Vecchio", "John Arnold"},
                        use_spacy=False)


def test_known_name_in_body(det):
    (m,) = det.detect("Please ask Phillip Allen about the deal.")
    assert (m.type, m.text, m.action) == ("person", "Phillip Allen", "redact")


def test_longest_known_name_wins(det):
    (m,) = det.detect("Phillip K. Allen called")
    assert m.text == "Phillip K. Allen"


def test_known_name_with_particle(det):
    (m,) = det.detect("cc Peter del Vecchio today")
    assert m.text == "Peter del Vecchio"


def test_unknown_capitalized_words_not_matched(det):
    assert det.detect("Houston Ship Channel Gas Daily") == []


def test_detect_all_merges_patterns_and_names(det):
    text = "John Arnold/HOU/ECT@ECT wrote: call John Arnold at 713-853-1234"
    kinds = [m.type for m in det.detect_all(text)]
    assert kinds == ["notes_addr", "person", "phone"]   # Notes match beats the shorter name


def test_known_list_trims_word_absorbed_before_notes_name():
    det = NameDetector({"Vince Kaminski"}, use_spacy=False)
    (m,) = det.detect_all("Please Ask Vince Kaminski/HOU/ECT")
    assert (m.text, m.value) == ("Vince Kaminski/HOU/ECT", "Vince Kaminski")


def test_escalation_inside_longer_match_does_not_block_redaction():
    # Leak-check round 1: "Mark" (ambiguous, escalated) must not stop the
    # whole Notes address from being redacted.
    from detect import Match, _resolve_overlaps
    notes = Match("notes_addr", "Mark Torres/Corp/Enron@ENRON", 0, 28, "redact", "Mark Torres")
    mark = Match("person", "Mark", 0, 4, "escalate", "Mark")
    assert _resolve_overlaps([mark, notes]) == [notes]


# Leak-check round 2: names in X- headers with quotes, titles, glued suffixes
@pytest.mark.parametrize("text, expected", [
    ("'Scott Josey' <sjosey@enron.com>", "Scott Josey"),
    ("John Brindle- VP Research Group", "John Brindle"),
    ("Brad McKay.Mail <bmckay@enron.com>", "Brad McKay."),
])
def test_known_names_with_header_punctuation(text, expected):
    det = NameDetector({"Scott Josey", "John Brindle", "Brad McKay"}, use_spacy=False)
    (m,) = [m for m in det.detect(text)]
    assert m.text == expected


@pytest.mark.parametrize("text", ["Re: John Smith's offer", "Re: John Smith\u2019s offer"])
def test_possessive_name_matches_and_keeps_apostrophe_s(text):
    det = NameDetector({"John Smith"}, use_spacy=False)
    (m,) = det.detect(text)
    assert m.text == "John Smith" and text[m.end:m.end + 2] in ("'s", "\u2019s")


def test_names_from_header_quotes_and_titles():
    assert names_from_header("'Scott Josey' <sjosey@enron.com>, John Brindle- VP Research") == \
        ["Scott Josey", "John Brindle"]


# --- rules for spaCy PERSON entities -------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("Sara Shackleton", "redact"),
    ("Jeff", "redact"),
    ("Subject", None),               # header word (round 5)
    ("Portfolio", None),
    ("ENRON", None),                 # all caps
    ("Enron Energy Services", None), # org words
    ("Q3 2001", None),               # digits
    ("john.doe@enron.com", None),    # address
])
def test_classify_spacy_person(text, expected):
    assert classify_spacy_person(text) == expected


# Round 5: ambiguous single words are judged by context.
@pytest.mark.parametrize("before, word, after, expected", [
    ("", "May", " I ask a question?", "escalate"),            # sentence start, more text
    ("Done. ", "Will", " you send it?", "escalate"),
    ("\n", "Mark", " the date on your calendar", "escalate"),
    ("Please talk to ", "Frank", " about the deal.", "redact"),  # mid-sentence
    ("Thanks,\n", "Frank", "\n", "redact"),                   # sign-off alone on line
    ("Hi ", "Bob", ", see below", "redact"),
    ("", "Jeff", " said yes", "redact"),                        # not an ambiguous word
])
def test_ambiguous_words_judged_by_context(before, word, after, expected):
    assert classify_spacy_person(word, before, after) == expected


# Round 6: header words glued onto a name from the next line are trimmed.
@pytest.mark.parametrize("text, expected", [
    ("John\nSubject: deal", "John"),
    ("Jennifer\nSent: Monday", "Jennifer"),
    ("John Arnold\nTo: x", "John Arnold"),
    ("Sara Shackleton", "Sara Shackleton"),       # nothing to trim
])
def test_trim_header_words(text, expected):
    end = text.index(":") if ":" in text else len(text)   # spaCy's span ends before the colon
    s, e = trim_header_words(text, 0, end)
    assert text[s:e] == expected


def test_entity_that_is_only_a_header_word_is_dropped():
    assert trim_header_words("Subject: hi", 0, 7) == (0, 0)


# --- spaCy smoke test (runs only where spaCy + model are installed) -------------
def test_spacy_finds_a_name_not_on_the_list():
    pytest.importorskip("spacy")
    det = NameDetector(set(), use_spacy=True)
    found = [m.text for m in det.detect("Please send the contract to Sara Shackleton by Friday.")]
    assert any("Shackleton" in t for t in found), found
