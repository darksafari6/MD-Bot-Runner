from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apphost.api import create_app, slugify
from apphost.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    settings = Settings(
        data_dir=tmp_path / "data",
        token="test-token",
        auth_required=True,
        allowed_roots=(str(tmp_path),),
        max_apps=5,
        autostart=False,
    )
    settings.prepare()
    return settings


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


MANIFEST = json.dumps(
    {
        "name": "bot",
        "scripts": {"dev": "vite --host 127.0.0.1", "build": "vite build"},
        "dependencies": {"react": "^18"},
        "devDependencies": {"vite": "^5"},
    }
)


def project_dir(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "package.json").write_text(MANIFEST, encoding="utf-8")
    (root / "vite.config.js").write_text("export default {}", encoding="utf-8")
    return root


# -- health & auth ------------------------------------------------------
def test_health_is_open(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"].startswith("4.")


def test_api_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/apps").status_code == 401
    assert client.get("/api/apps", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_api_accepts_x_api_token(client: TestClient) -> None:
    assert client.get("/api/apps", headers={"X-API-Token": "test-token"}).status_code == 200


def test_dashboard_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Your projects" in response.text


def test_static_assets_are_served(client: TestClient) -> None:
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_doctor_endpoint_reports_node(client: TestClient) -> None:
    body = client.get("/api/doctor").json()
    names = {c["name"] for c in body["checks"]}
    assert "node" in names
    assert "loopback" in names


# -- create -------------------------------------------------------------
def test_create_from_folder_inspects_project(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "WhatsApp Bot", "source": "folder", "path": str(root)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "whatsapp-bot"
    assert body["start_command"] == "npm run dev"
    assert body["build_command"] == "npm run build"
    assert body["package_manager"] == "npm"
    assert body["workdir"] == str(root)
    assert body["port"] > 0


def test_create_rejects_path_outside_allowed_roots(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "nope", "source": "folder", "path": "/etc"},
    )
    assert response.status_code == 403
    assert "allowed roots" in response.json()["detail"]


def test_create_reports_missing_package_json(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "empty", "source": "folder", "path": str(empty)},
    )
    assert response.status_code == 400
    assert "package.json" in response.json()["detail"]


def test_create_rejects_bad_port(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "x", "source": "folder", "path": str(root), "port": "700000"},
    )
    assert response.status_code == 400


def test_create_parses_env_lines(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={
            "name": "env",
            "source": "folder",
            "path": str(root),
            "env": "WA_SESSION=main\nLOG_LEVEL=debug",
        },
    )
    assert response.status_code == 201
    assert response.json()["env"] == {"WA_SESSION": "main", "LOG_LEVEL": "debug"}


def test_create_rejects_bad_env_line(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "env", "source": "folder", "path": str(root), "env": "NOPE"},
    )
    assert response.status_code == 400
    assert "missing '='" in response.json()["detail"]


def test_duplicate_id_conflicts(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    payload = {"name": "dup", "source": "folder", "path": str(root)}
    assert client.post("/api/apps", headers=auth(settings), json=payload).status_code == 201
    assert client.post("/api/apps", headers=auth(settings), json=payload).status_code == 409


def test_app_limit_enforced(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    for index in range(5):
        root = project_dir(tmp_path, f"p{index}")
        response = client.post(
            "/api/apps",
            headers=auth(settings),
            json={
                "name": f"app-{index}",
                "source": "folder",
                "path": str(root),
                "port": 5000 + index,
            },
        )
        assert response.status_code == 201
    root = project_dir(tmp_path, "over")
    response = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "over", "source": "folder", "path": str(root)},
    )
    assert response.status_code == 409
    assert "limit" in response.json()["detail"]


