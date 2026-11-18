from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from apphost import sources
from apphost.errors import ValidationError


def zip_bytes(files: dict[str, str]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer  # type: ignore[return-value]


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "project.zip"
    path.write_bytes(
        zip_bytes({"bot/package.json": "{}", "bot/src/main.js": "1"}).getvalue()  # type: ignore[union-attr]
    )
    return path


def test_extract_zip(archive: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    count = sources.extract_archive(archive, dest)
    assert count == 2
    assert (dest / "bot" / "package.json").is_file()


def test_find_project_root_skips_wrapper(archive: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    sources.extract_archive(archive, dest)
    assert sources.find_project_root(dest) == dest / "bot"


def test_find_project_root_prefers_top_level(tmp_path: Path) -> None:
    root = tmp_path / "flat"
    root.mkdir()
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "package.json").write_text("{}", encoding="utf-8")
    assert sources.find_project_root(root) == root


def test_zip_traversal_blocked(tmp_path: Path) -> None:
    path = tmp_path / "evil.zip"
    path.write_bytes(zip_bytes({"../escape.txt": "x"}).getvalue())  # type: ignore[union-attr]
    with pytest.raises(ValidationError):
        sources.extract_archive(path, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_tar_gz_extraction(tmp_path: Path) -> None:
    source = tmp_path / "tar"
    source.mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "p.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source / "package.json", arcname="project/package.json")
    dest = tmp_path / "out"
    assert sources.extract_archive(archive, dest) == 1
    assert (dest / "project" / "package.json").is_file()


def test_tar_traversal_blocked(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar"
    payload = b"boom"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValidationError):
        sources.extract_archive(archive, tmp_path / "out")


def test_tar_symlinks_are_skipped(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("escape")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
        payload = b"{}"
        good = tarfile.TarInfo("package.json")
        good.size = len(payload)
        tar.addfile(good, io.BytesIO(payload))
    dest = tmp_path / "out"
    sources.extract_archive(archive, dest)
    assert not (dest / "escape").exists()
    assert (dest / "package.json").is_file()


def test_unsupported_archive(tmp_path: Path) -> None:
    weird = tmp_path / "file.rar"
    weird.write_bytes(b"not an archive")
    with pytest.raises(ValidationError):
        sources.extract_archive(weird, tmp_path / "out")


def test_link_folder_requires_package_json(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValidationError):
        sources.link_folder(str(empty), tmp_path / "dest")


def test_link_folder_keeps_original_path(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "package.json").write_text("{}", encoding="utf-8")
    imported = sources.link_folder(str(project), tmp_path / "unused")
    assert imported.workdir == project.resolve()


def test_git_url_detection() -> None:
    assert sources.is_git_url("https://github.com/u/r.git")
    assert sources.is_git_url("git@github.com:u/r.git")
    assert not sources.is_git_url("/home/me/project")
    assert not sources.is_git_url("C:\\projects\\bot")


async def test_clone_rejects_non_url(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        await sources.clone("/not/a/url", tmp_path / "dest")


def test_copy_folder_skips_node_modules(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "x.js").write_text("1", encoding="utf-8")
    (project / "package.json").write_text("{}", encoding="utf-8")
    imported = sources.copy_folder(str(project), tmp_path / "copy")
    assert (imported.workdir / "package.json").is_file()
    assert not (imported.workdir / "node_modules").exists()
