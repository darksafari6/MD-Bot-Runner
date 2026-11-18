from __future__ import annotations

import json
from pathlib import Path

import pytest

from apphost import detect


def write_project(root: Path, manifest: dict, files: tuple[str, ...] = ()) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


def test_detects_vite_react_fixture(fixture_vite: Path) -> None:
    plan = detect.analyse(fixture_vite)
    assert plan.framework == "vite"
    assert plan.start_command == "npm run dev"
    assert plan.build_command == "npm run build"
    assert plan.install_command == "npm install"


@pytest.mark.parametrize(
    ("lockfile", "manager", "install"),
    [
        ("package-lock.json", "npm", "npm install"),
        ("pnpm-lock.yaml", "pnpm", "pnpm install"),
        ("yarn.lock", "yarn", "yarn install"),
        ("bun.lockb", "bun", "bun install"),
    ],
)
def test_lockfile_wins(tmp_path: Path, lockfile: str, manager: str, install: str) -> None:
    root = write_project(tmp_path / "p", {"scripts": {"dev": "vite"}}, (lockfile,))
    plan = detect.analyse(root)
    assert plan.package_manager == manager
    assert plan.install_command == install
    assert plan.start_command == f"{'npm' if manager == 'npm' else manager} run dev"


def test_package_manager_field_used_when_no_lockfile(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p", {"packageManager": "pnpm@9.1.0", "scripts": {"dev": "vite"}}
    )
    assert detect.analyse(root).package_manager == "pnpm"


def test_next_uses_dev_server_and_port_3000(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"scripts": {"dev": "next dev", "build": "next build"}, "dependencies": {"next": "14"}},
        ("next.config.js",),
    )
    plan = detect.analyse(root)
    assert plan.framework == "next"
    assert plan.start_command == "npm run dev"
    assert plan.port == 3000


def test_plain_node_has_no_build_step(tmp_path: Path) -> None:
    root = write_project(tmp_path / "p", {"scripts": {"start": "node server.js"}})
    plan = detect.analyse(root)
    assert plan.framework == "node"
    assert plan.start_command == "npm run start"
    assert plan.build_command == ""


def test_port_is_read_from_the_start_script(tmp_path: Path) -> None:
    root = write_project(tmp_path / "p", {"scripts": {"start": "node server.js --port 4321"}})
    assert detect.analyse(root).port == 4321


def test_env_port_pattern(tmp_path: Path) -> None:
    root = write_project(tmp_path / "p", {"scripts": {"start": "PORT=8123 node index.js"}})
    assert detect.analyse(root).port == 8123


def test_missing_package_json_is_a_clear_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(detect.ProjectError) as excinfo:
        detect.analyse(empty)
    assert "package.json" in str(excinfo.value)


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "package.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(detect.ProjectError) as excinfo:
        detect.analyse(root)
    assert "valid JSON" in str(excinfo.value)


def test_no_scripts_is_reported(tmp_path: Path) -> None:
    root = write_project(tmp_path / "p", {"name": "x"})
    with pytest.raises(detect.ProjectError) as excinfo:
        detect.analyse(root)
    assert "dev/start" in str(excinfo.value)


def test_split_command_rejects_unbalanced_quotes() -> None:
    with pytest.raises(detect.ProjectError):
        detect.split_command('npm run dev -- --title "oops')


def test_split_command_keeps_arguments_together() -> None:
    assert detect.split_command("npm run dev -- --host 0.0.0.0") == [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "0.0.0.0",
    ]


def test_express_detected_as_server(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p", {"scripts": {"start": "node s.js"}, "dependencies": {"express": "4"}}
    )
    assert detect.analyse(root).framework == "server"


def test_extract_port_ignores_out_of_range() -> None:
    assert detect.extract_port("serve --port 99999") is None


def test_with_base_for_npm_script() -> None:
    assert detect.with_base("vite", "npm run dev", "/apps/x/") == "npm run dev -- --base=/apps/x/"


def test_with_base_for_direct_binary() -> None:
    assert detect.with_base("vite", "npx vite --host 0.0.0.0", "/apps/x/") == (
        "npx vite --host 0.0.0.0 --base=/apps/x/"
    )


def test_with_base_is_not_doubled() -> None:
    command = "npm run dev -- --base=/custom/"
    assert detect.with_base("vite", command, "/apps/x/") == command


def test_with_base_skips_frameworks_without_the_flag() -> None:
    assert detect.with_base("next", "npm run dev", "/apps/x/") == "npm run dev"
    assert detect.with_base("node", "node server.js", "/apps/x/") == "node server.js"
