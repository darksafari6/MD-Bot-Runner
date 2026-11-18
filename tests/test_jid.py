from __future__ import annotations

import pytest

from wamanager.jid import (
    describe_jid,
    is_group_jid,
    is_ignorable_jid,
    normalize_number,
    number_from_jid,
    parse_target,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+92 300-1234567", ("923001234567@s.whatsapp.net", "923001234567", "user")),
        ("923001234567", ("923001234567@s.whatsapp.net", "923001234567", "user")),
        ("120363000000000000@g.us", ("120363000000000000@g.us", None, "group")),
        ("923001234567@s.whatsapp.net", ("923001234567@s.whatsapp.net", "923001234567", "user")),
    ],
)
def test_parse_target_accepts(raw, expected):
    target = parse_target(raw)
    assert target is not None
    assert (target.jid, target.number, target.kind) == expected


@pytest.mark.parametrize(
    "raw", ["", "123", "not a number", "abc@evil.example.com", "../../etc/passwd"]
)
def test_parse_target_rejects(raw):
    assert parse_target(raw) is None


def test_normalize_number_bounds():
    assert normalize_number("+44 (7700) 900-123") == "447700900123"
    assert normalize_number("1234567") is None
    assert normalize_number("1" * 16) is None


def test_number_from_jid_strips_device():
    assert number_from_jid("923001234567:12@s.whatsapp.net") == "923001234567"


@pytest.mark.parametrize(
    "jid,ignored",
    [
        ("status@broadcast", True),
        ("123@newsletter", True),
        ("", True),
        ("923001234567@s.whatsapp.net", False),
    ],
)
def test_is_ignorable_jid(jid, ignored):
    assert is_ignorable_jid(jid) is ignored


def test_describe_jid():
    assert describe_jid("120363000000000000@g.us").startswith("Group")
    assert describe_jid("923001234567@s.whatsapp.net") == "+923001234567"
    assert is_group_jid("a@g.us")
    assert not is_group_jid("a@s.whatsapp.net")
