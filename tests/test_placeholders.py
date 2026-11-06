"""Tests for src/placeholders.py: same value -> same placeholder, everywhere."""
import json
import os

import pytest

from placeholders import PlaceholderMap, normalize_key


@pytest.mark.parametrize("a, b", [
    ("Phillip K Allen", "Phillip Allen"),          # middle initial dropped
    ("Phillip K. Allen", "PHILLIP ALLEN"),          # case, period
    ("Scott Mills", "Scott  Mills"),                # spacing
])
def test_person_variants_share_a_key(a, b):
    assert normalize_key("person", a) == normalize_key("person", b)


def test_quoted_email_same_key():
    assert normalize_key("email", "'Jana.Morse@dynegy.com") == normalize_key("email", "jana.morse@dynegy.com")


def test_different_people_differ():
    assert normalize_key("person", "Scott Mills") != normalize_key("person", "Scott Neal")


@pytest.mark.parametrize("a, b", [
    ("(713) 853-1234", "713.853.1234"),
    ("1-713-853-1234", "713 853 1234"),
])
def test_phone_formats_share_a_key(a, b):
    assert normalize_key("phone", a) == normalize_key("phone", b)


def test_same_value_same_placeholder(tmp_path):
    m = PlaceholderMap(tmp_path / "map.json")
    p1 = m.get("notes_addr", "Phillip K Allen")       # from "Phillip K Allen/HOU/ECT"
    p2 = m.get("person", "Phillip Allen")             # from the body text
    assert p1 == p2 == "[PERSON_00001]"
    assert m.get("person", "John Arnold") == "[PERSON_00002]"
    assert m.get("email", "A.B@Enron.com") == m.get("email", "a.b@enron.com") == "[EMAIL_00001]"


def test_map_persists_and_counters_continue(tmp_path):
    path = tmp_path / "secrets" / "map.json"
    m = PlaceholderMap(path)
    m.get("person", "Phillip Allen")
    m.save()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"   # owner-only
    m2 = PlaceholderMap(path)
    assert m2.get("person", "Phillip Allen") == "[PERSON_00001]"
    assert m2.get("person", "New Person") == "[PERSON_00002]"
    assert json.loads(path.read_text())["counters"]["person"] == 1  # m2 not saved yet
