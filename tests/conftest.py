from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wamanager.config import Settings  # noqa: E402
from wamanager.db import Database  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    config = Settings()
    object.__setattr__(config, "data_dir", tmp_path)
    object.__setattr__(config, "database_path", tmp_path / "test.sqlite3")
    object.__setattr__(config, "sessions_dir", tmp_path / "sessions")
    config.prepare()
    return config
