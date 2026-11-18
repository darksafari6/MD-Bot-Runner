"""Run, stop and proxy managed applications.

Two moving parts:

* ``Runner`` owns processes. It starts them in their own session so a whole
  process tree (npm -> node -> esbuild) can be stopped, writes output to a
  per-app log file, and tracks state transitions.
* ``Proxy`` reverse-proxies ``/apps/<id>/`` to the app's own port so the
  panel has one origin. App sub-resources are rewritten back into that prefix
  so dev servers that emit absolute paths still work.

A process is only reported ``running`` when its port actually accepts
connections -- the host never claims a running app it cannot reach.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
import socket
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .detect import base_supported, split_command, with_base
from .errors import ConflictError, NotFoundError, ValidationError

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}

# How long a stopped process may take to die before SIGKILL.
STOP_GRACE = 6.0


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    """True when something is listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def free_port(preferred: int, span: int = 60) -> int:
    """Prefer the project's own port; otherwise find a free one nearby."""
    if 1 <= preferred <= 65535 and not port_open(preferred, timeout=0.2):
        return preferred
    for offset in range(1, span):
        candidate = preferred + offset
        if candidate <= 65535 and not port_open(candidate, timeout=0.15):
            return candidate
    return preferred


def _listen_inodes(port: int) -> set[str]:
    """Inodes of sockets listening on `port`, from /proc/net/tcp{,6}."""
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            try:
                local_port = int(fields[1].split(":")[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port and fields[3] == "0A":  # 0A = LISTEN
                inodes.add(fields[9])
    return inodes


def _socket_inodes_of(pid: int) -> set[str]:
    fd_dir = Path(f"/proc/{pid}/fd")
    found: set[str] = set()
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return found
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            found.add(target[8:-1])
    return found


def listening_ports_in_tree(pid: int, max_pids: int = 200) -> list[int]:
    """Ports this process tree is listening on, discovered via /proc.

    Used when a dev server ignores the PORT env var (Vite does and binds its own
    configured port). Returns [] when /proc is unavailable.
    """
    pids = [pid]
    try:
        for child in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
            pids.append(int(child))
    except (OSError, ValueError):
        pass
    # Include the whole tree, one level beyond direct children (npm -> sh -> node).
    for child in list(pids):
        try:
            for grandchild in Path(f"/proc/{child}/task/{child}/children").read_text().split():
                child_pid = int(grandchild)
                if child_pid not in pids:
                    pids.append(child_pid)
        except (OSError, ValueError):
            continue
    inodes: set[str] = set()
    for each in pids[:max_pids]:
        inodes |= _socket_inodes_of(each)
    if not inodes:
        return []
    ports: set[int] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A" or fields[9] not in inodes:
                continue
            try:
                port = int(fields[1].split(":")[1], 16)
            except (IndexError, ValueError):
                continue
            if port:
                ports.add(port)
    return sorted(ports)


def kill_tree(pid: int, sig: int = signal.SIGTERM) -> None:
    """Signal the process group of a child we started with start_new_session."""
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, sig)


@dataclass(slots=True)
class Runtime:
    """Live state for one app (never persisted; the DB holds configuration)."""

    app_id: str
    process: asyncio.subprocess.Process | None = None
    port: int | None = None
    # Set when the app was launched with a proxy base (/apps/<id>): every
    # upstream request must then carry that prefix.
    base_path: str = ""
    log_path: Path | None = None
    log_handle: object | None = None
    started_at: float | None = None
    last_error: str = ""
    last_exit: int | None = None

    @property
    def pid(self) -> int | None:
        if self.process is None:
            return None
        return self.process.pid if self.process.returncode is None else None


@dataclass
class TaskState:
    """Progress of an install/build job for one app."""

    app_id: str
    kind: str
    running: bool = False
    ok: bool = False
    exit_code: int | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    log_path: Path | None = None
    command: str = ""
    error: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "app_id": self.app_id,
            "kind": self.kind,
            "running": self.running,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_path": str(self.log_path) if self.log_path else "",
            "command": self.command,
            "error": self.error,
        }


