"""WhatsApp engine: one neonize (whatsmeow) client per bot.

Everything here talks to the real WhatsApp Web protocol. There is no mock
path: if a dependency is missing or WhatsApp is unreachable, the bot reports
that error and refuses to pretend it is connected.

neonize is imported lazily so the rest of the app (CLI, TUI, web panel, AI
tooling) keeps working on machines without the WhatsApp binding installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ai import AiClient
from .commands import Incoming, command_list, decide, render
from .config import Settings
from .db import Bot, Database
from .errors import AppError, ConflictError, NotFoundError, ValidationError
from .jid import describe_jid, is_group_jid, is_ignorable_jid, number_from_jid, parse_target
from .throttle import Policy, Throttle, typing_delay_ms

log = logging.getLogger(__name__)

MAX_RECONNECT_ATTEMPTS = 8
MAX_BACKOFF_S = 30.0


class EngineUnavailable(AppError):
    """Raised when neonize (or a system dependency) is missing.

    Subclasses AppError so the API answers with a clear message and a 503
    rather than an opaque 500 stack trace.
    """

    status = 503


# --------------------------------------------------------------------------
# inbound message parsing (pure-ish: works on any duck-typed protobuf)
# --------------------------------------------------------------------------
@dataclass
class Inbound:
    chat_jid: str
    sender_jid: str
    sender_name: str
    text: str
    kind: str
    is_group: bool
    message_id: str
    timestamp: float
    raw: Any = None


def _jid_str(value: Any) -> str:
    """Convert a neonize JID protobuf to 'user@server'."""
    try:
        from neonize.utils.jid import Jid2String

        return Jid2String(value)
    except Exception:  # pragma: no cover - defensive
        return str(value)


def extract_inbound(message: Any) -> Inbound | None:
    """Pull the fields we need out of a neonize Message protobuf.

    Returns None for messages we must ignore. This is deliberately tolerant:
    unknown shapes are skipped rather than crashing the bot loop.
    """
    info = getattr(message, "Info", None)
    if info is None:
        return None
    source = getattr(info, "MessageSource", None)
    if source is None or getattr(source, "IsFromMe", False):
        return None

    chat_jid = _jid_str(source.Chat)
    if is_ignorable_jid(chat_jid):
        return None

    is_group = bool(getattr(source, "IsGroup", False)) or is_group_jid(chat_jid)
    sender_jid = _jid_str(source.Sender) if is_group else chat_jid

    body = getattr(message, "Message", None)
    text, kind = _body_text(body)
    # Reactions, edits and protocol stubs carry no text and no media: they are
    # not worth counting as activity. Media without a caption IS activity.
    if not text and kind in {"text", "other"}:
        return None

    return Inbound(
        chat_jid=chat_jid,
        sender_jid=sender_jid,
        sender_name=str(getattr(info, "Pushname", "") or describe_jid(sender_jid)),
        text=text,
        kind=kind,
        is_group=is_group,
        message_id=str(getattr(info, "ID", "")),
        timestamp=float(getattr(info, "Timestamp", 0) or time.time()),
        raw=message,
    )


def _body_text(body: Any) -> tuple[str, str]:
    if body is None:
        return "", "text"
    for attr, kind in (
        ("conversation", "text"),
        ("extendedTextMessage", "text"),
        ("imageMessage", "image"),
        ("videoMessage", "video"),
        ("audioMessage", "audio"),
        ("documentMessage", "document"),
        ("stickerMessage", "sticker"),
    ):
        value = getattr(body, attr, None)
        if value is None:
            continue
        if kind == "text":
            text = getattr(value, "text", "") if attr != "conversation" else str(value)
        else:
            text = getattr(value, "caption", "") or ""
        if text:
            return str(text), kind
        if kind != "text":
            return "", kind
    return "", "other"


# --------------------------------------------------------------------------
# runtime
# --------------------------------------------------------------------------
@dataclass
class LiveBot:
    client: Any
    policy: Policy
    throttle: Throttle
    started_at: float
    stop_requested: bool = False
    reconnect_attempts: int = 0
    last_qr: str | None = None
    pairing_code: str | None = None


Listener = Callable[[Bot], Awaitable[None] | None]


@dataclass
class Engine:
    settings: Settings
    db: Database
    ai: AiClient
    live: dict[str, LiveBot] = field(default_factory=dict)
    listeners: list[Listener] = field(default_factory=list)

    # ------------------------------------------------------------ lifecycle
    def on_change(self, callback: Listener) -> None:
        self.listeners.append(callback)

    async def _emit(self, bot_id: str) -> None:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            return
        for callback in list(self.listeners):
            try:
                result = callback(bot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - listeners must never break the engine
                log.exception("change listener failed")

    def _require_neonize(self):
        try:
            from neonize.client import NewClient  # noqa: F401
            from neonize.events import (  # noqa: F401
                ConnectedEv,
                DisconnectedEv,
                MessageEv,
                PairStatusEv,
                QREv,
            )
        except ImportError as exc:
            raise EngineUnavailable(
                "neonize is not installed. Run ./scripts/install.sh (needs libmagic1 and ffmpeg)."
            ) from exc
        from neonize.client import NewClient
        from neonize.events import (
            ConnectedEv,
            DisconnectedEv,
            MessageEv,
            PairStatusEv,
            QREv,
        )

        return NewClient, {
            "connected": ConnectedEv,
            "disconnected": DisconnectedEv,
            "message": MessageEv,
            "qrid": QREv,
            "pair": PairStatusEv,
        }

    def _session_path(self, bot_id: str) -> Path:
        assert self.settings.sessions_dir is not None
        return self.settings.sessions_dir / bot_id

    # ---------------------------------------------------------------- start
    async def start(self, bot_id: str) -> Bot:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            raise NotFoundError(f'Bot "{bot_id}" not found')
        if bot_id in self.live:
            return bot
        if len(self.live) >= self.settings.max_instances:
            raise ConflictError(
                f"Instance limit reached (MAX_INSTANCES={self.settings.max_instances})."
            )
        if not shutil.which("ffmpeg"):
            # Media features degrade, but text bots work fine. Record it once.
            log.warning("ffmpeg not found: media sending will fail for bot %s", bot_id)

        NewClient, events = self._require_neonize()
        self._session_path(bot_id).mkdir(parents=True, exist_ok=True)

        policy = Policy.clamp(
            bot.config.get("outbound_per_minute", 20),
            bot.config.get("outbound_min_gap_ms", 1200),
        )
        client = NewClient(str(self._session_path(bot_id)))
        entry = LiveBot(
            client=client,
            policy=policy,
            throttle=Throttle(policy),
            started_at=time.time(),
        )
        self.live[bot_id] = entry

        self.db.update_bot(bot_id, status="starting", last_error=None)
        await self._emit(bot_id)

        @client.event(events["qrid"])
        def _on_qr(_client: Any, qr: bytes) -> None:
            code = qr.decode(errors="ignore") if isinstance(qr, bytes) else str(qr)
            entry.last_qr = code
            entry.pairing_code = None
            self.db.update_bot(bot_id, status="qr", last_error=None)
            self._schedule_emit(bot_id)

        @client.event(events["connected"])
        def _on_connected(_client: Any, _data: Any) -> None:
            entry.reconnect_attempts = 0
            entry.last_qr = None
            entry.pairing_code = None
            me = str(getattr(client, "jid", "") or "")
            number = number_from_jid(me) if "@" in me else me.replace(":", "").split("@")[0]
            stats = dict(self.db.get_bot(bot_id).stats)  # type: ignore[union-attr]
            stats["started_at"] = time.time()
            self.db.update_bot(
                bot_id,
                status="connected",
                identity_jid=me or None,
                identity_number=number or None,
                last_error=None,
                stats=stats,
            )
            self._schedule_emit(bot_id)

        @client.event(events["pair"])
        def _on_pair(_client: Any, data: Any) -> None:
            entry.pairing_code = str(data)
            self.db.update_bot(bot_id, status="pairing")
            self._schedule_emit(bot_id)

        @client.event(events["message"])
        def _on_message(client_ref: Any, message: Any) -> None:
            asyncio.create_task(self._handle_message(bot_id, message))

        @client.event(events["disconnected"])
        def _on_disconnected(_client: Any, data: Any) -> None:
            asyncio.create_task(self._handle_disconnect(bot_id, str(data)))

        # connect() blocks, so run it off the event loop.
        async def _connect() -> None:
            try:
                await asyncio.to_thread(client.connect)
            except EngineUnavailable:
                raise
            except Exception as exc:  # network, TLS, session corruption…
                log.warning("bot %s connect failed: %s", bot_id, exc)
                await self._handle_disconnect(bot_id, str(exc))

        asyncio.create_task(_connect())
        return self.db.get_bot(bot_id)  # type: ignore[return-value]

    def _schedule_emit(self, bot_id: str) -> None:
        with contextlib.suppress(RuntimeError):
            loop = asyncio.get_running_loop()
            loop.create_task(self._emit(bot_id))

    # ----------------------------------------------------------------- stop
    async def stop(self, bot_id: str, *, logout: bool = False) -> Bot:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            raise NotFoundError(f'Bot "{bot_id}" not found')

        entry = self.live.pop(bot_id, None)
        if entry is not None:
            entry.stop_requested = True
            with contextlib.suppress(Exception):
                if logout:
                    await asyncio.to_thread(entry.client.logout)
                await asyncio.to_thread(entry.client.stop)

        if logout and self._session_path(bot_id).exists():
            shutil.rmtree(self._session_path(bot_id), ignore_errors=True)

        stats = dict(bot.stats)
        stats["started_at"] = None
        updated = self.db.update_bot(
            bot_id,
            status="logged_out" if logout else "stopped",
            identity_jid=None if logout else bot.identity_jid,
            identity_number=None if logout else bot.identity_number,
            stats=stats,
        )
        await self._emit(bot_id)
        return updated  # type: ignore[return-value]

    async def stop_all(self) -> None:
        for bot_id in list(self.live):
            with contextlib.suppress(Exception):
                await self.stop(bot_id)

    async def _handle_disconnect(self, bot_id: str, detail: str) -> None:
        entry = self.live.get(bot_id)
        if entry is None or entry.stop_requested:
            return
        self.live.pop(bot_id, None)
        bot = self.db.get_bot(bot_id)
        if bot is None:
            return

        entry.reconnect_attempts += 1
        stats = dict(bot.stats)
        stats["started_at"] = None

        lowered = detail.lower()
        if "logged out" in lowered or "401" in lowered:
            shutil.rmtree(self._session_path(bot_id), ignore_errors=True)
            self.db.update_bot(
                bot_id,
                status="logged_out",
                identity_jid=None,
                last_error="Device was unlinked. Link it again to reconnect.",
                stats=stats,
            )
            await self._emit(bot_id)
            return

        if entry.reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
            stats["errors"] = int(stats.get("errors", 0)) + 1
            self.db.update_bot(
                bot_id,
                status="error",
                last_error=f"Gave up after {MAX_RECONNECT_ATTEMPTS} attempts: {detail[:200]}",
                stats=stats,
            )
            await self._emit(bot_id)
            return

        delay = min(2 ** (entry.reconnect_attempts - 1), MAX_BACKOFF_S)
        stats["errors"] = int(stats.get("errors", 0)) + 1
        self.db.update_bot(
            bot_id,
            status="reconnecting",
            last_error=(
                f"{detail[:200]} — retry {entry.reconnect_attempts}/"
                f"{MAX_RECONNECT_ATTEMPTS} in {delay:.0f}s"
            ),
            stats=stats,
        )
        await self._emit(bot_id)
        await asyncio.sleep(delay)
        if bot_id not in self.live and self.db.get_bot(bot_id) is not None:
            with contextlib.suppress(Exception):
                await self.start(bot_id)

    # ----------------------------------------------------------- pairing/qr
    def qr(self, bot_id: str) -> dict[str, Any]:
        entry = self.live.get(bot_id)
        bot = self.db.get_bot(bot_id)
        return {
            "qr": entry.last_qr if entry else None,
            "pairing_code": entry.pairing_code if entry else None,
            "status": bot.status if bot else "stopped",
        }

    async def request_pairing_code(self, bot_id: str, phone: str) -> dict[str, Any]:
        entry = self.live.get(bot_id)
        if entry is None:
            raise ConflictError("Start the bot before requesting a pairing code.")
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not (8 <= len(digits) <= 15):
            raise ValidationError("Enter a full international number (country code included).")
        try:
            from neonize.utils.enum import ClientName

            code = await asyncio.to_thread(entry.client.PairPhone, digits, True, ClientName.LINUX)
        except Exception as exc:
            raise ConflictError(f"Pairing code request failed: {exc}") from exc
        entry.pairing_code = str(code)
        entry.last_qr = None
        self.db.update_bot(bot_id, status="pairing")
        await self._emit(bot_id)
        return {"pairing_code": str(code)}

    # -------------------------------------------------------------- sending
    async def send(
        self,
        bot_id: str,
        to: str,
        text: str,
        *,
        origin: str = "manual",
        chat_name: str | None = None,
        record: bool = True,
    ) -> dict[str, Any]:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            raise NotFoundError(f'Bot "{bot_id}" not found')

        target = parse_target(to)
        if target is None:
            raise ValidationError("Enter a valid phone number or chat jid.")
        body = (text or "").strip()
        if not body:
            raise ValidationError("Message text cannot be empty.")
        if len(body) > 4096:
            raise ValidationError("Message is too long (max 4096 characters).")

        if bot.status != "connected":
            raise ConflictError("This bot is not connected. Start it and link a device first.")
        entry = self.live.get(bot_id)
        if entry is None:
            raise ConflictError("This bot has no live connection.")

        reserved = entry.throttle.reserve()
        if reserved.delay_ms:
            await asyncio.sleep(reserved.delay_ms / 1000.0)

        if bot.config.get("typing_indicator", True):
            await self._presence(entry, target.jid, composing=True)
            await asyncio.sleep(min(typing_delay_ms(body), 2_500) / 1000.0)
            await self._presence(entry, target.jid, composing=False)

        try:
            await asyncio.to_thread(entry.client.send_message, target.jid, body)
        except Exception as exc:
            stats = dict(bot.stats)
            stats["errors"] = int(stats.get("errors", 0)) + 1
            self.db.update_bot(bot_id, stats=stats, last_error=str(exc)[:300])
            raise ConflictError(f"WhatsApp rejected the message: {exc}") from exc

        if record:
            message = self.db.add_message(
                bot_id,
                target.jid,
                chat_name or describe_jid(target.jid),
                "out",
                body,
                sender_name="Bot",
                origin=origin,
            )
        else:
            message = {
                "bot_id": bot_id,
                "chat_jid": target.jid,
                "body": body,
                "direction": "out",
                "origin": origin,
                "created_at": time.time(),
            }

        stats = dict(bot.stats)
        stats["messages_out"] = int(stats.get("messages_out", 0)) + 1
        stats["last_activity"] = time.time()
        self.db.update_bot(bot_id, stats=stats)
        await self._emit(bot_id)
        return {"message": message, "waited_ms": reserved.delay_ms}

    async def _presence(self, entry: LiveBot, jid: str, *, composing: bool) -> None:
        try:
            from neonize.utils.enum import ChatPresence, ChatPresenceMedia

            state = (
                ChatPresence.CHAT_PRESENCE_COMPOSING
                if composing
                else ChatPresence.CHAT_PRESENCE_PAUSED
            )
            await asyncio.to_thread(
                entry.client.send_chat_presence,
                jid,
                state,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
        except Exception:
            # Presence is cosmetic; never let it block a send.
            pass

    # ------------------------------------------------------------- inbound
    async def _handle_message(self, bot_id: str, message: Any) -> None:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            return
        inbound = extract_inbound(message)
        if inbound is None:
            return

        stats = dict(bot.stats)
        stats["messages_in"] = int(stats.get("messages_in", 0)) + 1
        stats["last_activity"] = time.time()

        self.db.add_message(
            bot_id,
            inbound.chat_jid,
            describe_jid(inbound.chat_jid),
            "in",
            inbound.text or f"[{inbound.kind}]",
            sender_jid=inbound.sender_jid,
            sender_name=inbound.sender_name,
            origin="system",
            kind=inbound.kind,
        )

        if bot.config.get("auto_read") and inbound.message_id:
            entry = self.live.get(bot_id)
            if entry is not None:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        entry.client.mark_read,
                        inbound.message_id,
                        chat=inbound.chat_jid,
                        sender=inbound.sender_jid,
                    )

        await self._emit(bot_id)

        # Media without a caption cannot match a text command.
        if not inbound.text:
            self.db.update_bot(bot_id, stats=stats)
            return

        decision = decide(
            bot.config,
            bot.commands,
            Incoming(
                chat_jid=inbound.chat_jid,
                sender_jid=inbound.sender_jid,
                sender_number=number_from_jid(inbound.sender_jid),
                sender_name=inbound.sender_name,
                text=inbound.text,
                is_group=inbound.is_group,
            ),
        )

        if decision.allowed and decision.command is not None:
            await self._run_command(bot, inbound, decision, stats)
            return

        # No command matched: fall through to AI if it is enabled for this bot.
        # AI failures are logged and surfaced, never answered with a fake reply.
        if (
            bot.ai_enabled
            and not inbound.is_group
            or (bot.ai_enabled and bot.config.get("ai_in_groups", False))
        ):
            await self._run_ai(bot, inbound, stats)
            return

        self.db.update_bot(bot_id, stats=stats)

    async def _run_command(
        self, bot: Bot, inbound: Inbound, decision: Any, stats: dict[str, Any]
    ) -> None:
        command = decision.command
        assert command is not None
        body = render(
            str(command["response"]),
            args=decision.args,
            command_name=str(command["name"]),
            sender=inbound.sender_name,
            bot_name=bot.name,
            status=bot.status,
            uptime_seconds=time.time() - float(stats.get("started_at") or time.time()),
            received=int(stats.get("messages_in", 0)),
            prefix=bot.command_prefix,
            command_list=command_list(bot.commands, bot.command_prefix),
        )
        try:
            await self.send(
                bot.id,
                inbound.chat_jid,
                body,
                origin="command",
                chat_name=describe_jid(inbound.chat_jid),
                record=False,
            )
            stats["commands_handled"] = int(stats.get("commands_handled", 0)) + 1
            self.db.add_message(
                bot.id,
                inbound.chat_jid,
                describe_jid(inbound.chat_jid),
                "out",
                body,
                sender_name="Bot",
                origin="command",
            )
        except Exception as exc:
            log.warning("command reply failed for %s: %s", bot.id, exc)
            stats["errors"] = int(stats.get("errors", 0)) + 1
        self.db.update_bot(bot.id, stats=stats)

    async def _run_ai(self, bot: Bot, inbound: Inbound, stats: dict[str, Any]) -> None:
        turns = int(bot.config.get("ai_history_turns", 8))
        history = self.db.get_memory(bot.id, inbound.chat_jid, turns)
        persona = str(bot.config.get("ai_persona") or "").strip()
        messages = (([{"role": "system", "content": persona}] if persona else []) + history) + [
            {"role": "user", "content": inbound.text}
        ]

        try:
            reply = await asyncio.to_thread(self.ai.complete, messages, bot_config=bot.config)
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            stats["errors"] = int(stats.get("errors", 0)) + 1
            self.db.update_bot(bot.id, stats=stats, last_error=f"AI: {message}"[:300])
            self.db.add_ai_usage(bot.id, "unknown", 0, 0, 0, ok=False, error=str(message)[:300])
            await self._emit(bot.id)
            return

        self.db.add_ai_usage(
            bot.id, reply.model, reply.prompt_tokens, reply.output_tokens, reply.latency_ms
        )
        self.db.append_memory(bot.id, inbound.chat_jid, "user", inbound.text)
        self.db.append_memory(bot.id, inbound.chat_jid, "assistant", reply.text)

        try:
            await self.send(
                bot.id,
                inbound.chat_jid,
                reply.text,
                origin="ai",
                chat_name=describe_jid(inbound.chat_jid),
                record=False,
            )
            self.db.add_message(
                bot.id,
                inbound.chat_jid,
                describe_jid(inbound.chat_jid),
                "out",
                reply.text,
                sender_name="Bot",
                origin="ai",
            )
            stats["ai_replies"] = int(stats.get("ai_replies", 0)) + 1
            stats["messages_out"] = int(stats.get("messages_out", 0)) + 1
        except Exception as exc:
            stats["errors"] = int(stats.get("errors", 0)) + 1
            self.db.update_bot(bot.id, last_error=f"AI send failed: {exc}"[:300])
        self.db.update_bot(bot.id, stats=stats)

    # ---------------------------------------------------------------- misc
    def status(self) -> dict[str, Any]:
        bots = self.db.list_bots()
        return {
            "total": len(bots),
            "connected": sum(1 for bot in bots if bot.status == "connected"),
            "live": len(self.live),
            "limit": self.settings.max_instances,
        }

    def throttle_status(self, bot_id: str) -> dict[str, Any]:
        entry = self.live.get(bot_id)
        if entry is None:
            return {"remaining": 0, "limit": 0, "min_gap_ms": 0}
        return {
            "remaining": entry.throttle.remaining(),
            "limit": entry.policy.limit,
            "min_gap_ms": entry.policy.min_gap_ms,
        }
