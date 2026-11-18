"""Application settings, loaded from the environment (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "wamanager"
VERSION = "3.0.0"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader so we do not need python-dotenv as a dependency."""
    candidates = [path] if path else [Path.cwd() / ".env", Path.home() / f".config/{APP_NAME}/.env"]
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Real environment always wins over the file.
            os.environ.setdefault(key, value)
        return


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("WAMANAGER_DATA_DIR", Path("./data")))
    database_path: Path | None = None
    sessions_dir: Path | None = None

    host: str = field(default_factory=lambda: os.environ.get("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    api_token: str | None = field(default_factory=lambda: os.environ.get("API_TOKEN") or None)
    max_instances: int = field(default_factory=lambda: _env_int("MAX_INSTANCES", 10))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    log_buffer: int = field(default_factory=lambda: _env_int("LOG_BUFFER", 2000))

    # AI defaults; per-bot overrides live in the database.
    ai_base_url: str = field(
        default_factory=lambda: os.environ.get("AI_BASE_URL", "https://api.openai.com/v1")
    )
    ai_api_key: str | None = field(default_factory=lambda: os.environ.get("AI_API_KEY") or None)
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "gpt-4o-mini"))
    ai_timeout: float = field(default_factory=lambda: float(os.environ.get("AI_TIMEOUT", "60")))

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())
        object.__setattr__(
            self,
            "database_path",
            Path(self.data_dir) / "wamanager.sqlite3",
        )
        object.__setattr__(self, "sessions_dir", Path(self.data_dir) / "sessions")

    def prepare(self) -> None:
        """Create the data directories with owner-only permissions."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        assert self.sessions_dir is not None
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        # 0o700: WhatsApp credentials must not be world readable.
        self.data_dir.chmod(0o700)
        self.sessions_dir.chmod(0o700)

    @property
    def auth_required(self) -> bool:
        return bool(self.api_token)


def get_settings() -> Settings:
    load_dotenv()
    return Settings()
