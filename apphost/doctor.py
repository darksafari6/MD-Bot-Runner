"""Environment diagnostics.

Reports exactly what this machine can and cannot run, so the panel never
promises a build it has no toolchain for.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun", "corepack")
NICE_TO_HAVE = ("git", "ffmpeg", "zip", "unzip", "tar", "curl")
# Present in some deployments; absence is not a failure.
OPTIONAL = {"ffmpeg", "zip", "unzip", "tar", "curl", "corepack"}

INSTALL_HINTS = {
    "node": "sudo apt install nodejs  (or https://nodejs.org, or nvm)",
    "npm": "sudo apt install npm  (ships with nodejs)",
    "pnpm": "corepack enable pnpm   or   npm install -g pnpm",
    "yarn": "corepack enable yarn   or   npm install -g yarn",
    "bun": "curl -fsSL https://bun.sh/install | bash",
    "corepack": "ships with Node.js 16.9+",
    "git": "sudo apt install git",
    "ffmpeg": "sudo apt install ffmpeg",
    "zip": "sudo apt install zip",
    "unzip": "sudo apt install unzip",
    "tar": "sudo apt install tar",
    "curl": "sudo apt install curl",
}


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    version: str = ""
    required: bool = False
    hint: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "version": self.version,
            "required": self.required,
            "hint": self.hint,
        }


@dataclass(slots=True)
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.required)

    @property
    def missing_required(self) -> list[Check]:
        return [c for c in self.checks if c.required and not c.ok]

    def get(self, name: str) -> Check | None:
        for check in self.checks:
            if check.name == name:
                return check
        return None

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [c.to_json() for c in self.checks],
            "missing_required": [c.name for c in self.missing_required],
        }

    def as_text(self) -> str:
        lines = []
        for check in self.checks:
            mark = "ok  " if check.ok else ("MISS" if check.required else "warn")
            suffix = check.version or check.detail
            lines.append(f"[{mark}] {check.name:<10} {suffix}")
            if not check.ok and check.hint:
                lines.append(f"          -> {check.hint}")
        return "\n".join(lines)


def _run_version(argv: list[str], timeout: float = 6.0) -> str:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0].strip() if text else ""


TOOL_VERSIONS = {
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "pnpm": ["pnpm", "--version"],
    "yarn": ["yarn", "--version"],
    "bun": ["bun", "--version"],
    "corepack": ["corepack", "--version"],
    "git": ["git", "--version"],
    "ffmpeg": ["ffmpeg", "-version"],
    "curl": ["curl", "--version"],
}


def check_tool(name: str, required: bool = False) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(
            name=name,
            ok=False,
            detail="not installed",
            required=required,
            hint=INSTALL_HINTS.get(name, ""),
        )
    version = ""
    if name in TOOL_VERSIONS:
        version = _run_version(TOOL_VERSIONS[name])
    return Check(name=name, ok=True, detail=path, version=version, required=required)


def check_node_runtime() -> Check:
    """Node must exist *and* be runnable: a broken install is a common failure."""
    base = check_tool("node", required=True)
    if not base.ok:
        return base
    version = base.version.lstrip("v")
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        return Check("node", True, base.detail, base.version, required=True)
    if major < 18:
        return Check(
            name="node",
            ok=False,
            detail=f"Node {version} is too old",
            version=base.version,
            required=True,
            hint="Install Node.js 18+ (Vite 5 and React 18 require it).",
        )
    return base


def check_loopback() -> Check:
    """Apps bind 127.0.0.1; make sure TCP works at all here."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        return Check("loopback", True, f"TCP ok (tried port {port})", required=True)
    except OSError as exc:
        return Check(
            "loopback", False, str(exc), required=True, hint="Check network namespaces / sandbox."
        )


def check_writable(path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("data-dir", True, str(path), required=True)
    except OSError as exc:
        return Check(
            "data-dir", False, str(exc), required=True, hint="Fix ownership of the data directory."
        )


def check_disk(path: Path) -> Check:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return Check("disk", False, str(exc), required=False)
    free_gb = usage.free / (1024**3)
    ok = free_gb >= 1.0
    return Check(
        name="disk",
        ok=ok,
        detail=f"{free_gb:.1f} GiB free",
        required=False,
        hint="" if ok else "node_modules need a few hundred MiB per app.",
    )


def check_python() -> Check:
    return Check(
        "python", True, platform.python_version(), platform.python_version(), required=False
    )


def diagnose(data_dir: Path, *, managers: tuple[str, ...] = PACKAGE_MANAGERS) -> Report:
    report = Report()
    report.checks.append(check_node_runtime())
    report.checks.append(check_tool("npm", required=False))
    for name in managers:
        if name in {"npm", "corepack"}:
            continue
        report.checks.append(check_tool(name, required=False))
    report.checks.append(check_tool("git", required=False))
    for name in ("ffmpeg", "zip", "unzip", "curl"):
        if name in NICE_TO_HAVE:
            report.checks.append(check_tool(name, required=False))
    report.checks.append(check_loopback())
    report.checks.append(check_writable(data_dir))
    report.checks.append(check_disk(data_dir))
    report.checks.append(
        Check("platform", True, f"{platform.system()} {platform.machine()}", required=False)
    )
    report.checks.append(check_python())
    return report


def manager_status(managers: tuple[str, ...]) -> list[dict[str, object]]:
    """Version table used by the UI header."""
    rows = []
    for name in managers:
        path = shutil.which(name)
        version = _run_version(TOOL_VERSIONS.get(name, [name, "--version"])) if path else ""
        rows.append({"name": name, "installed": bool(path), "path": path or "", "version": version})
    return rows


def node_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(("NODE_", "NPM_", "PNPM_", "BUN_"))}
