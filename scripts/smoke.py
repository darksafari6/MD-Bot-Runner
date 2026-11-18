#!/usr/bin/env python3
"""End-to-end smoke test over real HTTP.

Starts the panel on a scratch data directory, registers a real project, installs
it, starts it, and fetches the app *through* the proxy. Nothing is mocked: the
project is real npm/Vite, the port is real, the page comes from the dev server.

    python3 scripts/smoke.py                     # uses tests/fixtures/vite-react
    python3 scripts/smoke.py /path/to/project    # any project folder

Exit code 0 means: panel serves, app installs, app starts, proxy serves it.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "smoke-token"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - localhost
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


def wait_for(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = request(url)
        if status == 200:
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "fixtures" / "vite-react"
    if not (project / "package.json").is_file():
        print(f"no package.json in {project}")
        return 2

    work = Path(tempfile.mkdtemp(prefix="apphost-smoke-"))
    data_dir = work / "data"
    port = free_port()
    env = dict(os.environ, APPHOST_DATA_DIR=str(data_dir), APPHOST_TOKEN=TOKEN)
    env.pop("APPHOST_AUTH", None)
    base = f"http://127.0.0.1:{port}"

    print(f"==> panel on {base} (data {data_dir})")
    log = open(work / "panel.log", "wb")  # noqa: SIM115 - closed in finally
    server = subprocess.Popen(
        [sys.executable, "-m", "apphost", "serve", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    ok = False
    try:
        if not wait_for(f"{base}/api/health"):
            print("FAIL: panel did not become healthy")
            print((work / "panel.log").read_text()[-3000:])
            return 1
        _, health = request(f"{base}/api/health")
        print(f"    health: {health.strip()}")

        if not (project / "node_modules").is_dir():
            print("==> installing project dependencies (npm install)")
        status, body = request(
            f"{base}/api/apps",
            "POST",
            {"name": "Smoke App", "source": "folder", "path": str(project)},
        )
        if status != 201:
            print(f"FAIL: create returned {status}: {body}")
            return 1
        app = json.loads(body)
        app_id = app["id"]
        print(f"    registered '{app_id}': {app['start_command']} (port {app['port']})")

        status, body = request(f"{base}/api/apps/{app_id}/install", "POST")
        print(f"    install started: {status}")
        for _ in range(240):
            _, state = request(f"{base}/api/apps/{app_id}")
            task = json.loads(state).get("task") or {}
            if not task.get("running"):
                break
            time.sleep(1)
        task = json.loads(state).get("task") or {}
        print(f"    install: ok={task.get('ok')} exit={task.get('exit_code')}")
        if not task.get("ok"):
            _, log = request(f"{base}/api/apps/{app_id}/logs?kind=install&lines=40")
            print(log)
            return 1

        status, body = request(f"{base}/api/apps/{app_id}/start", "POST")
        print(f"    start: {status}")

        page = None
        deadline = time.time() + 120
        while time.time() < deadline:
            status, text = request(f"{base}/apps/{app_id}/")
            if status == 200:
                page = text
                break
            time.sleep(1)
        if page is None:
            _, state = request(f"{base}/api/apps/{app_id}")
            print(f"FAIL: proxy never served the app. state={state}")
            _, log = request(f"{base}/api/apps/{app_id}/logs?lines=40")
            print(log)
            return 1

        print(f"    proxied page: {len(page)} bytes")
        if 'id="root"' not in page:
            print("FAIL: page does not look like the app's index.html")
            print(page[:500])
            return 1
        # Every module URL must resolve through the prefix, or the browser shows
        # a blank page even though the HTML arrived.
        marker = f"/apps/{app_id}/"
        modules = sorted(
            {
                token.split('"')[0].split("'")[0]
                for token in page.replace(marker, "\x00").split("\x00")[1:]
            }
        )
        for module in modules[:6]:
            path = marker + module.lstrip("/").split("?")[0]
            code, _ = request(f"{base}{path}")
            print(f"    module {path:<44} {code}")
            if code != 200:
                print("FAIL: a module referenced by the page does not resolve through the proxy")
                return 1
        ok = True
        print("PASS: real project installed, started, and served through the proxy")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        print(f"==> logs kept in {work}")
        if not ok:
            print((work / "panel.log").read_text()[-2000:])


if __name__ == "__main__":
    raise SystemExit(main())
