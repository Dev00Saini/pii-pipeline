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


# Leak-check round 1 (found by bin/leak_check.sh on batches 000-002)
@pytest.mark.parametrize("text, expected", [
    ("To: 'jana.morse@dynegy.com'", "'jana.morse@dynegy.com"),
    ("cc <.ward@enron.com>", ".ward@enron.com"),
])
def test_email_with_leading_quote_or_dot(text, expected):
    assert ("email", expected) in types(text)


def test_all_caps_notes_name_with_at_domain():
    ms = [m for m in detect("cc: JEFF SHIVELY/ENRON@Gateway") if m.type == "notes_addr"]
    assert len(ms) == 1 and ms[0].value == "JEFF SHIVELY"


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


@pytest.mark.parametrize("text, name", [
    ("cc: Russ Severson/HOU/ECT@ECT, Scott \nMills/HOU/ECT@ECT", "Scott Mills"),
    ("Kimberly Brown/HOU/ECT@ECT, Paul T \nLucci/NA/Enron@Enron", "Paul T Lucci"),
])
def test_notes_name_wrapped_across_lines(text, name):
    names = [m.value for m in detect(text) if m.type == "notes_addr"]
    assert names[-1] == name


@pytest.mark.parametrize("text, name", [
    ("cc: Michael Danielson/SF/ECT@ECT, Peter del Vecchio/HOU/ECT@ECT", "Peter del Vecchio"),
    ("To:     Monica L.\n     Brown/Internal/Accenture@Accenture", "Monica L. Brown"),
    ("Jan van der Berg/LON/ECT@ECT", "Jan van der Berg"),
])
def test_notes_round4_particles_and_initial_wrap(text, name):
    names = [m.value for m in detect(text) if m.type == "notes_addr"]
    assert names[-1] == name


def test_word_ending_in_period_does_not_join_across_line():
    (m,) = [m for m in detect("Regards.\n   John Arnold/HOU/ECT@ECT") if m.type == "notes_addr"]
    assert m.value == "John Arnold"


def test_plain_line_break_does_not_join_previous_word():
    (m,) = [m for m in detect("Thanks\nJohn Arnold/HOU/ECT@ECT") if m.type == "notes_addr"]
    assert m.value == "John Arnold"


@pytest.mark.parametrize("text", [
    "From (MM/DD/YY):      To (MM/DD/YY)",     # form date placeholders
    "Rate/Term/Downpayment",                    # slash-separated list
    "Gas/Power/Coal desks",
])
def test_notes_lookalikes_rejected(text):
    assert [t for t in types(text) if t[0] == "notes_addr"] == []


def test_mixed_case_orgs_need_at_domain():
    assert ("notes_addr", "Laura Harder/Corp/Enron@Enron") in types("cc: Laura Harder/Corp/Enron@Enron")


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
@pytest.mark.xfail(reason="two-column forwarded headers: first name on a different line", strict=True)
def test_notes_two_column_layout():
    text = "To:     Sheri A.\n11/27/2001 11:10 AM          Righi/Internal/Accenture@Accenture"
    (m,) = [m for m in detect(text) if m.type == "notes_addr"]
    assert m.value == "Sheri A. Righi"


@pytest.mark.xfail(reason="phone number split across a line break", strict=True)
def test_phone_split_across_lines():
    assert ("phone", "713-853-\n1234") in types("call 713-853-\n1234")


@pytest.mark.xfail(reason="unformatted 10-digit numbers skipped: too many IDs look the same", strict=True)
def test_unformatted_ten_digits():
    assert any(t[0] == "phone" for t in types("call 7138531234"))


@pytest.mark.xfail(reason="wrapped line ending in 'Word \\n' before a name gets joined to it", strict=True)
def test_notes_wrap_after_unrelated_word():
    (m,) = [m for m in detect("Regards \nJohn Arnold/HOU/ECT") if m.type == "notes_addr"]
    assert m.value == "John Arnold"


@pytest.mark.xfail(reason="name before a Notes address absorbs a leading capitalized word", strict=True)
def test_notes_leading_capitalized_word():
    (m,) = [m for m in detect("Please Ask Vince Kaminski/HOU/ECT") if m.type == "notes_addr"]
    assert m.value == "Vince Kaminski"