def test_inspect_previews_detection(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    response = client.get("/api/apps/inspect", headers=auth(settings), params={"path": str(root)})
    assert response.status_code == 200
    assert response.json()["start_command"] == "npm run dev"


def test_scan_lists_toolchains(client: TestClient, settings: Settings) -> None:
    body = client.get("/api/apps/scan", headers=auth(settings)).json()
    assert {m["name"] for m in body["packages"]} >= {"npm"}
    assert isinstance(body["git"], bool)


# -- upload -------------------------------------------------------------
def test_upload_zip_with_wrapper_folder(client: TestClient, settings: Settings) -> None:
    data = make_zip(
        {
            "whatsapp-bot-main/package.json": MANIFEST,
            "whatsapp-bot-main/vite.config.js": "export default {}",
            "whatsapp-bot-main/src/main.jsx": "console.log(1)",
        }
    )
    response = client.post(
        "/api/apps/upload",
        headers=auth(settings),
        files={"file": ("bot.zip", data, "application/zip")},
        data={"name": "Uploaded Bot"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "uploaded-bot"
    assert body["source_kind"] == "upload"
    assert Path(body["workdir"], "package.json").is_file()


def test_upload_without_package_json_is_rejected(client: TestClient, settings: Settings) -> None:
    data = make_zip({"readme.md": "hello"})
    response = client.post(
        "/api/apps/upload",
        headers=auth(settings),
        files={"file": ("bad.zip", data, "application/zip")},
    )
    assert response.status_code == 400
    assert "package.json" in response.json()["detail"]


def test_upload_rejects_path_traversal(client: TestClient, settings: Settings) -> None:
    data = make_zip({"../../evil.txt": "boom", "package.json": MANIFEST})
    response = client.post(
        "/api/apps/upload",
        headers=auth(settings),
        files={"file": ("evil.zip", data, "application/zip")},
    )
    assert response.status_code == 400
    assert "escapes" in response.json()["detail"]
    assert not (settings.data_dir.parent / "evil.txt").exists()


# -- read / update / delete --------------------------------------------
def test_get_list_patch(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "p", "source": "folder", "path": str(root)},
    ).json()
    app_id = created["id"]

    listed = client.get("/api/apps", headers=auth(settings)).json()["apps"]
    assert [a["id"] for a in listed] == [app_id]

    patched = client.patch(
        f"/api/apps/{app_id}",
        headers=auth(settings),
        json={"name": "renamed", "start_command": "node server.js", "autostart": True},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "renamed"
    assert patched.json()["start_command"] == "node server.js"
    assert patched.json()["autostart"] is True


def test_patch_rejects_malformed_command(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "p", "source": "folder", "path": str(root)},
    ).json()
    response = client.patch(
        f"/api/apps/{created['id']}",
        headers=auth(settings),
        json={"start_command": 'node "unclosed'},
    )
    assert response.status_code == 400


def test_patch_unknown_app_404(client: TestClient, settings: Settings) -> None:
    assert (
        client.patch("/api/apps/ghost", headers=auth(settings), json={"name": "x"}).status_code
        == 404
    )


def test_delete_keeps_folder_for_folder_sources(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "p", "source": "folder", "path": str(root)},
    ).json()
    response = client.delete(f"/api/apps/{created['id']}", headers=auth(settings))
    assert response.status_code == 200
    assert response.json()["files_removed"] is False
    assert root.is_dir()


def test_delete_upload_removes_workspace_copy(client: TestClient, settings: Settings) -> None:
    data = make_zip({"package.json": MANIFEST})
    created = client.post(
        "/api/apps/upload",
        headers=auth(settings),
        files={"file": ("bot.zip", data, "application/zip")},
        data={"name": "Uploaded"},
    ).json()
    workdir = Path(created["workdir"])
    assert workdir.is_dir()
    response = client.delete(
        f"/api/apps/{created['id']}", headers=auth(settings), params={"delete_files": True}
    )
    assert response.status_code == 200
    assert response.json()["files_removed"] is True
    assert not workdir.exists()


# -- lifecycle through HTTP --------------------------------------------
def test_start_without_node_after_install_fails_honestly(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    """A project with an unrunnable start command must produce 400, not a fake 'running'."""
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={
            "name": "broken",
            "source": "folder",
            "path": str(root),
            "start_command": "no-such-binary-here",
        },
    ).json()
    response = client.post(f"/api/apps/{created['id']}/start", headers=auth(settings))
    assert response.status_code == 400
    assert "not installed" in response.json()["detail"]


def test_stop_is_safe_when_not_running(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "p", "source": "folder", "path": str(root)},
    ).json()
    response = client.post(f"/api/apps/{created['id']}/stop", headers=auth(settings))
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


def test_logs_endpoint(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "p", "source": "folder", "path": str(root)},
    ).json()
    body = client.get(f"/api/apps/{created['id']}/logs", headers=auth(settings)).text
    assert "no output yet" in body


def test_start_actually_serves_the_app(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    root = project_dir(tmp_path)
    (root / "server.js").write_text(
        'require("http").createServer((q,s)=>s.end("hello-from-app")).listen(process.env.PORT,"127.0.0.1")',
        encoding="utf-8",
    )
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={
            "name": "live",
            "source": "folder",
            "path": str(root),
            "start_command": "node server.js",
            "port": 5311,
        },
    ).json()
    assert created["port"] == 5311
    response = client.post(f"/api/apps/{created['id']}/start", headers=auth(settings))
    assert response.status_code == 200, response.text

    import time

    deadline = time.time() + 25
    body = None
    while time.time() < deadline:
        probe = client.get(f"/apps/{created['id']}/")
        if probe.status_code == 200:
            body = probe.text
            break
        time.sleep(0.4)
    assert body is not None, "proxy never served the app"
    assert "hello-from-app" in body

    stopped = client.post(f"/api/apps/{created['id']}/stop", headers=auth(settings))
    assert stopped.status_code == 200


