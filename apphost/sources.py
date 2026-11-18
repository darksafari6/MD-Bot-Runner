"""Getting a project onto the host: folder, git clone, or uploaded archive.

All three paths land in the app's workspace directory. Nothing is executed
from an uploaded file until the user starts it; archives are validated before
extraction (no absolute paths, no traversal, size caps).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ValidationError

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_MEMBERS = 50_000

IGNORED_DIRS = {
    "node_modules",
    ".git",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "out",
    "coverage",
    ".turbo",
    ".cache",
    "__pycache__",
    ".venv",
    "venv",
}


@dataclass(slots=True)
class Imported:
    workdir: Path
    kind: str
    detail: str = ""


def is_git_url(value: str) -> bool:
    value = value.strip()
    return value.startswith(("http://", "https://", "git@", "ssh://", "git://")) or value.endswith(
        ".git"
    )


def safe_dest(dest: Path, member: str) -> Path:
    """Resolve an archive member inside dest, rejecting traversal."""
    target = (dest / member).resolve()
    base = dest.resolve()
    if target != base and base not in target.parents:
        raise ValidationError(f"Archive member escapes the target directory: {member}")
    return target


def extract_archive(archive: Path, dest: Path) -> int:
    """Extract .zip/.tar(.gz) safely; returns number of files written."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip") or zipfile.is_zipfile(archive):
        total = 0
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            if len(members) > MAX_MEMBERS:
                raise ValidationError(f"Archive has too many files ({len(members)}).")
            for info in members:
                target = safe_dest(dest, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if info.file_size > MAX_EXTRACTED_BYTES:
                    raise ValidationError(f"Archive member too large: {info.filename}")
                total += info.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise ValidationError("Archive is too large when unpacked.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        return len(members)
    if tarfile.is_tarfile(archive):
        total = 0
        count = 0
        with tarfile.open(archive) as tf:
            members = tf.getmembers()
            if len(members) > MAX_MEMBERS:
                raise ValidationError(f"Archive has too many files ({len(members)}).")
            for member in members:
                target = safe_dest(dest, member.name)
                if member.issym() or member.islnk():
                    continue  # links in uploads are never trusted
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                total += member.size
                if total > MAX_EXTRACTED_BYTES:
                    raise ValidationError("Archive is too large when unpacked.")
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
        return count
    raise ValidationError("Unsupported archive. Upload a .zip, .tar, .tar.gz or .tgz file.")


def find_project_root(base: Path, max_depth: int = 2) -> Path:
    """Locate the directory holding package.json (GitHub zips have one wrapper dir)."""
    if (base / "package.json").is_file():
        return base
    candidates: list[Path] = []
    for root, dirs, files in os.walk(base):
        depth = len(Path(root).relative_to(base).parts)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        if depth >= max_depth:
            dirs[:] = []
        if "package.json" in files:
            candidates.append(Path(root))
    if not candidates:
        raise ValidationError(
            "No package.json found in the upload. Upload the project root "
            "(the folder containing package.json)."
        )
    candidates.sort(key=lambda p: (len(p.parts), str(p)))
    return candidates[0]


def count_files(path: Path, limit: int = 20_000) -> int:
    total = 0
    for _root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        total += len(files)
        if total > limit:
            return limit
    return total


def has_node_modules(path: Path) -> bool:
    return (path / "node_modules").is_dir()


async def clone(url: str, dest: Path, *, branch: str = "", timeout: int = 900) -> Imported:
    """Shallow-clone a repository. Requires git; failure is reported verbatim."""
    if shutil.which("git") is None:
        raise ValidationError("git is not installed on this machine (`sudo apt install git`).")
    if not is_git_url(url):
        raise ValidationError("That does not look like a git URL (https://…, ssh://…, git@…).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and any(dest.iterdir()):
        shutil.rmtree(dest)
    argv = ["git", "clone", "--depth", "1", "--recursive"]
    if branch.strip():
        argv += ["--branch", branch.strip()]
    argv += [url.strip(), str(dest)]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true")
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        raise ValidationError(f"git clone timed out after {timeout}s.") from None
    if process.returncode != 0:
        text = output.decode("utf-8", "replace").strip().splitlines()[-5:]
        raise ValidationError("git clone failed: " + " | ".join(text))
    detail = output.decode("utf-8", "replace").strip().splitlines()
    return Imported(workdir=dest, kind="git", detail=detail[-1] if detail else "")


def link_folder(source: str, dest: Path) -> Imported:
    """Import an existing directory.

    The project is *copied* (symlinked node_modules are resolved) only when the
    caller asks; by default we manage the folder in place so edits, git state
    and the user's own node_modules stay where they are.
    """
    src = Path(source).expanduser()
    if not src.is_dir():
        raise ValidationError(f"{src} is not a directory.")
    if not (src / "package.json").is_file():
        raise ValidationError(f"{src} has no package.json (not the project root).")
    return Imported(workdir=src.resolve(), kind="folder")


def copy_folder(source: str, dest: Path) -> Imported:
    """Copy a project into the workspace (used when the source is read-only)."""
    src = Path(source).expanduser()
    if not src.is_dir():
        raise ValidationError(f"{src} is not a directory.")
    if not (src / "package.json").is_file():
        raise ValidationError(f"{src} has no package.json (not the project root).")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(*IGNORED_DIRS),
        symlinks=False,
        dirs_exist_ok=False,
    )
    return Imported(workdir=dest, kind="folder", detail=f"copied from {src}")


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def git_available() -> bool:
    return shutil.which("git") is not None


def git_sync(workdir: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    """Fast-forward an existing clone (used by the Update button)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true")
    return subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
