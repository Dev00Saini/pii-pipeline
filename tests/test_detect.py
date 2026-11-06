"""Tests for src/detect.py.

Cases marked xfail are KNOWN LIMITATIONS, kept on purpose: they document what
the detectors miss, so the gaps are visible instead of silent.
"""
import pytest

from detect import detect


def types(text):
    return [(m.type, m.text) for m in detect(text)]


# --- Email ---------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("Send it to john.smith@enron.com today", "john.smith@enron.com"),
    ("From: <Mike.Roberts@ENRON.COM>", "Mike.Roberts@ENRON.COM"),
    ("contact mstjohn@haas.berkeley.edu please", "mstjohn@haas.berkeley.edu"),
    ("reply to o'brien+deals@aol.com", "o'brien+deals@aol.com"),
    ("email me at a.b@enron.com.", "a.b@enron.com"),   # sentence-ending dot excluded
])
def test_email_found(text, expected):
    assert ("email", expected) in types(text)


def test_email_value_is_lowercased_for_consistent_placeholders():
    (m,) = detect("Mike.Roberts@ENRON.COM")
    assert m.value == "mike.roberts@enron.com"


def test_not_an_email():
    assert types("meeting @ 3pm in room 4@") == []


# --- Lotus Notes addresses ---------------------------------------------------
@pytest.mark.parametrize("text, name", [
    ("To: Vince J Kaminski/HOU/ECT@ECT", "Vince J Kaminski"),
    ("Forwarded by Patricia Tlapek/HOU/ECT on 06/12/2000", "Patricia Tlapek"),
    ("cc: Mary-Ann O'Neil/NA/Enron@Enron, ", "Mary-Ann O'Neil"),
    ("From: John Doe/Enron@EnronXGate", "John Doe"),
])
def test_notes_address(text, name):
    ms = [m for m in detect(text) if m.type == "notes_addr"]
    assert len(ms) == 1 and ms[0].value == name


def test_city_state_is_not_a_notes_address():
    assert types("Our office in Houston/TX is closed") == []


# --- Phone numbers -----------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("call (713) 853-1234 now", "(713) 853-1234"),
    ("call 713-853-1234", "713-853-1234"),
    ("call 713.853.1234", "713.853.1234"),
    ("call +1 713 853 1234", "+1 713 853 1234"),
    ("call 713-853-1234 x5678", "713-853-1234 x5678"),
    ("call 713-853-1234 ext. 12", "713-853-1234 ext. 12"),
    ("Phone: 853-1234", "853-1234"),                     # labeled 7-digit
    ("fax 853.1234", "853.1234"),
])
def test_phone_found(text, expected):
    assert ("phone", expected) in types(text)


@pytest.mark.parametrize("text", [
    "on 2001-10-15 we met",          # ISO date
    "on 10/15/2001 we met",          # US date
    "price $1,234.56 per MWh",       # price
    "deal 123456 and 7891011",       # deal / ticket numbers
    "at 10:30 or 14:45",             # times
    "server 192.168.100.1",          # IP address
    "costs 853-1234 units",          # unlabeled 7-digit: ambiguous, skipped
    "volume 001 2345 678",           # 00-prefixed ID too short to be international
    "deal 0012345678901",            # unseparated 00-prefixed run: an ID
])
def test_not_a_phone(text):
    assert [t for t in types(text) if t[0] == "phone"] == []


# --- Escalate-only: SSN-like and card-like -----------------------------------
def test_ssn_like_escalated():
    (m,) = detect("my number is 123-45-6789")
    assert (m.type, m.action) == ("ssn_like", "escalate")


@pytest.mark.parametrize("text", ["000-12-3456", "666-12-3456", "912-34-5678", "123-00-4567"])
def test_impossible_ssns_ignored(text):
    assert types(text) == []


@pytest.mark.parametrize("text", [
    "acct 000000000077131",          # zero-padded ID (passed Luhn in batch_000)
    "years 30 2001 2000 2001",       # run of dates (passed Luhn in batch_000)
    "ref 4111-111-111-111-1",        # card digits, wrong grouping
])
def test_not_card_like(text):
    assert [t for t in types(text) if t[0] == "card_like"] == []


@pytest.mark.parametrize("text, expected", [
    ("tel 0044 207 78 36777", "0044 207 78 36777"),     # found in batch_000
    ("call +44 20 7783 6777", "+44 20 7783 6777"),
    ("call +1 (713) 853-1234", "+1 (713) 853-1234"),
])
def test_international_phone(text, expected):
    assert ("phone", expected) in types(text)
    assert [t for t in types(text) if t[0] == "card_like"] == []


def test_card_like_escalated_only_if_luhn_valid():
    assert ("card_like", "4111 1111 1111 1111") in types("card 4111 1111 1111 1111")
    assert types("ref 4111 1111 1111 1112") == []        # fails checksum


# --- Mixed text ---------------------------------------------------------------
def test_signature_block():
    sig = "Thanks,\nJeff Dasovich/SFO/EES@EES\nPhone: (415) 782-7822\njeff.dasovich@enron.com"
    assert [m.type for m in detect(sig)] == ["notes_addr", "phone", "email"]


# --- Known limitations (documented, not fixed) --------------------------------
@pytest.mark.xfail(reason="phone number split across a line break", strict=True)
def test_phone_split_across_lines():
    assert ("phone", "713-853-\n1234") in types("call 713-853-\n1234")


@pytest.mark.xfail(reason="unformatted 10-digit numbers skipped: too many IDs look the same", strict=True)
def test_unformatted_ten_digits():
    assert any(t[0] == "phone" for t in types("call 7138531234"))


@pytest.mark.xfail(reason="name before a Notes address absorbs a leading capitalized word", strict=True)
def test_notes_leading_capitalized_word():
    (m,) = [m for m in detect("Please Ask Vince Kaminski/HOU/ECT") if m.type == "notes_addr"]
    assert m.value == "Vince Kaminski"
