"""Work out how to install, build and start a JavaScript project.

Pure functions only: everything here takes file contents/paths and returns
plain data, so it can be tested without a build toolchain.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

# Lockfile -> package manager, checked in order.
LOCKFILES: tuple[tuple[str, str], ...] = (
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
)

INSTALL_COMMANDS = {
    "npm": "npm install",
    "pnpm": "pnpm install",
    "yarn": "yarn install",
    "bun": "bun install",
}

# Preferred dev-script names, most specific first.
VITE_SCRIPTS = ("dev", "start", "serve", "preview")
FRAMEWORK_HINTS = (
    ("vite.config.ts", "vite"),
    ("vite.config.js", "vite"),
    ("vite.config.mjs", "vite"),
    ("next.config.js", "next"),
    ("next.config.ts", "next"),
    ("next.config.mjs", "next"),
    ("astro.config.mjs", "astro"),
    ("remix.config.js", "remix"),
)

# Frontend build tools put the dev server port in the CLI, not in env.
DEFAULT_DEV_PORT = 5173

# Frameworks that take a base path on the command line. Behind the panel every
# app lives under /apps/<id>/, so a base keeps its module URLs correct.
BASE_CAPABLE = {"vite": "--base={base}", "astro": "--base {base}"}
BASE_IN_CONFIG = {"next", "cra"}
DEFAULT_NODE_PORT = 3000

PORT_PATTERNS = (
    re.compile(r"--port[= ](\d{2,5})"),
    re.compile(r"(?:^|\s)-p\s*(\d{2,5})"),
    re.compile(r"PORT=(\d{2,5})"),
    re.compile(r"listen\(\s*(\d{2,5})"),
)


class ProjectError(ValueError):
    """The directory is not a project the host knows how to run."""


@dataclass(slots=True)
class Plan:
    """How to run a project."""

    workdir: Path
    package_manager: str = "npm"
    install_command: str = "npm install"
    build_command: str = ""
    start_command: str = ""
    port: int = DEFAULT_DEV_PORT
    framework: str = "node"
    scripts: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "workdir": str(self.workdir),
            "package_manager": self.package_manager,
            "install_command": self.install_command,
            "build_command": self.build_command,
            "start_command": self.start_command,
            "port": self.port,
            "framework": self.framework,
            "scripts": dict(self.scripts),
            "notes": list(self.notes),
        }


def detect_package_manager(workdir: Path, manifest: dict | None = None) -> str:
    for filename, manager in LOCKFILES:
        if (workdir / filename).exists():
            return manager
    if manifest:
        declared = str(manifest.get("packageManager", "")).split("@")[0].strip()
        if declared in INSTALL_COMMANDS:
            return declared
    return "npm"


def read_manifest(workdir: Path) -> dict:
    path = workdir / "package.json"
    if not path.is_file():
        raise ProjectError(
            f"No package.json in {workdir}. Pick the folder that contains "
            "package.json (the project root, not the src folder)."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"package.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError("package.json must contain a JSON object.")
    return data


def detect_framework(workdir: Path, manifest: dict) -> str:
    for filename, framework in FRAMEWORK_HINTS:
        if (workdir / filename).exists():
            return framework
    deps = {}
    for key in ("dependencies", "devDependencies"):
        block = manifest.get(key)
        if isinstance(block, dict):
            deps.update(block)
    if "vite" in deps:
        return "vite"
    if "next" in deps:
        return "next"
    if "react-scripts" in deps:
        return "cra"
    if "react" in deps:
        return "react"
    if "express" in deps or "fastify" in deps or "koa" in deps:
        return "server"
    return "node"


def command_for(manager: str, script: str) -> str:
    if manager == "npm":
        return f"npm run {script}"
    if manager == "bun":
        return f"bun run {script}"
    return f"{manager} run {script}"


def extract_port(command: str) -> int | None:
    for pattern in PORT_PATTERNS:
        match = pattern.search(command)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 65535:
                return value
    return None


def pick_start_script(manifest: dict, manager: str, framework: str) -> tuple[str, str, str]:
    """Return (command, script body, notes) for the command that starts the app.

    The script body matters: the port usually lives in ``node server.js --port``,
    not in ``npm run start``.
    """
    raw_scripts = manifest.get("scripts")
    scripts = (
        {str(k): str(v) for k, v in raw_scripts.items()} if isinstance(raw_scripts, dict) else {}
    )

    # Next.js has a first-class dev server; `next dev` is the honest choice.
    if framework == "next" and "dev" in scripts:
        return command_for(manager, "dev"), scripts["dev"], []
    for name in VITE_SCRIPTS:
        if name in scripts:
            return command_for(manager, name), scripts[name], []
    if framework in {"vite", "react"} and manager == "npm":
        note = "No dev script found; starting Vite directly."
        return "npx --yes vite --host 0.0.0.0", "", [note]
    for name in ("start", "dev", "serve"):
        if name in scripts:
            return command_for(manager, name), scripts[name], []
    raise ProjectError(
        "package.json has no dev/start script. Add one, or set the start "
        "command manually when creating the app."
    )


def detect_build_script(manifest: dict, manager: str, framework: str) -> str:
    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict):
        return ""
    if framework in {"vite", "react", "cra", "astro", "remix"} and "build" in scripts:
        return command_for(manager, "build")
    return ""


def with_base(framework: str, command: str, base: str) -> str:
    """Add the proxy base path to a start command when the framework supports it.

    Only rewrites commands for frameworks where the flag is known to exist, and
    never if the user already passed a base themselves.
    """
    flag = BASE_CAPABLE.get(framework)
    if not flag or "--base" in command or not base:
        return command
    argv = split_command(command)
    # Insert after the script/tool being run: `npm run dev` -> `npm run dev -- --base=`
    if argv[0] in {"npm", "pnpm", "yarn", "bun"} and "run" in argv:
        return command + " -- " + flag.format(base=base)
    if argv[0] in {"npx", "node", "vite", "astro"} or argv[0].endswith(("vite", "astro")):
        return command + " " + flag.format(base=base)
    return command


def base_supported(framework: str) -> bool:
    return framework in BASE_CAPABLE or framework in BASE_IN_CONFIG


def normalise_entry(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def analyse(workdir: str | Path, package_manager: str | None = None) -> Plan:
    """Inspect a project directory and produce a run plan."""
    root = normalise_entry(workdir)
    if not root.is_dir():
        raise ProjectError(f"{root} is not a directory.")
    manifest = read_manifest(root)
    manager = package_manager or detect_package_manager(root, manifest)
    if manager not in INSTALL_COMMANDS:
        raise ProjectError(f"Unsupported package manager: {manager}")
    framework = detect_framework(root, manifest)
    start, body, notes = pick_start_script(manifest, manager, framework)
    port = (
        extract_port(start)
        or extract_port(body)
        or (DEFAULT_NODE_PORT if framework == "next" else DEFAULT_DEV_PORT)
    )
    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), dict) else {}
    return Plan(
        workdir=root,
        package_manager=manager,
        install_command=INSTALL_COMMANDS[manager],
        build_command=detect_build_script(manifest, manager, framework),
        start_command=start,
        port=port,
        framework=framework,
        scripts={str(k): str(v) for k, v in scripts.items()},
        notes=notes,
    )


@dataclass(slots=True)
class Toolchain:
    name: str
    path: str


def which(name: str, path_env: str | None = None) -> str | None:
    import shutil

    return shutil.which(name, path=path_env)


def available_managers(names: tuple[str, ...] = ("npm", "pnpm", "yarn", "bun")) -> list[Toolchain]:
    found = []
    for name in names:
        path = which(name)
        if path:
            found.append(Toolchain(name, path))
    return found


def split_command(command: str) -> list[str]:
    """Parse a user or detected command into argv (no shell involved)."""
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ProjectError(f"Could not parse command ({exc}): {command}") from exc
    if not parts:
        raise ProjectError("Command is empty.")
    return parts
