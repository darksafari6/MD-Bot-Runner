from __future__ import annotations

from wamanager.commands import Incoming, command_list, decide, format_uptime, render

BASE_CONFIG = {
    "command_prefix": "!",
    "respond_to_groups": True,
    "respond_to_dms": True,
    "allowed_numbers": [],
    "blocked_numbers": [],
}
COMMANDS = [
    {"name": "ping", "response": "pong", "enabled": True, "exact": False},
    {"name": "help", "response": "help text", "enabled": True, "exact": False},
    {"name": "off", "response": "disabled", "enabled": False, "exact": False},
    {"name": "hello", "response": "hi", "enabled": True, "exact": True},
]


def msg(text="!ping", number="923001234567", group=False, chat="923001234567@s.whatsapp.net"):
    return Incoming(
        chat_jid=chat,
        sender_jid=f"{number}@s.whatsapp.net",
        sender_number=number,
        sender_name="Ali",
        text=text,
        is_group=group,
    )


def test_matches_command_with_prefix():
    decision = decide(BASE_CONFIG, COMMANDS, msg())
    assert decision.allowed
    assert decision.command["name"] == "ping"


def test_passes_arguments():
    decision = decide(BASE_CONFIG, COMMANDS, msg("!ping hello world"))
    assert decision.args == "hello world"


def test_ignores_plain_chatter():
    assert not decide(BASE_CONFIG, COMMANDS, msg("good morning")).allowed


def test_unknown_command_is_rejected():
    decision = decide(BASE_CONFIG, COMMANDS, msg("!nope"))
    assert not decision.allowed
    assert "unknown command" in decision.reason


def test_disabled_commands_never_fire():
    assert not decide(BASE_CONFIG, COMMANDS, msg("!off")).allowed


def test_custom_prefix():
    config = {**BASE_CONFIG, "command_prefix": "."}
    assert decide(config, COMMANDS, msg(".ping")).allowed
    assert not decide(config, COMMANDS, msg("!ping")).allowed


def test_group_and_dm_toggles():
    assert not decide(
        {**BASE_CONFIG, "respond_to_groups": False}, COMMANDS, msg(group=True)
    ).allowed
    assert not decide({**BASE_CONFIG, "respond_to_dms": False}, COMMANDS, msg()).allowed


def test_blocklist_and_allowlist():
    blocked = {**BASE_CONFIG, "blocked_numbers": ["923001234567"]}
    assert not decide(blocked, COMMANDS, msg()).allowed
    allowed = {**BASE_CONFIG, "allowed_numbers": ["447700900123"]}
    assert not decide(allowed, COMMANDS, msg()).allowed
    assert decide(allowed, COMMANDS, msg(number="447700900123")).allowed


def test_exact_match_without_prefix():
    assert decide(BASE_CONFIG, COMMANDS, msg("Hello")).allowed
    assert not decide(BASE_CONFIG, COMMANDS, msg("hello there")).allowed


def test_empty_message():
    assert not decide(BASE_CONFIG, COMMANDS, msg("   ")).allowed


def test_render_placeholders():
    out = render(
        "Hi {{sender}}, {{command}} for {{bot}} ({{uptime}}, {{received}}) {{unknown}}",
        args="",
        command_name="ping",
        sender="Ali",
        bot_name="Support",
        status="connected",
        uptime_seconds=3725,
        received=12,
        prefix="!",
        command_list="!ping",
    )
    assert out == "Hi Ali, ping for Support (1h 2m, 12) {{unknown}}"


def test_command_list_only_enabled():
    assert command_list(COMMANDS, "!") == "!ping, !help, !hello"


def test_format_uptime():
    assert format_uptime(0) == "0s"
    assert format_uptime(45) == "45s"
    assert format_uptime(90) == "1m 30s"
    assert format_uptime(3725) == "1h 2m"
    assert format_uptime(90_000) == "1d 1h"
