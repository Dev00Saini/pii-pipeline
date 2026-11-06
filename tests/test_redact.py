"""Tests for src/redact.py (no spaCy needed: uses the known-people list only)."""
from collections import Counter

import pytest

from names import NameDetector
from parse import ParsedMessage
from placeholders import PlaceholderMap
from redact import batch_id, redact_message


@pytest.fixture
def setup(tmp_path):
    det = NameDetector({"Phillip Allen", "John Arnold"}, use_spacy=False)
    return det, PlaceholderMap(tmp_path / "map.json"), Counter(), []


def msg(headers, body):
    return ParsedMessage(path="x", headers=headers, body=body)


def test_same_person_same_placeholder_across_headers_and_body(setup):
    det, pmap, counts, esc = setup
    m = msg({"from": "phillip.allen@enron.com", "x-from": "Phillip K Allen",
             "subject": "Note from Phillip Allen"},
            "Ask Phillip Allen/HOU/ECT@ECT or call 713-853-1234.\nThanks, John Arnold")
    out = redact_message(m, det, pmap, counts, esc, "data/maildir/a/inbox/1.")
    assert "Phillip" not in out and "Arnold" not in out and "853-1234" not in out
    assert out.count("[PERSON_00001]") == 3      # X-From, Subject, Notes address in body
    assert "From: [EMAIL_00001]" in out
    assert "[PHONE_00001]" in out and "[PERSON_00002]" in out


def test_folder_headers_dropped(setup):
    det, pmap, counts, esc = setup
    m = msg({"date": "Mon, 1 Jan 2001", "x-folder": "\\Phillip_Allen_Dec2000\\Inbox",
             "x-origin": "Allen-P", "x-filename": "pallen.nsf"}, "hi")
    out = redact_message(m, det, pmap, counts, esc, "f")
    assert "Allen" not in out and "X-Folder" not in out and "Date: Mon, 1 Jan 2001" in out


def test_escalations_left_in_place_and_logged(setup):
    det, pmap, counts, esc = setup
    out = redact_message(msg({}, "my SSN is 123-45-6789 ok"), det, pmap, counts, esc, "f")
    assert "123-45-6789" in out                    # not auto-redacted
    assert esc[0]["type"] == "ssn_like" and esc[0]["field"] == "body"
    assert "my SSN is 123-45-6789 ok" in esc[0]["context"]
    assert counts["escalate_ssn_like"] == 1


@pytest.mark.parametrize("arg, expected", [("7", "batch_007"), ("007", "batch_007"), ("batch_12", "batch_012")])
def test_batch_id(arg, expected):
    assert batch_id(arg) == expected


def test_bad_batch_id():
    with pytest.raises(ValueError):
        batch_id("seven")
