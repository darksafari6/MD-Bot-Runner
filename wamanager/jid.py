"""WhatsApp JID helpers. Pure functions, no I/O, fully unit tested."""

from __future__ import annotations

import re
from dataclasses import dataclass

USER_SERVER = "s.whatsapp.net"
GROUP_SERVER = "g.us"
_JID_RE = re.compile(r"^[0-9A-Za-z._:-]{3,80}@(s\.whatsapp\.net|g\.us|broadcast|newsletter)$")


@dataclass(frozen=True)
class Target:
    jid: str
    number: str | None
    kind: str  # "user" | "group" | "other"


def normalize_number(raw: str) -> str | None:
    """Digits only, validated to a plausible E.164 length."""
    digits = re.sub(r"\D", "", raw or "")
    if 8 <= len(digits) <= 15:
        return digits
    return None


def parse_target(raw: str) -> Target | None:
    """Accept what a human types (a phone number) or a full jid. None if unusable."""
    text = (raw or "").strip()
    if not text:
        return None

    if "@" in text:
        jid = text.lower()
        if not _JID_RE.match(jid):
            return None
        if jid.endswith(f"@{GROUP_SERVER}"):
            return Target(jid=jid, number=None, kind="group")
        if jid.endswith(f"@{USER_SERVER}"):
            return Target(jid=jid, number=number_from_jid(jid), kind="user")
        return Target(jid=jid, number=None, kind="other")

    number = normalize_number(text)
    if not number:
        return None
    return Target(jid=f"{number}@{USER_SERVER}", number=number, kind="user")


def number_from_jid(jid: str) -> str:
    """'92300…:12@s.whatsapp.net' -> '92300…'"""
    return re.sub(r"\D", "", jid.split("@", 1)[0].split(":", 1)[0])


def is_group_jid(jid: str) -> bool:
    return jid.endswith(f"@{GROUP_SERVER}")


def is_ignorable_jid(jid: str) -> bool:
    if not jid:
        return True
    return jid == "status@broadcast" or jid.endswith("@newsletter") or jid.endswith("@broadcast")


def describe_jid(jid: str) -> str:
    if is_group_jid(jid):
        return f"Group {jid.split('@', 1)[0]}"
    number = number_from_jid(jid)
    return f"+{number}" if number else jid
