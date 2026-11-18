from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apphost.db import App, Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.sqlite3")


def make_app(app_id: str = "demo", **kw: object) -> App:
    base = {
        "id": app_id,
        "name": "Demo",
        "source_kind": "folder",
        "workdir": "/tmp/demo",
        "start_command": "npm run dev",
        "port": 5173,
    }
    base.update(kw)
    return App(**base)  # type: ignore[arg-type]


def test_schema_is_created(db: Database) -> None:
    with db.connect() as conn:
        tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"apps", "meta"} <= tables


def test_add_and_get(db: Database) -> None:
    db.add_app(make_app(env={"A": "1"}))
    stored = db.get_app("demo")
    assert stored is not None
    assert stored.name == "Demo"
    assert stored.env == {"A": "1"}
    assert stored.created_at and stored.updated_at


def test_ids_are_unique(db: Database) -> None:
    db.add_app(make_app())
    with pytest.raises(sqlite3.IntegrityError):
        db.add_app(make_app())


def test_update_only_allowed_fields(db: Database) -> None:
    db.add_app(make_app())
    updated = db.update_app("demo", {"name": "Renamed", "id": "hacked", "workdir": "/etc"})
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.id == "demo"
    assert updated.workdir == "/tmp/demo"


def test_update_port_and_autostart(db: Database) -> None:
    db.add_app(make_app(autostart=False))
    updated = db.update_app("demo", {"port": "6000", "autostart": True})
    assert updated is not None
    assert updated.port == 6000
    assert updated.autostart is True


def test_update_port_blank_clears(db: Database) -> None:
    db.add_app(make_app())
    updated = db.update_app("demo", {"port": ""})
    assert updated is not None and updated.port is None


def test_update_missing_app_returns_none(db: Database) -> None:
    assert db.update_app("ghost", {"name": "x"}) is None


def test_env_roundtrip_through_json(db: Database) -> None:
    db.add_app(make_app(env={"WA_SESSION": "main", "LOG": "debug"}))
    db.update_app("demo", {"env": {"ONLY": "one"}})
    stored = db.get_app("demo")
    assert stored is not None
    assert stored.env == {"ONLY": "one"}


def test_listing_is_sorted_by_name(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.sqlite3")
    db.add_app(make_app("b", name="zulu"))
    db.add_app(make_app("a", name="alpha"))
    assert [a.id for a in db.list_apps()] == ["a", "b"]


def test_delete(db: Database) -> None:
    db.add_app(make_app())
    assert db.delete_app("demo") is True
    assert db.get_app("demo") is None
    assert db.delete_app("demo") is False


def test_meta_upsert(db: Database) -> None:
    db.set_meta("k", "1")
    db.set_meta("k", "2")
    assert db.get_meta("k") == "2"
    assert db.get_meta("missing", "fallback") == "fallback"


def test_id_taken(db: Database) -> None:
    assert db.id_taken("demo") is False
    db.add_app(make_app())
    assert db.id_taken("demo") is True


def test_broken_env_json_does_not_crash(db: Database) -> None:
    db.add_app(make_app())
    with db.connect() as conn:
        conn.execute("UPDATE apps SET env = 'not-json' WHERE id = 'demo'")
    stored = db.get_app("demo")
    assert stored is not None and stored.env == {}