class Runner:
    """Owns managed child processes and their logs."""

    def __init__(self, log_dir: Path, log_lines: int = 500) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_lines = log_lines
        self.apps: dict[str, Runtime] = {}
        self.tasks: dict[str, TaskState] = {}
        self._listeners: list = []

    # -- listeners ----------------------------------------------------
    def subscribe(self, callback) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    async def _emit(self, app_id: str, event: str) -> None:
        for callback in list(self._listeners):
            try:
                result = callback(app_id, event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - listener isolation
                pass

    # -- paths --------------------------------------------------------
    def log_path(self, app_id: str, kind: str = "app") -> Path:
        return self.log_dir / f"{app_id}.{kind}.log"

    def runtime(self, app_id: str) -> Runtime:
        return self.apps.setdefault(app_id, Runtime(app_id=app_id))

    @staticmethod
    def _env_for(app) -> dict[str, str]:
        env = dict(os.environ)
        # Keep the panel's own configuration out of the child.
        for key in ("APPHOST_TOKEN", "APPHOST_ROOTS"):
            env.pop(key, None)
        env.update({str(k): str(v) for k, v in (app.env or {}).items()})
        if app.port:
            # Every framework wants the port differently; set them all so the
            # app binds where the host expects it.
            env.setdefault("PORT", str(app.port))
            env.setdefault("VITE_PORT", str(app.port))
            env.setdefault("APP_PORT", str(app.port))
        env.setdefault("BROWSER", "none")  # never try to open a browser
        env.setdefault("CI", "1")  # keep Vite/CRA non-interactive
        env.setdefault("NO_COLOR", "1")
        return env

    # -- logs ---------------------------------------------------------
    def tail(self, path: Path | None, lines: int | None = None) -> str:
        if not path or not Path(path).exists():
            return ""
        count = lines or self.log_lines
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                block = min(size, max(8192, count * 400))
                handle.seek(size - block)
                data = handle.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(data.splitlines()[-count:])

    def app_log(self, app_id: str) -> str:
        return self.tail(self.log_path(app_id))

    def clear_log(self, app_id: str) -> None:
        for kind in ("app", "install", "build"):
            path = self.log_path(app_id, kind)
            if path.exists():
                path.unlink()

    # -- state --------------------------------------------------------
    def status(self, app_id: str) -> str:
        runtime = self.apps.get(app_id)
        task = self.tasks.get(app_id)
        if runtime and runtime.process is not None and runtime.process.returncode is None:
            if runtime.port and port_open(runtime.port):
                return "running"
            return "starting"
        if runtime and runtime.process is not None:
            # exited on its own
            return "crashed" if runtime.process.returncode not in (0, -15, None) else "stopped"
        if task and task.running:
            return f"{task.kind}ing"
        return "stopped"

    def state(self, app_id: str) -> dict[str, object]:
        runtime = self.apps.get(app_id)
        task = self.tasks.get(app_id)
        status = self.status(app_id)
        return {
            "id": app_id,
            "status": status,
            "pid": runtime.pid if runtime else None,
            "port": runtime.port if runtime else None,
            "started_at": runtime.started_at if runtime else None,
            "uptime": (
                round(time.time() - runtime.started_at)
                if runtime and runtime.started_at and status in {"running", "starting"}
                else None
            ),
            "last_error": runtime.last_error if runtime else "",
            "last_exit": runtime.last_exit if runtime else None,
            "log_path": str(self.log_path(app_id)) if runtime else "",
            "task": task.to_json() if task else None,
        }

    def is_managed_port(self, port: int | None) -> bool:
        if not port:
            return False
        return any(rt.port == port for rt in self.apps.values())

    # -- validation ---------------------------------------------------
    @staticmethod
    def launch_command(app) -> str:
        """The command actually executed: start_command plus the proxy base."""
        if getattr(app, "proxy_base", True) and base_supported(getattr(app, "framework", "")):
            return with_base(app.framework, app.start_command, f"/apps/{app.id}/")
        return app.start_command

    @staticmethod
    def validate(app) -> None:
        """Fail fast, before any task is queued, if this app cannot start."""
        workdir = Path(app.workdir)
        if not workdir.is_dir():
            raise ValidationError(f"Project directory does not exist: {workdir}")
        if not app.start_command.strip():
            raise ValidationError("No start command configured for this app.")
        argv = split_command(Runner.launch_command(app))
        if shutil.which(argv[0]) is None:
            raise ValidationError(
                f"`{argv[0]}` is not installed on this machine. "
                "Install Node.js (`sudo apt install nodejs npm`) and try again."
            )

    def _prepare(
        self, app, *, override_port: int | None = None
    ) -> tuple[list[str], int, dict[str, str], Path]:
        workdir = Path(app.workdir)
        if not workdir.is_dir():
            raise ValidationError(f"Project directory does not exist: {workdir}")
        if not app.start_command.strip():
            raise ValidationError("No start command configured for this app.")
        argv = split_command(Runner.launch_command(app))
        if shutil.which(argv[0]) is None:
            raise ValidationError(
                f"`{argv[0]}` is not installed on this machine. "
                "Install Node.js (`sudo apt install nodejs npm`) and try again."
            )
        port = override_port or app.port or 0
        if not port:
            raise ValidationError("No port configured for this app.")
        if port_open(port) and not self.is_managed_port(port):
            # Something else owns the port: move rather than fight it.
            port = free_port(port)
        return argv, port, self._env_for(app), workdir

    # -- lifecycle ----------------------------------------------------
    async def start(self, app, *, port: int | None = None) -> dict[str, object]:
        runtime = self.runtime(app.id)
        if runtime.process is not None and runtime.process.returncode is None:
            return self.state(app.id)
        argv, chosen_port, env, workdir = self._prepare(app, override_port=port)
        env["PORT"] = str(chosen_port)

        log_path = self.log_path(app.id)
        handle = open(log_path, "ab", buffering=0)  # noqa: SIM115
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"\n=== start {stamp} · {app.start_command} · port {chosen_port}"
            + (" · base /apps/" + app.id + "/" if base_supported(app.framework) else "")
            + "\n"
        )
        handle.write(header.encode())

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(workdir),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=handle,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            handle.close()
            raise ValidationError(f"Cannot run `{argv[0]}`: {exc}") from exc
        except OSError as exc:
            handle.close()
            raise ValidationError(f"Failed to start {app.name}: {exc}") from exc

        runtime.process = process
        runtime.port = chosen_port
        runtime.base_path = (
            f"/apps/{app.id}" if base_supported(app.framework) and app.proxy_base else ""
        )
        runtime.log_path = log_path
        runtime.log_handle = handle
        runtime.started_at = time.time()
        runtime.last_error = ""
        runtime.last_exit = None
        await self._emit(app.id, "started")
        return self.state(app.id)

    async def wait_ready(self, app_id: str, timeout: float | None = None) -> str:
        """Poll until the port answers; returns the final status."""
        runtime = self.apps.get(app_id)
        if runtime is None:
            return "stopped"
        deadline = time.time() + (timeout or 120)
        while time.time() < deadline:
            process = runtime.process
            if process is None:
                return "stopped"
            if process.returncode is not None:
                runtime.last_exit = process.returncode
                if runtime.last_exit not in (0, -int(signal.SIGTERM)):
                    runtime.last_error = f"Process exited with code {runtime.last_exit}. See logs."
                return self.status(app_id)
            if runtime.port and port_open(runtime.port):
                return "running"
            discovered = listening_ports_in_tree(process.pid)
            if discovered:
                actual = discovered[0]
                if actual != runtime.port:
                    log_note = (
                        f"\n[host] app ignored the requested port and bound {actual}; "
                        "following it.\n"
                    )
                    target = runtime.log_path or self.log_path(app_id)
                    with contextlib.suppress(OSError), open(target, "a") as handle:
                        handle.write(log_note)
                    runtime.port = actual
                    await self._emit(app_id, "port")
                    return "running"
            await asyncio.sleep(0.4)
        runtime.last_error = (
            f"App did not open a port within {int(timeout or 120)}s. See logs for the reason."
        )
        return self.status(app_id)

    async def stop(self, app_id: str) -> dict[str, object]:
        runtime = self.apps.get(app_id)
        if runtime is None or runtime.process is None:
            return self.state(app_id)
        process = runtime.process
        if process.returncode is None:
            kill_tree(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=STOP_GRACE)
            except asyncio.TimeoutError:
                kill_tree(process.pid, signal.SIGKILL)
                try:
                    await asyncio.wait_for(process.wait(), timeout=STOP_GRACE)
                except asyncio.TimeoutError:  # pragma: no cover
                    runtime.last_error = "Process did not exit after SIGKILL."
        runtime.last_exit = process.returncode
        if runtime.log_handle is not None:
            with contextlib.suppress(OSError):
                runtime.log_handle.close()
        runtime.log_handle = None
        runtime.process = None
        runtime.started_at = None
        await self._emit(app_id, "stopped")
        return self.state(app_id)

    async def restart(self, app, *, port: int | None = None) -> dict[str, object]:
        await self.stop(app.id)
        return await self.start(app, port=port)

    async def stop_all(self) -> None:
        for app_id in list(self.apps):
            with contextlib.suppress(Exception):
                await self.stop(app_id)

    # -- install / build ---------------------------------------------
    async def run_task(self, app, kind: str, *, timeout: int | None = None) -> TaskState:
        """Run install or build in the app directory, streaming to a log file."""
        task = self.tasks.get(app.id)
        if task and task.running:
            raise ConflictError(f"A {task.kind} task is already running for {app.name}.")
        command = app.install_command if kind == "install" else app.build_command
        if not command.strip():
            raise ValidationError(f"No {kind} command configured for {app.name}.")
        argv = split_command(command)
        workdir = Path(app.workdir)
        if not workdir.is_dir():
            raise ValidationError(f"Project directory does not exist: {workdir}")
        if shutil.which(argv[0]) is None:
            raise ValidationError(f"`{argv[0]}` is not installed on this machine.")

        state = TaskState(
            app_id=app.id,
            kind=kind,
            running=True,
            log_path=self.log_path(app.id, kind),
            command=command,
        )
        self.tasks[app.id] = state
        env = self._env_for(app)
        with open(state.log_path, "wb") as banner:
            banner.write(f"$ {command}\n".encode())
        await self._emit(app.id, f"{kind}-start")

        async def _worker() -> None:
            with contextlib.suppress(Exception):  # never leave a task "running" forever
                await _spawn()
            state.running = False
            state.finished_at = time.time()
            await self._emit(app.id, f"{kind}-done")

        async def _spawn() -> None:
            handle = open(state.log_path, "ab", buffering=0)  # noqa: SIM115
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(workdir),
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=handle,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    code = await asyncio.wait_for(process.wait(), timeout=timeout or 1800)
                except asyncio.TimeoutError:
                    kill_tree(process.pid, signal.SIGKILL)
                    code = -1
                    state.error = f"Timed out after {timeout or 1800}s."
                state.exit_code = code
                state.ok = code == 0
                if code != 0 and not state.error:
                    state.error = f"{kind} failed with exit code {code}."
            except FileNotFoundError as exc:
                state.error = f"Cannot run `{argv[0]}`: {exc}"
                state.exit_code = 127
            except Exception as exc:  # pragma: no cover - defensive
                state.error = str(exc)
                state.exit_code = 1
            finally:
                handle.close()

        asyncio.create_task(_worker())
        return state


