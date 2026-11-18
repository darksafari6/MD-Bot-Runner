"""SQLite persistence: bots, commands, messages, AI config and usage.

One file database in WAL mode. All writes go through a lock so the web panel,
the TUI and any CLI call can share the same process safely.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bots (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    created_at   REAL NOT NULL,
    -- stopped | starting | qr | pairing | connected | reconnecting | logged_out | error
    status       TEXT NOT NULL DEFAULT 'stopped',
    identity_jid TEXT,
    identity_name TEXT,
    identity_number TEXT,
    last_error   TEXT,
    autostart    INTEGER NOT NULL DEFAULT 1,
    -- JSON blob: prefix, toggles, allow/block lists, pacing, ai settings
    config       TEXT NOT NULL,
    stats        TEXT NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    bot_id    TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    response  TEXT NOT NULL,
    enabled   INTEGER NOT NULL DEFAULT 1,
    exact     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bot_id, name)
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    chat_jid    TEXT NOT NULL,
    chat_name   TEXT NOT NULL,
    sender_jid  TEXT,
    sender_name TEXT,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    origin      TEXT NOT NULL DEFAULT 'system',
    kind        TEXT NOT NULL DEFAULT 'text',
    body        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_bot_chat ON messages(bot_id, chat_jid, id);
CREATE INDEX IF NOT EXISTS idx_messages_bot_time ON messages(bot_id, created_at);

CREATE TABLE IF NOT EXISTS ai_usage (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id         TEXT NOT NULL,
    created_at     REAL NOT NULL,
    model          TEXT NOT NULL,
    prompt_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER NOT NULL DEFAULT 0,
    ok             INTEGER NOT NULL DEFAULT 1,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_bot ON ai_usage(bot_id, created_at);

CREATE TABLE IF NOT EXISTS ai_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id     TEXT NOT NULL,
    chat_jid   TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_memory_chat ON ai_memory(bot_id, chat_jid, id);
"""

DEFAULT_CONFIG: dict[str, Any] = {
    "command_prefix": "!",
    "respond_to_groups": True,
    "respond_to_dms": True,
    "allowed_numbers": [],
    "blocked_numbers": [],
    "auto_read": False,
    "typing_indicator": True,
    "outbound_per_minute": 20,
    "outbound_min_gap_ms": 1200,
    "ai_enabled": False,
    "ai_model": None,
    "ai_base_url": None,
    "ai_persona": "You are a concise, friendly WhatsApp assistant. Keep replies under 60 words.",
    "ai_history_turns": 8,
}

DEFAULT_STATS: dict[str, Any] = {
    "messages_in": 0,
    "messages_out": 0,
    "commands_handled": 0,
    "ai_replies": 0,
    "errors": 0,
    "started_at": None,
    "last_activity": None,
}

DEFAULT_COMMANDS = [
    ("ping", "pong 🏓", 1, 0),
    ("help", "Commands: {{commands}}", 1, 0),
    ("info", "🤖 {{bot}}\nStatus: {{status}}\nUptime: {{uptime}}", 1, 0),
]


