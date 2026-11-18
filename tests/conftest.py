from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixture_node() -> Path:
    """A real, runnable Node project."""
    return FIXTURES / "plain-node"


@pytest.fixture()
def fixture_vite() -> Path:
    """A Vite + React project (not installed)."""
    return FIXTURES / "vite-react"


@pytest.fixture()
def copied_node(tmp_path: Path, fixture_node: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture_node, dest)
    return dest


@pytest.fixture()
def node_available() -> bool:
    return shutil.which("node") is not None