# -- HTMX / forms -------------------------------------------------------
def test_ui_create_redirects_to_app(client: TestClient, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/ui/apps",
        data={"name": "from-form", "source": "folder", "path": str(root)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/apps/from-form")


def test_register_form_page(client: TestClient) -> None:
    response = client.get("/register")
    assert response.status_code == 200
    assert "Where is the code?" in response.text


def test_register_post_redirects(client: TestClient, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    response = client.post(
        "/register",
        data={"name": "reg", "source": "folder", "path": str(root)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_ui_action_returns_card(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "card", "source": "folder", "path": str(root)},
    ).json()
    response = client.post(f"/ui/apps/{created['id']}/stop")
    assert response.status_code == 200
    assert "card" in response.text
    assert "Start" in response.text


def test_ui_config_saves(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "cfg", "source": "folder", "path": str(root)},
    ).json()
    response = client.post(
        f"/ui/apps/{created['id']}/config",
        data={
            "name": "cfg2",
            "start_command": "npm run dev -- --host 127.0.0.1",
            "install_command": "npm ci",
            "build_command": "",
            "port": "6200",
            "env": "A=1",
            "autostart": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    stored = client.get(f"/api/apps/{created['id']}", headers=auth(settings)).json()
    assert stored["name"] == "cfg2"
    assert stored["port"] == 6200
    assert stored["env"] == {"A": "1"}
    assert stored["autostart"] is True


def test_app_page_renders_tabs(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "tabs", "source": "folder", "path": str(root)},
    ).json()
    for tab in ("overview", "run", "config", "logs"):
        response = client.get(f"/apps/{created['id']}?tab={tab}")
        assert response.status_code == 200
        assert "tabs" in response.text


def test_unknown_app_page_404(client: TestClient) -> None:
    assert client.get("/apps/ghost").status_code == 404


def test_partial_apps_lists_cards(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "partial", "source": "folder", "path": str(root)},
    )
    response = client.get("/partials/apps")
    assert response.status_code == 200
    assert "partial" in response.text


def test_proxy_unknown_app_404(client: TestClient) -> None:
    assert client.get("/apps/ghost/anything").status_code == 404


def test_slugify() -> None:
    assert slugify("My WhatsApp Bot!") == "my-whatsapp-bot"
    assert slugify("  ---  ") == "app"
    assert len(slugify("a" * 60)) <= 32


# -- proxy base: the fix for Vite module URLs --------------------------
def test_vite_app_is_started_with_proxy_base(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "based", "source": "folder", "path": str(root)},
    ).json()
    assert created["framework"] == "vite"
    from apphost.db import Database

    row = Database(settings.database_path).get_app(created["id"])
    assert row is not None
    from apphost.runner import Runner

    assert Runner.launch_command(row).endswith(f"--base=/apps/{created['id']}/")


def test_plain_node_app_gets_no_base_flag(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "nodeapp"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8"
    )
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "plain", "source": "folder", "path": str(root)},
    ).json()
    from apphost.db import Database
    from apphost.runner import Runner

    row = Database(settings.database_path).get_app(created["id"])
    assert row is not None
    assert Runner.launch_command(row) == "npm run start"


def test_proxy_base_can_be_disabled(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    root = project_dir(tmp_path)
    created = client.post(
        "/api/apps",
        headers=auth(settings),
        json={"name": "nobase", "source": "folder", "path": str(root), "proxy_base": False},
    ).json()
    assert created["proxy_base"] is False


# -- websocket proxy (Vite HMR relies on it) ---------------------------
def test_websocket_is_tunnelled_over_real_uvicorn(settings: Settings, tmp_path: Path) -> None:
    """Open a websocket on /apps/<id>/ against a real server and echo through it.

    Starlette's TestClient cannot send ``Upgrade: websocket``, so this test runs
    uvicorn for real -- the same stack the panel uses in production.
    """
    pytest.importorskip("websockets")
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    import websockets
    from websockets.sync.client import connect

    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    echo_port = free_port()
    ready = threading.Event()

    def echo_server() -> None:
        async def handler(ws) -> None:
            message = await ws.recv()
            if isinstance(message, bytes):
                await ws.send(b"echo:" + message)
            else:
                await ws.send("echo:" + message)

        async def main() -> None:
            async with websockets.serve(handler, "127.0.0.1", echo_port):
                ready.set()
                await asyncio.sleep(120)

        asyncio.run(main())

    threading.Thread(target=echo_server, daemon=True).start()
    assert ready.wait(10)

    app = create_app(settings)
    panel_port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=panel_port, log_level="warning", lifespan="on")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"

    from apphost.runner import Runtime

    app.state.runner.apps["wsapp"] = Runtime(app_id="wsapp", port=echo_port)
    app.state.db.add_app(
        __import__("apphost.db", fromlist=["App"]).App(
            id="wsapp",
            name="ws",
            source_kind="folder",
            workdir=str(tmp_path),
            start_command="node s.js",
            port=echo_port,
        )
    )

    try:
        with connect(f"ws://127.0.0.1:{panel_port}/apps/wsapp/", open_timeout=10) as ws:
            ws.send("hello-hmr")
            assert ws.recv(timeout=10) == "echo:hello-hmr"
    finally:
        server.should_exit = True