@dataclass
class Bot:
    id: str
    name: str
    created_at: float
    status: str
    config: dict[str, Any]
    stats: dict[str, Any]
    identity_jid: str | None = None
    identity_name: str | None = None
    identity_number: str | None = None
    last_error: str | None = None
    autostart: bool = True
    commands: list[dict[str, Any]] = field(default_factory=list)

    @property
    def command_prefix(self) -> str:
        return str(self.config.get("command_prefix", "!"))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.config.get("ai_enabled"))


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    # ---------------------------------------------------------------- schema
    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ bots
    def list_bots(self) -> list[Bot]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM bots ORDER BY created_at").fetchall()
            return [self._row_to_bot(row) for row in rows]

    def get_bot(self, bot_id: str) -> Bot | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
            return self._row_to_bot(row) if row else None

    def create_bot(self, bot_id: str, name: str, config: dict[str, Any] | None = None) -> Bot:
        now = time.time()
        merged = {**DEFAULT_CONFIG, **(config or {})}
        with self._lock:
            self._conn.execute(
                """INSERT INTO bots(id, name, created_at, status, config, stats, updated_at)
                   VALUES (?, ?, ?, 'stopped', ?, ?, ?)""",
                (bot_id, name, now, json.dumps(merged), json.dumps(DEFAULT_STATS), now),
            )
            self._conn.executemany(
                """INSERT INTO commands(bot_id, name, response, enabled, exact)
                   VALUES (?, ?, ?, ?, ?)""",
                [(bot_id, n, r, e, x) for n, r, e, x in DEFAULT_COMMANDS],
            )
            self._conn.commit()
        bot = self.get_bot(bot_id)
        assert bot is not None
        return bot

    def update_bot(self, bot_id: str, **fields: Any) -> Bot | None:
        allowed = {
            "name",
            "status",
            "identity_jid",
            "identity_name",
            "identity_number",
            "last_error",
            "autostart",
            "config",
            "stats",
        }
        sets, values = ["updated_at = ?"], [time.time()]
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"config", "stats"}:
                value = json.dumps(value)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get_bot(bot_id)
        values.append(bot_id)
        with self._lock:
            self._conn.execute(f"UPDATE bots SET {', '.join(sets)} WHERE id=?", values)
            self._conn.commit()
        return self.get_bot(bot_id)

    def delete_bot(self, bot_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------- commands
    def list_commands(self, bot_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, response, enabled, exact FROM commands WHERE bot_id=? ORDER BY rowid",
                (bot_id,),
            ).fetchall()
        return [
            {
                "name": row["name"],
                "response": row["response"],
                "enabled": bool(row["enabled"]),
                "exact": bool(row["exact"]),
            }
            for row in rows
        ]

    def replace_commands(self, bot_id: str, commands: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                bot_id,
                str(cmd["name"]).strip().lower(),
                str(cmd["response"]),
                1 if cmd.get("enabled", True) else 0,
                1 if cmd.get("exact") else 0,
            )
            for cmd in commands
            if str(cmd.get("name", "")).strip() and str(cmd.get("response", "")).strip()
        ]
        with self._lock:
            self._conn.execute("DELETE FROM commands WHERE bot_id=?", (bot_id,))
            self._conn.executemany(
                """INSERT INTO commands(bot_id, name, response, enabled, exact)
                   VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
            self._conn.commit()

    # -------------------------------------------------------------- messages
    def add_message(
        self,
        bot_id: str,
        chat_jid: str,
        chat_name: str,
        direction: str,
        body: str,
        *,
        sender_jid: str | None = None,
        sender_name: str | None = None,
        origin: str = "system",
        kind: str = "text",
        created_at: float | None = None,
    ) -> dict[str, Any]:
        now = created_at or time.time()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO messages
                   (bot_id, chat_jid, chat_name, sender_jid, sender_name,
                    direction, origin, kind, body, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bot_id,
                    chat_jid,
                    chat_name,
                    sender_jid,
                    sender_name,
                    direction,
                    origin,
                    kind,
                    body,
                    now,
                ),
            )
            self._conn.commit()
            message_id = cur.lastrowid
        return {
            "id": message_id,
            "bot_id": bot_id,
            "chat_jid": chat_jid,
            "chat_name": chat_name,
            "sender_jid": sender_jid,
            "sender_name": sender_name,
            "direction": direction,
            "origin": origin,
            "kind": kind,
            "body": body,
            "created_at": now,
        }

    def list_messages(
        self, bot_id: str, chat_jid: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            if chat_jid:
                rows = self._conn.execute(
                    """SELECT * FROM messages WHERE bot_id=? AND chat_jid=?
                       ORDER BY id DESC LIMIT ?""",
                    (bot_id, chat_jid, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM messages WHERE bot_id=? ORDER BY id DESC LIMIT ?",
                    (bot_id, limit),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def conversations(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT chat_jid,
                          MAX(chat_name)            AS chat_name,
                          MAX(id)                   AS last_id,
                          MAX(created_at)           AS last_at,
                          COUNT(*)                  AS total
                   FROM messages WHERE bot_id=?
                   GROUP BY chat_jid ORDER BY last_at DESC LIMIT ?""",
                (bot_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                last = self._conn.execute(
                    "SELECT body, direction FROM messages WHERE id=?", (row["last_id"],)
                ).fetchone()
                result.append(
                    {
                        "chat_jid": row["chat_jid"],
                        "chat_name": row["chat_name"],
                        "last_body": last["body"] if last else "",
                        "last_direction": last["direction"] if last else "in",
                        "last_at": row["last_at"],
                        "total": row["total"],
                        "is_group": str(row["chat_jid"]).endswith("@g.us"),
                    }
                )
        return result

    def clear_messages(self, bot_id: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM messages WHERE bot_id=?", (bot_id,))
            self._conn.commit()
            return cur.rowcount

    # -------------------------------------------------------------- ai parts
    def add_ai_usage(
        self,
        bot_id: str,
        model: str,
        prompt_tokens: int,
        output_tokens: int,
        latency_ms: int,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO ai_usage
                   (bot_id, created_at, model, prompt_tokens, output_tokens, latency_ms, ok, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bot_id,
                    time.time(),
                    model,
                    prompt_tokens,
                    output_tokens,
                    latency_ms,
                    int(ok),
                    error,
                ),
            )
            self._conn.commit()

    def ai_usage_summary(self, bot_id: str) -> dict[str, Any]:
        day_ago = time.time() - 86400
        with self._lock:
            total = self._conn.execute(
                """SELECT COUNT(*) AS calls,
                          COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(ok = 0), 0)        AS failures
                   FROM ai_usage WHERE bot_id=?""",
                (bot_id,),
            ).fetchone()
            day = self._conn.execute(
                """SELECT COUNT(*) AS calls,
                          COALESCE(SUM(prompt_tokens + output_tokens), 0) AS tokens
                   FROM ai_usage WHERE bot_id=? AND created_at > ?""",
                (bot_id, day_ago),
            ).fetchone()
        return {
            "calls": total["calls"],
            "prompt_tokens": total["prompt_tokens"],
            "output_tokens": total["output_tokens"],
            "failures": total["failures"],
            "today_calls": day["calls"],
            "today_tokens": day["tokens"],
        }

    def append_memory(self, bot_id: str, chat_jid: str, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO ai_memory(bot_id, chat_jid, role, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (bot_id, chat_jid, role, content, time.time()),
            )
            self._conn.commit()

    def get_memory(self, bot_id: str, chat_jid: str, turns: int = 8) -> list[dict[str, str]]:
        limit = max(0, min(turns, 50)) * 2
        if limit == 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                """SELECT role, content FROM ai_memory
                   WHERE bot_id=? AND chat_jid=? ORDER BY id DESC LIMIT ?""",
                (bot_id, chat_jid, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def clear_memory(self, bot_id: str, chat_jid: str | None = None) -> int:
        with self._lock:
            if chat_jid:
                cur = self._conn.execute(
                    "DELETE FROM ai_memory WHERE bot_id=? AND chat_jid=?", (bot_id, chat_jid)
                )
            else:
                cur = self._conn.execute("DELETE FROM ai_memory WHERE bot_id=?", (bot_id,))
            self._conn.commit()
            return cur.rowcount

    # ----------------------------------------------------------------- utils
    def _row_to_bot(self, row: sqlite3.Row) -> Bot:
        return Bot(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            status=row["status"],
            config=json.loads(row["config"]),
            stats=json.loads(row["stats"]),
            identity_jid=row["identity_jid"],
            identity_name=row["identity_name"],
            identity_number=row["identity_number"],
            last_error=row["last_error"],
            autostart=bool(row["autostart"]),
            commands=self.list_commands(row["id"]),
        )
