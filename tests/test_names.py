"""Tests for src/names.py and src/known_people.py.

Most tests use the known-people list only (no spaCy). The last test is a
smoke test that runs spaCy itself; it's skipped if spaCy isn't installed.
"""
import pytest

from known_people import names_from_header
from names import NameDetector, classify_spacy_person


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


# --- rules for spaCy PERSON entities -------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("Sara Shackleton", "redact"),
    ("Jeff", "redact"),
    ("Will", "escalate"),            # common word
    ("Mark", "escalate"),
    ("ENRON", None),                 # all caps
    ("Enron Energy Services", None), # org words
    ("Q3 2001", None),               # digits
    ("john.doe@enron.com", None),    # address
])
def test_classify_spacy_person(text, expected):
    assert classify_spacy_person(text) == expected


# --- spaCy smoke test (runs only where spaCy + model are installed) -------------
def test_spacy_finds_a_name_not_on_the_list():
    pytest.importorskip("spacy")
    det = NameDetector(set(), use_spacy=True)
    found = [m.text for m in det.detect("Please send the contract to Sara Shackleton by Friday.")]
    assert any("Shackleton" in t for t in found), found
