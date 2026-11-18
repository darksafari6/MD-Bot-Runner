"""Engine tests that do not require WhatsApp connectivity.

They exercise the real code paths with protobuf-shaped stand-ins, so message
parsing and error handling are covered without a network connection.
"""

from __future__ import annotations

import types

import pytest

from wamanager.engine import Engine, extract_inbound
from wamanager.errors import ConflictError, NotFoundError, ValidationError


# --------------------------------------------------------------- fixtures
def make_message(
    *,
    chat="923001234567@s.whatsapp.net",
    sender=None,
    group=False,
    from_me=False,
    text="!ping",
    body_attr="conversation",
    pushname="Ali",
):
    """Build an object shaped like neonize's Message protobuf."""
    sender = sender or chat

    # Mirror neonize's JID protobuf: User/Server fields, and a str() that
    # yields "user@server" like the real protobuf __str__ does.
    class Jid:
        def __init__(self, jid: str) -> None:
            self.User = jid.split("@")[0]
            self.Server = jid.split("@")[1] if "@" in jid else ""

        def __str__(self) -> str:
            return f"{self.User}@{self.Server}"

    source = types.SimpleNamespace(
        Chat=Jid(chat),
        Sender=Jid(sender),
        IsFromMe=from_me,
        IsGroup=group,
    )
    info = types.SimpleNamespace(
        MessageSource=source, Pushname=pushname, ID="MSG1", Timestamp=1_700_000_000
    )
    if body_attr == "conversation":
        body = types.SimpleNamespace(conversation=text, extendedTextMessage=None)
    else:
        body = types.SimpleNamespace(
            conversation=None, **{body_attr: types.SimpleNamespace(caption=text)}
        )
    return types.SimpleNamespace(Info=info, Message=body)


def test_extract_plain_text():
    inbound = extract_inbound(make_message())
    assert inbound is not None
    assert inbound.text == "!ping"
    assert inbound.chat_jid == "923001234567@s.whatsapp.net"
    assert inbound.is_group is False


def test_extract_group_attributes_to_participant():
    inbound = extract_inbound(
        make_message(
            chat="120363000000000000@g.us", sender="447700900123@s.whatsapp.net", group=True
        )
    )
    assert inbound is not None
    assert inbound.is_group is True
    assert inbound.sender_jid == "447700900123@s.whatsapp.net"


def test_ignores_own_messages_and_status():
    assert extract_inbound(make_message(from_me=True)) is None
    assert extract_inbound(make_message(chat="status@broadcast")) is None
    assert extract_inbound(make_message(chat="123@newsletter")) is None


def test_media_caption_is_used_as_text():
    inbound = extract_inbound(make_message(body_attr="imageMessage", text="look at this"))
    assert inbound is not None
    assert inbound.kind == "image"
    assert inbound.text == "look at this"


def test_uninterpretable_payload_returns_none():
    message = make_message()
    message.Message = types.SimpleNamespace(conversation=None, extendedTextMessage=None)
    assert extract_inbound(message) is None


# ------------------------------------------------------------- send guards
class StubEngine:
    """Engine with the WhatsApp client patched out — no network involved."""

    def __init__(self, db, settings):
        from wamanager.ai import AiClient

        self.engine = Engine(settings=settings, db=db, ai=AiClient(settings))
        self.db = db

    async def send(self, bot_id, to, text):
        return await self.engine.send(bot_id, to, text)


@pytest.fixture()
def stub(db, settings):
    return StubEngine(db, settings)


async def test_send_rejects_unknown_bot(stub):
    with pytest.raises(NotFoundError):
        await stub.send("ghost", "923001234567", "hi")


async def test_send_validates_recipient_before_state(stub, db):
    db.create_bot("b1", "Bot")
    with pytest.raises(ValidationError):
        await stub.send("b1", "definitely not a number", "hi")


async def test_send_requires_connection(stub, db):
    db.create_bot("b1", "Bot")
    with pytest.raises(ConflictError, match="not connected"):
        await stub.send("b1", "923001234567", "hi")


async def test_send_rejects_empty_and_long_text(stub, db):
    db.create_bot("b1", "Bot")
    with pytest.raises(ValidationError):
        await stub.send("b1", "923001234567", "   ")
    with pytest.raises(ValidationError):
        await stub.send("b1", "923001234567", "x" * 5000)


async def test_start_without_neonize_reports_clearly(db, settings, monkeypatch):
    """When the engine is missing, the error must name the fix."""
    from wamanager.ai import AiClient

    engine = Engine(settings=settings, db=db, ai=AiClient(settings))
    db.create_bot("b1", "Bot")
    monkeypatch.setattr(
        Engine,
        "_require_neonize",
        lambda self: (_ for _ in ()).throw(
            RuntimeError(
                "neonize is not installed. Run ./scripts/install.sh (needs libmagic1 and ffmpeg)."
            )
        ),
    )
    with pytest.raises(RuntimeError, match="not installed"):
        await engine.start("b1")


def test_qr_reports_not_running(db, settings):
    from wamanager.ai import AiClient

    engine = Engine(settings=settings, db=db, ai=AiClient(settings))
    assert engine.qr("missing") == {"qr": None, "pairing_code": None, "status": "stopped"}
