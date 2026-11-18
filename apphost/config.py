"""Configuration for the app host.

Everything is environment- or CLI-driven so the same code runs from the
installer, a `.deb`, Docker, or a bare checkout.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from dataclasses import dataclass, field, replace
from pathlib import Path

VERSION = "4.0.0"
APP_NAME = "apphost"
DISPLAY_NAME = "App Host"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def default_data_dir() -> Path:
    """Per-user data directory, honouring XDG and the system service."""
    override = _env("APPHOST_DATA_DIR")
    if override:
        return Path(override).expanduser()
    xdg = _env("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / APP_NAME
    if os.geteuid() == 0:
        return Path("/var/lib") / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = field(default_factory=default_data_dir)
    token: str = ""
    auth_required: bool = True
    max_apps: int = 10
    log_lines: int = 500
    install_timeout: int = 1800
    build_timeout: int = 1800
    start_timeout: int = 300
    public_url: str = ""
    packages: tuple[str, ...] = ("npm", "pnpm", "yarn", "bun")
    autostart: bool = True
    # Filesystem roots the panel may browse/import from. Linux default is
    # everything the service user can read; DOCKER narrows this.
    allowed_roots: tuple[str, ...] = ("/",)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "apphost.sqlite3"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "apps"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def with_overrides(self, **kw: object) -> Settings:
        return replace(self, **kw)

    def prepare(self) -> None:
        for path in (self.data_dir, self.workspace_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.data_dir, 0o700)

    def root_allowed(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        for root in self.allowed_roots:
            try:
                base = Path(root).expanduser().resolve()
            except OSError:
                continue
            if resolved == base or base in resolved.parents:
                return True
        return False


def load_settings(**overrides: object) -> Settings:
    """Build settings from the environment, then apply explicit overrides."""
    data_dir = overrides.pop("data_dir", None) or default_data_dir()
    token = _env("APPHOST_TOKEN")
    auth_required = _env("APPHOST_AUTH").lower() not in {"0", "false", "off", "no"}
    settings = Settings(
        host=_env("APPHOST_HOST", "127.0.0.1") or "127.0.0.1",
        port=_env_int("APPHOST_PORT", 8080),
        data_dir=Path(data_dir).expanduser(),
        token=token,
        auth_required=auth_required and bool(token),
        max_apps=_env_int("APPHOST_MAX_APPS", 10),
        log_lines=_env_int("APPHOST_LOG_LINES", 500),
        install_timeout=_env_int("APPHOST_INSTALL_TIMEOUT", 1800),
        build_timeout=_env_int("APPHOST_BUILD_TIMEOUT", 1800),
        start_timeout=_env_int("APPHOST_START_TIMEOUT", 300),
        public_url=_env("APPHOST_PUBLIC_URL"),
        autostart=_env("APPHOST_AUTOSTART").lower() not in {"0", "false", "off", "no"},
        allowed_roots=(_env("APPHOST_ROOTS") or "/",).split(":")
        if _env("APPHOST_ROOTS")
        else ("/",),
    )
    valid_overrides = {k: v for k, v in overrides.items() if hasattr(settings, k)}
    return replace(settings, **valid_overrides)


def ensure_token(settings: Settings) -> str:
    """Create a persistent access token on first run; keeps the panel closed by default."""
    if settings.token:
        return settings.token
    path = settings.data_dir / "token"
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return token
