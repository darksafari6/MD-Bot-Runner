"""SQLite persistence for registered applications.

One row per managed project. The database is deliberately tiny: the project
directory on disk is the source of truth for code, this file only records how
the host should run it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    source_path     TEXT NOT NULL DEFAULT '',
    source_url      TEXT NOT NULL DEFAULT '',
    workdir         TEXT NOT NULL,
    package_manager TEXT NOT NULL DEFAULT 'npm',
    install_command TEXT NOT NULL DEFAULT '',
    build_command   TEXT NOT NULL DEFAULT '',
    start_command   TEXT NOT NULL DEFAULT '',
    framework       TEXT NOT NULL DEFAULT '',
    proxy_base      INTEGER NOT NULL DEFAULT 1,
    port            INTEGER,
    env             TEXT NOT NULL DEFAULT '{}',
    autostart       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class App:
    id: str
    name: str
    source_kind: str  # folder | git | upload
    workdir: str
    source_path: str = ""
    source_url: str = ""
    package_manager: str = "npm"
    install_command: str = ""
    build_command: str = ""
    start_command: str = ""
    framework: str = ""
    proxy_base: bool = True
    port: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    autostart: bool = False
    created_at: str = ""
    updated_at: str = ""

    @property
    def path(self) -> Path:
        return Path(self.workdir)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "workdir": self.workdir,
            "package_manager": self.package_manager,
            "install_command": self.install_command,
            "build_command": self.build_command,
            "start_command": self.start_command,
            "framework": self.framework,
            "proxy_base": self.proxy_base,
            "port": self.port,
            "env": dict(self.env),
            "autostart": self.autostart,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


EDITABLE_FIELDS = {
    "name",
    "package_manager",
    "install_command",
    "build_command",
    "start_command",
    "framework",
    "proxy_base",
    "port",
    "env",
    "autostart",
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns introduced after the first release (no data loss)."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(apps)")}
        additions = {
            "framework": "ALTER TABLE apps ADD COLUMN framework TEXT NOT NULL DEFAULT ''",
            "proxy_base": "ALTER TABLE apps ADD COLUMN proxy_base INTEGER NOT NULL DEFAULT 1",
        }
        for column, statement in additions.items():
            if column not in existing:
                conn.execute(statement)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- apps ---------------------------------------------------------
    def _row_to_app(self, row: sqlite3.Row) -> App:
        try:
            env = json.loads(row["env"] or "{}")
        except json.JSONDecodeError:
            env = {}
        return App(
            id=row["id"],
            name=row["name"],
            source_kind=row["source_kind"],
            source_path=row["source_path"],
            source_url=row["source_url"],
            workdir=row["workdir"],
            package_manager=row["package_manager"],
            install_command=row["install_command"],
            build_command=row["build_command"],
            start_command=row["start_command"],
            framework=row["framework"],
            proxy_base=bool(row["proxy_base"]),
            port=row["port"],
            env={str(k): str(v) for k, v in env.items()},
            autostart=bool(row["autostart"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_apps(self) -> list[App]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM apps ORDER BY name COLLATE NOCASE").fetchall()
        return [self._row_to_app(r) for r in rows]

    def get_app(self, app_id: str) -> App | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
        return self._row_to_app(row) if row else None

    def id_taken(self, app_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM apps WHERE id = ?", (app_id,)).fetchone()
        return row is not None

    def add_app(self, app: App) -> App:
        now = utcnow()
        app.created_at = app.created_at or now
        app.updated_at = now
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO apps (
                       id, name, source_kind, source_path, source_url, workdir,
                       package_manager, install_command, build_command,
                       start_command, framework, proxy_base, port, env, autostart,
                       created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    app.id,
                    app.name,
                    app.source_kind,
                    app.source_path,
                    app.source_url,
                    str(app.workdir),
                    app.package_manager,
                    app.install_command,
                    app.build_command,
                    app.start_command,
                    app.framework,
                    int(app.proxy_base),
                    app.port,
                    json.dumps(app.env),
                    int(app.autostart),
                    app.created_at,
                    app.updated_at,
                ),
            )
        return app

    def update_app(self, app_id: str, changes: dict[str, Any]) -> App | None:
        app = self.get_app(app_id)
        if app is None:
            return None
        for key, value in changes.items():
            if key not in EDITABLE_FIELDS:
                continue
            if key == "env":
                app.env = {str(k): str(v) for k, v in dict(value or {}).items()}
            elif key == "proxy_base":
                app.proxy_base = str(value).lower() not in {"0", "false", "off", "no", ""}
            elif key == "port":
                app.port = int(value) if value not in (None, "") else None
            elif key == "autostart":
                app.autostart = bool(value)
            elif key == "name":
                name = str(value).strip()
                if name:
                    app.name = name
            else:
                setattr(app, key, str(value))
        app.updated_at = utcnow()
        with self.connect() as conn:
            conn.execute(
                """UPDATE apps SET name=?, package_manager=?, install_command=?,
                       build_command=?, start_command=?, framework=?, proxy_base=?,
                       port=?, env=?, autostart=?, updated_at=? WHERE id=?""",
                (
                    app.name,
                    app.package_manager,
                    app.install_command,
                    app.build_command,
                    app.start_command,
                    app.framework,
                    int(app.proxy_base),
                    app.port,
                    json.dumps(app.env),
                    int(app.autostart),
                    app.updated_at,
                    app_id,
                ),
            )
        return app

    def delete_app(self, app_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))
        return cur.rowcount > 0

    # -- meta ---------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
