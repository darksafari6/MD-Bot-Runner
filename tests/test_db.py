from __future__ import annotations

import time

from wamanager.db import DEFAULT_CONFIG, Database


def test_creates_bot_with_defaults(db: Database):
    bot = db.create_bot("support", "Support Bot")
    assert bot.id == "support"
    assert bot.status == "stopped"
    assert bot.config["command_prefix"] == "!"
    assert {cmd["name"] for cmd in bot.commands} >= {"ping", "help", "info"}


def test_update_bot_merges_json_fields(db: Database):
    db.create_bot("b1", "Bot")
    merged = {**DEFAULT_CONFIG, "command_prefix": ".", "outbound_per_minute": 5}
    updated = db.update_bot("b1", config=merged, name="Renamed")
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.config["command_prefix"] == "."
    assert updated.config["outbound_per_minute"] == 5


def test_unknown_fields_are_ignored(db: Database):
    db.create_bot("b1", "Bot")
    updated = db.update_bot("b1", nonsense="value")  # type: ignore[arg-type]
    assert updated is not None
    assert updated.name == "Bot"


def test_commands_can_be_replaced(db: Database):
    db.create_bot("b1", "Bot")
    db.replace_commands(
        "b1",
        [
            {"name": "hours", "response": "9-5", "enabled": True},
            {"name": "", "response": "dropped"},
            {"name": "empty", "response": "   "},
        ],
    )
    commands = db.list_commands("b1")
    assert [c["name"] for c in commands] == ["hours"]


def test_messages_are_paginated_newest_last(db: Database):
    db.create_bot("b1", "Bot")
    for index in range(20):
        db.add_message("b1", "chat@s.whatsapp.net", "Chat", "in", f"m{index}")
    recent = db.list_messages("b1", limit=5)
    assert [m["body"] for m in recent] == ["m15", "m16", "m17", "m18", "m19"]


def test_conversations_group_by_chat(db: Database):
    db.create_bot("b1", "Bot")
    db.add_message("b1", "a@s.whatsapp.net", "A", "in", "one", created_at=time.time() - 5)
    db.add_message("b1", "a@s.whatsapp.net", "A", "out", "two", created_at=time.time() - 4)
    db.add_message("b1", "b@g.us", "B", "in", "three", created_at=time.time())

    chats = db.conversations("b1")
    assert len(chats) == 2
    assert chats[0]["chat_jid"] == "b@g.us"
    assert chats[0]["is_group"] is True
    assert chats[1]["total"] == 2
    assert chats[1]["last_body"] == "two"


def test_deleting_bot_cascades(db: Database):
    db.create_bot("b1", "Bot")
    db.add_message("b1", "a@s.whatsapp.net", "A", "in", "hi")
    assert db.delete_bot("b1")
    assert db.list_messages("b1") == []
    assert db.list_commands("b1") == []


def test_ai_usage_summary(db: Database):
    db.create_bot("b1", "Bot")
    db.add_ai_usage("b1", "gpt-4o-mini", 100, 50, 300)
    db.add_ai_usage("b1", "gpt-4o-mini", 10, 5, 100, ok=False, error="timeout")
    summary = db.ai_usage_summary("b1")
    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 110
    assert summary["output_tokens"] == 55
    assert summary["failures"] == 1


def test_memory_is_scoped_per_chat(db: Database):
    db.create_bot("b1", "Bot")
    db.append_memory("b1", "a@s.whatsapp.net", "user", "hello")
    db.append_memory("b1", "a@s.whatsapp.net", "assistant", "hi there")
    db.append_memory("b1", "b@s.whatsapp.net", "user", "other")

    memory = db.get_memory("b1", "a@s.whatsapp.net", turns=5)
    assert [m["content"] for m in memory] == ["hello", "hi there"]

    db.clear_memory("b1")
    assert db.get_memory("b1", "a@s.whatsapp.net") == []


def test_memory_turn_limit(db: Database):
    db.create_bot("b1", "Bot")
    for index in range(20):
        db.append_memory("b1", "a@s.whatsapp.net", "user", f"m{index}")
    assert len(db.get_memory("b1", "a@s.whatsapp.net", turns=2)) == 4
    assert db.get_memory("b1", "a@s.whatsapp.net", turns=0) == []