# ---------------------------------------------------------------------------
# Reverse proxy
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(rb"""(src|href|action)=(["'])(/[^"'\s]*)""")


def rewrite_body(body: bytes, prefix: str) -> bytes:
    """Point absolute-root HTML attributes at the app's proxy prefix.

    Idempotent: a path that already starts with the prefix, or a
    protocol-relative URL (``//cdn…``), is left exactly as it is.
    """
    encoded = prefix.encode()

    def replace(match: re.Match[bytes]) -> bytes:
        attribute, quote, value = match.group(1), match.group(2), match.group(3)
        if value.startswith(b"//") or value.startswith(encoded + b"/") or value == encoded:
            return match.group(0)
        return attribute + b"=" + quote + encoded + value

    return _ATTR_RE.sub(replace, body)


def rewrite_headers(headers: Iterable[tuple[str, str]], prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        lower = key.lower()
        if lower in HOP_BY_HOP:
            continue
        if (
            lower in {"location", "content-location"}
            and value.startswith("/")
            and not value.startswith("//")
        ):
            if value.startswith(prefix + "/") or value == prefix:
                out[key] = value
                continue
            value = prefix + value
        out[key] = value
    return out


class Proxy:
    """Reverse proxy that keeps every managed app on the panel's origin.

    HTTP is proxied request-at-a-time; websockets are tunnelled byte-for-byte so
    Vite's HMR socket works through the panel.
    """

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=5.0),
            follow_redirects=False,
            verify=False,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    @staticmethod
    def target_port(app_id: str, runner: Runner) -> int:
        runtime = runner.apps.get(app_id)
        if runtime is None or runtime.port is None:
            raise NotFoundError(f"No running instance for app '{app_id}'.")
        return runtime.port

    @staticmethod
    def upstream_path(app_id: str, path: str, runner: Runner) -> str:
        """Add the base prefix the app was started with, if any."""
        runtime = runner.apps.get(app_id)
        base = getattr(runtime, "base_path", "") if runtime else ""
        if not base:
            return path
        if path == "/" or path == "":
            return base + "/"
        if path.startswith(base + "/"):
            return path
        return base + path

    async def stream(
        self,
        app_id: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: AsyncIterator[bytes] | bytes | None,
        query: str = "",
    ) -> tuple[int, dict[str, str], bytes]:
        port = self.target_port(app_id, self.runner)
        prefix = f"/apps/{app_id}"
        upstream = self.upstream_path(app_id, path, self.runner)
        url = f"http://127.0.0.1:{port}{upstream}" + (f"?{query}" if query else "")
        request_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() not in {"host", "authorization", "cookie"}
        }
        request_headers["host"] = f"127.0.0.1:{port}"
        # Rewrite the Origin/Referer so strict dev servers (Vite) accept them.
        for header in ("origin", "referer"):
            value = request_headers.get(header) or request_headers.get(header.title())
            if value:
                request_headers[header] = re.sub(
                    r"^https?://[^/]+", f"http://127.0.0.1:{port}", value
                )

        try:
            if isinstance(body, bytes) or body is None:
                response = await self.client.request(
                    method, url, headers=request_headers, content=body
                )
                raw = response.content
            else:
                chunks = [chunk async for chunk in body]
                response = await self.client.request(
                    method, url, headers=request_headers, content=b"".join(chunks)
                )
                raw = response.content
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"App '{app_id}' is not accepting connections on port {port} yet."
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Proxy error talking to '{app_id}': {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            raw = rewrite_body(raw, prefix)
        return response.status_code, rewrite_headers(response.headers.items(), prefix), raw

    # -- websockets (Vite HMR, socket.io, etc.) -----------------------
    async def tunnel(
        self,
        app_id: str,
        path: str,
        query: str,
        scope: dict,
        client: object,
        server_callback,
    ) -> None:
        """Bridge an incoming websocket to the app's own websocket endpoint."""

        port = self.target_port(app_id, self.runner)
        path = self.upstream_path(app_id, path, self.runner)
        host_header = f"127.0.0.1:{port}"
        headers = [(b"host", host_header.encode()), (b"upgrade", b"websocket")]
        for key, value in scope.get("headers") or []:
            lower = key.lower()
            if lower in (
                b"host",
                b"sec-websocket-accept",
                b"upgrade",
                # Extensions are negotiated per hop; forwarding the browser's
                # offer makes the upstream compress frames this tunnel relays
                # as plain text, which corrupts them.
                b"sec-websocket-extensions",
            ):
                continue
            if lower == b"origin":
                # Dev servers validate Origin; present the app's own origin.
                value = f"http://127.0.0.1:{port}".encode()
            headers.append((key, value))

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            request_line = f"GET {path}{'?' + query if query else ''} HTTP/1.1\r\n"
            raw = request_line.encode()
            for key, value in headers:
                raw += key + b": " + value + b"\r\n"
            raw += b"\r\n"
            writer.write(raw)
            await writer.drain()
            response_line = await reader.readline()
            if b" 101 " not in response_line:
                # Upstream refused the upgrade: report it instead of hanging.
                writer.close()
                await server_callback({"type": "websocket.close", "code": 1011})
                return

            # The ASGI server writes its own Upgrade/Connection/Accept headers,
            # so only application headers are forwarded. The subprotocol is
            # negotiated explicitly: Vite requires its "vite-hmr" echo.
            response_headers: list[tuple[bytes, bytes]] = []
            subprotocol: str | None = None
            skip = {b"connection", b"upgrade", b"sec-websocket-accept", b"sec-websocket-extensions"}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" not in line:
                    continue
                key, value = line.split(b":", 1)
                key = key.strip()
                value = value.strip()
                if key.lower() == b"sec-websocket-protocol":
                    subprotocol = value.decode("latin-1")
                    continue
                if key.lower() in skip:
                    continue
                response_headers.append((key, value))
            await server_callback(
                {
                    "type": "websocket.accept",
                    "subprotocol": subprotocol,
                    "headers": response_headers,
                }
            )
            await self._bridge(reader, writer, client)
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    @staticmethod
    async def _bridge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client) -> None:
        async def from_client() -> None:
            while True:
                message = await client.receive()
                kind = message.get("type")
                if kind == "websocket.disconnect":
                    break
                raw_bytes = message.get("bytes")
                text = message.get("text")
                is_text = raw_bytes is None and text is not None
                data = raw_bytes if raw_bytes is not None else (text or "").encode()
                if not data:
                    continue
                size = len(data)
                # 0x81 = FIN + text, 0x82 = FIN + binary: framing must be preserved
                header = bytearray([0x81 if is_text else 0x82])
                if size < 126:
                    header.append(0x80 | size)
                elif size < 65536:
                    header.append(0x80 | 126)
                    header += size.to_bytes(2, "big")
                else:
                    header.append(0x80 | 127)
                    header += size.to_bytes(8, "big")
                mask = os.urandom(4)
                header += mask
                masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
                writer.write(bytes(header) + masked)
                await writer.drain()

        async def from_server() -> None:
            while True:
                head = await reader.readexactly(2)
                opcode = head[0] & 0x0F
                length = head[1] & 0x7F
                if length == 126:
                    length = int.from_bytes(await reader.readexactly(2), "big")
                elif length == 127:
                    length = int.from_bytes(await reader.readexactly(8), "big")
                payload = await reader.readexactly(length) if length else b""
                if opcode == 0x8:  # close
                    break
                if opcode == 0x9:  # ping -> pong
                    writer.write(bytes([0x8A, 0x80]) + os.urandom(4))
                    await writer.drain()
                    continue
                if opcode == 0x1:
                    try:
                        await client.send_text(payload.decode("utf-8", "replace"))
                    except Exception:
                        break
                elif opcode == 0x2:
                    try:
                        await client.send_bytes(payload)
                    except Exception:
                        break

        tasks = [asyncio.create_task(from_client()), asyncio.create_task(from_server())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            with contextlib.suppress(Exception):
                task.result()
