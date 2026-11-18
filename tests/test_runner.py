"""Runner tests use real Node processes and real TCP ports.

Nothing here is stubbed: if the host says an app is running, a socket in the
test is talking to a Node process.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import urllib.request
from pathlib import Path

import pytest

from apphost.db import App
from apphost.runner import Proxy, Runner, free_port, port_open, rewrite_body

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def make_app(path: Path, port: int, command: str = "npm run start", app_id: str = "fixture") -> App:
    return App(
        id=app_id,
        name="Fixture",
        source_kind="folder",
        workdir=str(path),
        package_manager="npm",
        install_command="",
        start_command=command,
        port=port,
    )


def http_get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback only
        return response.status, response.read().decode("utf-8", "replace")


async def wait_until(predicate, timeout: float = 25.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.2)
    return False


@pytest.fixture()
async def runner(tmp_path: Path):
    instance = Runner(tmp_path / "logs", log_lines=200)
    yield instance
    await instance.stop_all()


async def test_start_writes_log_and_serves_http(runner: Runner, copied_node: Path) -> None:
    port = free_port(4700)
    app = make_app(copied_node, port, command="node server.js")
    await runner.start(app)
    assert await wait_until(lambda: port_open(port))
    try:
        status, body = http_get(f"http://127.0.0.1:{port}/")
        assert status == 200
        assert "fixture-ok" in body
        assert runner.status("fixture") == "running"
        state = runner.state("fixture")
        assert state["port"] == port
        assert state["pid"]
        assert "fixture listening" in runner.app_log("fixture")
    finally:
        await runner.stop("fixture")
    assert runner.status("fixture") in {"stopped", "crashed"}
    await wait_until(lambda: not port_open(port))


async def test_stop_terminates_the_whole_tree(runner: Runner, copied_node: Path) -> None:
    port = free_port(4800)
    await runner.start(make_app(copied_node, port, command="node server.js"))
    assert await wait_until(lambda: port_open(port))
    await runner.stop("fixture")
    assert await wait_until(lambda: not port_open(port))


async def test_start_twice_is_idempotent(runner: Runner, copied_node: Path) -> None:
    port = free_port(4810)
    app = make_app(copied_node, port, command="node server.js")
    await runner.start(app)
    assert await wait_until(lambda: port_open(port))
    first_pid = runner.state("fixture")["pid"]
    await runner.start(app)
    assert runner.state("fixture")["pid"] == first_pid
    await runner.stop("fixture")


async def test_missing_binary_is_a_validation_error(runner: Runner, copied_node: Path) -> None:
    from apphost.errors import ValidationError

    app = make_app(copied_node, 4820, command="definitely-not-a-real-binary --nope")
    with pytest.raises(ValidationError) as excinfo:
        await runner.start(app)
    assert "not installed" in str(excinfo.value)


async def test_missing_directory_is_reported(runner: Runner, tmp_path: Path) -> None:
    from apphost.errors import ValidationError

    app = make_app(tmp_path / "gone", 4830, command="node server.js")
    with pytest.raises(ValidationError) as excinfo:
        await runner.start(app)
    assert "does not exist" in str(excinfo.value)


async def test_port_collision_moves_to_a_free_port(runner: Runner, copied_node: Path) -> None:
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    taken = blocker.getsockname()[1]
    try:
        app = make_app(copied_node, taken, command="node server.js")
        await runner.start(app)
        chosen = runner.state("fixture")["port"]
        assert chosen != taken
        assert await wait_until(lambda: port_open(int(chosen)))
        await runner.stop("fixture")
    finally:
        blocker.close()


async def test_crash_is_reported_with_exit_code(runner: Runner, tmp_path: Path) -> None:
    project = tmp_path / "crash"
    project.mkdir()
    (project / "crash.js").write_text("process.exit(3);", encoding="utf-8")
    app = make_app(project, 4840, command="node crash.js")
    await runner.start(app)
    await runner.wait_ready("fixture", timeout=15)
    state = runner.state("fixture")
    assert state["status"] == "crashed"
    assert state["last_exit"] == 3
    assert "exited with code 3" in str(state["last_error"])


async def test_install_task_runs_and_reports(runner: Runner, tmp_path: Path) -> None:
    project = tmp_path / "task"
    project.mkdir()
    (project / "echo.js").write_text("console.log('installed');", encoding="utf-8")
    app = make_app(project, 4850, command="node echo.js")
    app.install_command = "node -e \"console.log('install-ok')\""
    task = await runner.run_task(app, "install", timeout=60)
    deadline = asyncio.get_running_loop().time() + 30
    while task.running and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
    assert task.running is False
    assert task.ok is True
    assert task.exit_code == 0
    log = runner.tail(task.log_path)
    assert "install-ok" in log


async def test_failed_task_reports_exit_code(runner: Runner, tmp_path: Path) -> None:
    project = tmp_path / "fail"
    project.mkdir()
    app = make_app(project, 4860, command="node -v")
    app.install_command = "node -e 'process.exit(7)'"
    task = await runner.run_task(app, "install", timeout=60)
    deadline = asyncio.get_running_loop().time() + 30
    while task.running and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
    assert task.ok is False
    assert task.exit_code == 7
    assert "exit code 7" in task.error


async def test_missing_command_rejected(runner: Runner, tmp_path: Path) -> None:
    from apphost.errors import ValidationError

    project = tmp_path / "nocmd"
    project.mkdir()
    app = make_app(project, 4870, command="node -v")
    app.install_command = ""
    with pytest.raises(ValidationError):
        await runner.run_task(app, "install")


async def test_concurrent_task_is_rejected(runner: Runner, tmp_path: Path) -> None:
    from apphost.errors import ConflictError

    project = tmp_path / "slow"
    project.mkdir()
    app = make_app(project, 4880, command="node -v")
    app.install_command = "node -e \"setTimeout(()=>console.log('slow'),1500)\""
    task = await runner.run_task(app, "install", timeout=60)
    with pytest.raises(ConflictError):
        await runner.run_task(app, "install", timeout=60)
    deadline = asyncio.get_running_loop().time() + 30
    while task.running and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)


async def test_log_rotation_keeps_tail(runner: Runner, tmp_path: Path) -> None:
    project = tmp_path / "log"
    project.mkdir()
    app = make_app(project, 4890, command="node -v")
    app.install_command = "node -e \"for(let i=0;i<300;i++) console.log('line-'+i)\""
    task = await runner.run_task(app, "install", timeout=60)
    deadline = asyncio.get_running_loop().time() + 30
    while task.running and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
    tail = runner.tail(task.log_path, lines=5)
    assert "line-299" in tail
    assert "line-1" not in tail.splitlines()


async def test_proxy_serves_app_and_rewrites_absolute_paths(
    runner: Runner, copied_node: Path
) -> None:
    port = free_port(4900)
    await runner.start(make_app(copied_node, port, command="node server.js"))
    assert await wait_until(lambda: port_open(port))
    proxy = Proxy(runner)
    try:
        status, headers, body = await proxy.stream(
            "fixture", "GET", "/", {"accept": "text/html"}, None
        )
        assert status == 200
        assert b"fixture-ok" in body
        assert b'href="/apps/fixture/style.css"' in body
        assert headers["content-type"].startswith("text/html")

        status, _, body = await proxy.stream("fixture", "GET", "/api/ping", {}, None)
        assert status == 200
        assert b'"pong":true' in body
    finally:
        await proxy.aclose()
        await runner.stop("fixture")


async def test_proxy_reports_connection_failure(runner: Runner, copied_node: Path) -> None:
    app = make_app(copied_node, free_port(4910), command="node server.js")
    runtime = runner.runtime(app.id)
    runtime.port = 4999  # nothing listening
    proxy = Proxy(runner)
    try:
        with pytest.raises(ConnectionError):
            await proxy.stream("fixture", "GET", "/", {}, None)
    finally:
        await proxy.aclose()


def test_rewrite_body_leaves_protocol_relative_urls() -> None:
    body = b'<a href="//cdn.example/x.js">x</a><img src="/a.png">'
    out = rewrite_body(body, "/apps/demo")
    assert b"//cdn.example/x.js" in out
    assert b'src="/apps/demo/a.png"' in out


def test_free_port_skips_busy_port() -> None:
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    taken = blocker.getsockname()[1]
    try:
        assert free_port(taken) != taken
    finally:
        blocker.close()


async def test_host_follows_port_the_app_actually_binds(runner: Runner, tmp_path: Path) -> None:
    """Many dev servers ignore PORT (Vite) -- the host must find the real port."""
    project = tmp_path / "fixed"
    project.mkdir()
    (project / "server.js").write_text(
        'require("http").createServer((q,s)=>s.end("fixed-port-ok")).listen(4788,"127.0.0.1");',
        encoding="utf-8",
    )
    app = make_app(project, 4799, command="node server.js")  # deliberately wrong
    await runner.start(app)
    status = await runner.wait_ready(app.id, timeout=40)
    assert status == "running"
    assert runner.state(app.id)["port"] == 4788
    assert "ignored the requested port" in runner.app_log(app.id)
    try:
        code, body = http_get("http://127.0.0.1:4788/")
        assert code == 200 and "fixed-port-ok" in body
    finally:
        await runner.stop(app.id)


async def test_wait_ready_reports_timeout_not_running(runner: Runner, tmp_path: Path) -> None:
    project = tmp_path / "idle"
    project.mkdir()
    (project / "idle.js").write_text("setTimeout(()=>{}, 60000);", encoding="utf-8")
    app = make_app(project, 4796, command="node idle.js")
    await runner.start(app)
    try:
        status = await runner.wait_ready(app.id, timeout=3)
        assert status == "starting"
        assert "did not open a port" in runner.state(app.id)["last_error"]
    finally:
        await runner.stop(app.id)


async def test_validate_catches_missing_binary_without_spawning(copied_node: Path) -> None:
    from apphost.errors import ValidationError

    app = make_app(copied_node, 4795, command="ghost-binary")
    with pytest.raises(ValidationError):
        Runner.validate(app)


def test_rewrite_body_is_idempotent() -> None:
    body = b'<script src="/apps/demo/src/main.jsx"></script><a href="/apps/demo/">x</a>'
    assert rewrite_body(body, "/apps/demo") == body


def test_rewrite_body_prefixes_vite_client() -> None:
    out = rewrite_body(b'<script type="module" src="/@vite/client"></script>', "/apps/demo")
    assert b'src="/apps/demo/@vite/client"' in out
