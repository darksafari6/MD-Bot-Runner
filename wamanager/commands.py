"""Command matching and response templating. Pure functions, fully tested."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Incoming:
    chat_jid: str
    sender_jid: str
    sender_number: str
    sender_name: str
    text: str
    is_group: bool


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    command: dict[str, Any] | None = None
    args: str = ""


def decide(config: dict[str, Any], commands: list[dict[str, Any]], message: Incoming) -> Decision:
    """Decide whether to answer, and with which command."""
    if message.is_group and not config.get("respond_to_groups", True):
        return Decision(False, "group replies disabled")
    if not message.is_group and not config.get("respond_to_dms", True):
        return Decision(False, "DM replies disabled")

    blocked = set(config.get("blocked_numbers") or [])
    allowed = set(config.get("allowed_numbers") or [])
    if message.sender_number in blocked:
        return Decision(False, "sender is blocked")
    if allowed and message.sender_number not in allowed:
        return Decision(False, "sender is not on the allowlist")

    text = (message.text or "").strip()
    if not text:
        return Decision(False, "empty message")

    prefix = str(config.get("command_prefix") or "!")
    enabled = [cmd for cmd in commands if cmd.get("enabled", True)]

    if text.startswith(prefix):
        body = text[len(prefix) :].strip()
        if not body:
            return Decision(False, "empty command")
        parts = body.split(None, 1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        for cmd in enabled:
            if str(cmd["name"]).lower() == name:
                return Decision(True, command=cmd, args=args)
        return Decision(False, f'unknown command "{name}"')

    lowered = text.lower()
    for cmd in enabled:
        if cmd.get("exact") and str(cmd["name"]).lower() == lowered:
            return Decision(True, command=cmd, args="")

    return Decision(False, "no command matched")


def format_uptime(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "0s"
    seconds = int(seconds)
    parts: list[str] = []
    for suffix, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{suffix}")
        if len(parts) == 2:
            break
    return " ".join(parts) or "0s"


def render(
    template: str,
    *,
    args: str,
    command_name: str,
    sender: str,
    bot_name: str,
    status: str,
    uptime_seconds: float,
    received: int,
    prefix: str,
    command_list: str,
) -> str:
    """Substitute {{placeholders}}; unknown placeholders are left untouched."""
    values = {
        "sender": sender,
        "args": args or "(none)",
        "command": command_name,
        "bot": bot_name,
        "instance": bot_name,
        "status": status,
        "uptime": format_uptime(uptime_seconds),
        "received": str(received),
        "prefix": prefix,
        "commands": command_list,
    }

    def replace(match: re.Match[str]) -> str:  # noqa: F821 - typing only
        key = match.group(1)
        return values.get(key, match.group(0))

    import re

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)


def command_list(commands: list[dict[str, Any]], prefix: str) -> str:
    names = [f"{prefix}{cmd['name']}" for cmd in commands if cmd.get("enabled", True)]
    return ", ".join(names) if names else "(none configured)"
