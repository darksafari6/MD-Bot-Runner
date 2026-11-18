"""HTTP surface: JSON API, HTMX panel, and the per-app reverse proxy."""

from __future__ import annotations

import asyncio
import contextlib
import json
import platform
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import detect, doctor, sources
from .config import APP_NAME, DISPLAY_NAME, VERSION, Settings, ensure_token, load_settings
from .db import App, Database
from .errors import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationError
from .runner import Proxy, Runner, port_open

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
STATIC = HERE / "static"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:32].strip("-")
    return slug or "app"


def _unique_id(db: Database, base: str) -> str:
    if not db.id_taken(base):
        return base
    for index in range(2, 100):
        candidate = f"{base}-{index}"
        if not db.id_taken(candidate):
            return candidate
    raise ConflictError("Could not find a free app id; choose a different name.")


def _split_env(raw: str | dict[str, str] | None) -> dict[str, str]:
    """Accept KEY=value lines (textarea) or a JSON object."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k).strip(): str(v) for k, v in raw.items() if str(k).strip()}
    env: dict[str, str] = {}
    for line in str(raw).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValidationError(f"Environment line is missing '=': {line}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValidationError(f"Invalid environment variable name: {key}")
        env[key] = value.strip()
    return env


def _flag(value: object, *, default: bool = False) -> bool:
    """Form checkboxes send "on"; JSON sends true. Absent means the default."""
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def _coerce_port(value: object) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        port = int(str(value))
    except ValueError:
        raise ValidationError(f"Port must be a number, got {value!r}") from None
    if not (1 <= port <= 65535):
        raise ValidationError("Port must be between 1 and 65535.")
    return port


def _app_json(app: App, runner: Runner) -> dict[str, object]:
    data = app.to_json()
    state = dict(runner.state(app.id))
    runtime_port = state.pop("port", None)
    data.update(state)
    data["runtime_port"] = runtime_port
    data["port_effective"] = runtime_port or app.port
    data["exists"] = app.path.is_dir()
    data["url"] = f"/apps/{app.id}/"
    data["installed"] = (app.path / "node_modules").is_dir()
    return data


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.prepare()
    token = ensure_token(settings)
    auth_required = settings.auth_required and bool(token)
    db = Database(settings.database_path)
    runner = Runner(settings.log_dir, log_lines=settings.log_lines)
    proxy = Proxy(runner)
    subscribers: set[asyncio.Queue] = set()

    async def publish(event: str, data: dict) -> None:
        payload = {"event": event, "data": data}
        for queue in list(subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    async def on_change(app_id: str, event: str) -> None:
        app = db.get_app(app_id)
        await publish("app", {"app": _app_json(app, runner) if app else None, "change": event})

    runner.subscribe(on_change)

    async def check_token(
        request: Request,
        authorization: str = Header(default=""),
        x_api_token: str = Header(default=""),
    ) -> None:
        if not auth_required:
            return
        supplied = ""
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        elif x_api_token:
            supplied = x_api_token.strip()
        elif request.cookies.get("apphost_token"):
            supplied = request.cookies.get("apphost_token", "").strip()
        if supplied != token:
            raise HTTPException(status_code=401, detail="Invalid or missing access token.")

    def get_app_or_404(app_id: str) -> App:
        app = db.get_app(app_id)
        if app is None:
            raise NotFoundError(f"No app with id '{app_id}'.")
        return app

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.autostart:
            for app in db.list_apps():
                if app.autostart and app.path.is_dir():
                    try:
                        await runner.start(app)
                    except AppError:
                        continue
        try:
            yield
        finally:
            await runner.stop_all()
            await proxy.aclose()

    app = FastAPI(
        title=f"{DISPLAY_NAME} API",
        version=VERSION,
        description="Run and supervise Node.js/Vite/React projects on this machine.",
        lifespan=lifespan,
    )

    # Exposed for embedding and tests: the same objects the routes use.
    app.state.settings = settings
    app.state.db = db
    app.state.runner = runner
    app.state.proxy = proxy
    app.state.token = token

    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def assign_port(preferred: int) -> int:
        """Pick a free port that no other registered app already claims."""
        claimed = {a.port for a in db.list_apps() if a.port}
        for offset in range(0, 400):
            candidate = preferred + offset
            if candidate > 65535:
                break
            if candidate in claimed:
                continue
            runtime_ports = {rt.port for rt in runner.apps.values()}
            if candidate in runtime_ports:
                continue
            if not port_open(candidate, timeout=0.12):
                return candidate
        raise ConflictError("No free port found near the detected default. Set a port manually.")

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content={"detail": exc.message, "code": exc.code}
        )

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "app": APP_NAME,
            "version": VERSION,
            "auth_required": auth_required,
            "node": bool(shutil.which("node")),
            "apps": len(db.list_apps()),
            "running": sum(1 for a in db.list_apps() if runner.status(a.id) == "running"),
            "python": platform.python_version(),
        }

    @app.get("/api/doctor")
    async def api_doctor() -> dict[str, object]:
        report = doctor.diagnose(settings.data_dir, managers=settings.packages)
        return report.to_json()

    @app.get("/api/toolchains")
    async def api_toolchains() -> dict[str, object]:
        return {
            "managers": doctor.manager_status(settings.packages),
            "data_dir": str(settings.data_dir),
            "workspace": str(settings.workspace_dir),
        }

    # ------------------------------------------------------------------
    # Apps: CRUD
    # ------------------------------------------------------------------
    @app.get("/api/apps", dependencies=[Depends(check_token)])
    async def list_apps() -> dict[str, object]:
        return {"apps": [_app_json(a, runner) for a in db.list_apps()]}

    async def _payload(request: Request) -> dict:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                raise ValidationError("Request body is not valid JSON.") from None
            if not isinstance(data, dict):
                raise ValidationError("Request body must be a JSON object.")
            return data
        if "form" in ctype or "multipart" in ctype:
            form = await request.form()
            return {k: v for k, v in form.items()}
        query = dict(request.query_params)
        return query

    @app.post("/api/apps", dependencies=[Depends(check_token)], status_code=201)
    async def create_app_endpoint(request: Request) -> dict[str, object]:
        data = await _payload(request)
        return await _create(data)

    @app.get("/api/apps/scan", dependencies=[Depends(check_token)])
    async def scan() -> dict[str, object]:
        """Show what the host can import without executing anything."""
        return {
            "packages": doctor.manager_status(settings.packages),
            "git": bool(shutil.which("git")),
            "roots": list(settings.allowed_roots),
            "home": str(Path.home()),
            "cwd": str(Path.cwd()),
        }

    @app.get("/api/apps/inspect", dependencies=[Depends(check_token)])
    async def inspect(path: str) -> dict[str, object]:
        """Detect a project's commands before registering it."""
        target = Path(path).expanduser()
        if not settings.root_allowed(target):
            raise ForbiddenError(
                f"{target} is outside the allowed roots ({', '.join(settings.allowed_roots)})."
            )
        try:
            plan = detect.analyse(target)
        except detect.ProjectError as exc:
            raise ValidationError(str(exc)) from None
        return plan.to_json()

    async def _create(data: dict) -> dict[str, object]:
        name = str(data.get("name", "")).strip()
        source_kind = str(data.get("source", data.get("source_kind", "folder"))).strip()
        if source_kind not in {"folder", "git", "upload"}:
            raise ValidationError("source must be one of: folder, git, upload.")

        if not name:
            if source_kind == "folder":
                name = Path(str(data.get("path", ""))).name
            elif source_kind == "git":
                name = Path(str(data.get("url", "")).rstrip("/")).name.removesuffix(".git")
            if not name:
                raise ValidationError("A name is required.")

        explicit_id = str(data.get("id", "")).strip().lower()
        app_id = explicit_id or _unique_id(db, slugify(name))
        if not ID_RE.match(app_id):
            raise ValidationError("id must be lowercase letters, digits and dashes (max 32).")
        if explicit_id and db.id_taken(app_id):
            raise ConflictError(f"An app with id '{app_id}' already exists.")
        if len(db.list_apps()) >= settings.max_apps:
            raise ConflictError(
                f"App limit reached ({settings.max_apps}). Remove one or raise APPHOST_MAX_APPS."
            )

        workspace = settings.workspace_dir / app_id
        source_path = str(data.get("path", "")).strip()
        source_url = str(data.get("url", "")).strip()

        if source_kind == "folder":
            if not source_path:
                raise ValidationError("path is required when source=folder.")
            if not settings.root_allowed(Path(source_path).expanduser()):
                raise ForbiddenError(
                    f"{source_path} is outside the allowed roots "
                    f"({', '.join(settings.allowed_roots)}). Set APPHOST_ROOTS to widen."
                )
            imported = sources.link_folder(source_path, workspace)
            workdir = imported.workdir
            resolved = workdir.resolve()
            for existing in db.list_apps():
                if existing.path.resolve() == resolved:
                    raise ConflictError(
                        f"'{existing.id}' already manages {resolved}. "
                        "Two supervisors on one folder fight over node_modules."
                    )
        elif source_kind == "git":
            if not source_url:
                raise ValidationError("url is required when source=git.")
            imported = await sources.clone(
                source_url, workspace, branch=str(data.get("branch", ""))
            )
            workdir = imported.workdir
        else:  # upload handled by the multipart endpoint
            raise ValidationError("Upload an archive with POST /api/apps/upload.")

        try:
            plan = detect.analyse(workdir, str(data.get("package_manager", "")).strip() or None)
        except detect.ProjectError as exc:
            if source_kind == "git":
                shutil.rmtree(workspace, ignore_errors=True)
            raise ValidationError(str(exc)) from None

        requested_port = _coerce_port(data.get("port"))
        port = requested_port or assign_port(plan.port)
        start_command = str(data.get("start_command", "")).strip() or plan.start_command
        try:
            detect.split_command(start_command)
        except detect.ProjectError as exc:
            raise ValidationError(f"start_command is not valid: {exc}") from None
        app_row = App(
            id=app_id,
            name=name,
            source_kind=source_kind,
            source_path=str(workdir) if source_kind == "folder" else source_path,
            source_url=source_url,
            workdir=str(workdir),
            package_manager=str(data.get("package_manager", "")).strip() or plan.package_manager,
            install_command=str(data.get("install_command", "")).strip() or plan.install_command,
            build_command=str(data.get("build_command", "")).strip() or plan.build_command,
            start_command=start_command,
            framework=plan.framework,
            proxy_base=_flag(data.get("proxy_base"), default=True),
            port=port,
            env=_split_env(data.get("env")),
            autostart=bool(data.get("autostart")),
        )
        db.add_app(app_row)
        await publish("apps", {"created": app_id})
        return _app_json(app_row, runner)

    @app.post("/api/apps/upload", dependencies=[Depends(check_token)], status_code=201)
    async def upload(request: Request) -> dict[str, object]:
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None or isinstance(upload_file, str):
            raise ValidationError("Attach an archive in the 'file' field (.zip/.tar.gz).")
        name = str(form.get("name", "")).strip()
        filename = Path(getattr(upload_file, "filename", "upload.zip") or "upload.zip").name
        if not name:
            name = Path(filename).stem.replace("_", "-")
        app_id = str(form.get("id", "")).strip().lower() or _unique_id(db, slugify(name))
        if not ID_RE.match(app_id):
            raise ValidationError("id must be lowercase letters, digits and dashes (max 32).")
        if db.id_taken(app_id):
            raise ConflictError(f"An app with id '{app_id}' already exists.")

        workspace = settings.workspace_dir / app_id
        staging = settings.workspace_dir / f".upload-{app_id}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        archive_path = staging / filename
        size = 0
        with open(archive_path, "wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > sources.MAX_UPLOAD_BYTES:
                    out.close()
                    shutil.rmtree(staging, ignore_errors=True)
                    raise ValidationError(
                        "Upload exceeds 100 MiB. Use the git importer for large repos."
                    )
                out.write(chunk)
        try:
            extract_dir = staging / "content"
            sources.extract_archive(archive_path, extract_dir)
            root = sources.find_project_root(extract_dir)
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.move(str(root), str(workspace))
            plan = detect.analyse(workspace, str(form.get("package_manager", "")).strip() or None)
        except sources.ValidationError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except detect.ProjectError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise ValidationError(str(exc)) from None
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        app_row = App(
            id=app_id,
            name=name,
            source_kind="upload",
            source_path=filename,
            workdir=str(workspace),
            package_manager=plan.package_manager,
            install_command=plan.install_command,
            build_command=plan.build_command,
            start_command=plan.start_command,
            framework=plan.framework,
            port=_coerce_port(form.get("port")) or assign_port(plan.port),
            env={},
            autostart=bool(form.get("autostart")),
        )
        db.add_app(app_row)
        await publish("apps", {"created": app_id})
        return _app_json(app_row, runner)

    @app.get("/api/apps/{app_id}", dependencies=[Depends(check_token)])
    async def get_one(app_id: str) -> dict[str, object]:
        return _app_json(get_app_or_404(app_id), runner)

    @app.patch("/api/apps/{app_id}", dependencies=[Depends(check_token)])
    async def patch_one(app_id: str, request: Request) -> dict[str, object]:
        get_app_or_404(app_id)
        data = await _payload(request)
        changes = dict(data)
        if "env" in changes:
            changes["env"] = _split_env(changes["env"])
        if "port" in changes:
            changes["port"] = _coerce_port(changes["port"])
        for command_field in ("start_command", "install_command", "build_command"):
            if command_field in changes:
                value = str(changes[command_field]).strip()
                if value:
                    try:
                        detect.split_command(value)
                    except detect.ProjectError as exc:
                        raise ValidationError(f"{command_field} is not valid: {exc}") from None
                changes[command_field] = value
        if "start_command" in changes and not changes["start_command"]:
            raise ValidationError("start_command cannot be empty.")
        if "autostart" in changes:
            changes["autostart"] = _flag(changes["autostart"])
        if "proxy_base" in changes:
            changes["proxy_base"] = _flag(changes["proxy_base"], default=True)
        updated = db.update_app(app_id, changes)
        assert updated is not None
        await publish("app", {"app": _app_json(updated, runner), "change": "updated"})
        return _app_json(updated, runner)

    @app.delete("/api/apps/{app_id}", dependencies=[Depends(check_token)])
    async def delete_one(app_id: str, delete_files: bool = False) -> dict[str, object]:
        app_row = get_app_or_404(app_id)
        await runner.stop(app_id)
        db.delete_app(app_id)
        runner.clear_log(app_id)
        runner.apps.pop(app_id, None)
        removed = False
        if delete_files:
            target = app_row.path
            workspace = settings.workspace_dir.resolve()
            if target.resolve() != workspace and workspace in target.resolve().parents:
                shutil.rmtree(target, ignore_errors=True)
                removed = True
        await publish("apps", {"deleted": app_id})
        return {"deleted": app_id, "files_removed": removed}

    # ------------------------------------------------------------------
    # Apps: lifecycle
    # ------------------------------------------------------------------
    @app.post("/api/apps/{app_id}/install", dependencies=[Depends(check_token)])
    async def install(app_id: str) -> dict[str, object]:
        app_row = get_app_or_404(app_id)
        task = await runner.run_task(app_row, "install", timeout=settings.install_timeout)
        return task.to_json()

    @app.post("/api/apps/{app_id}/build", dependencies=[Depends(check_token)])
    async def build(app_id: str) -> dict[str, object]:
        app_row = get_app_or_404(app_id)
        task = await runner.run_task(app_row, "build", timeout=settings.build_timeout)
        return task.to_json()

    async def _start(app_row: App) -> dict[str, object]:
        if not app_row.path.is_dir():
            raise ValidationError(f"Project directory is missing: {app_row.workdir}")
        runner.validate(app_row)
        if not (app_row.path / "node_modules").is_dir() and app_row.install_command:
            # First run: install dependencies so `vite`/`react-scripts` resolve.
            task = await runner.run_task(app_row, "install", timeout=settings.install_timeout)
            await asyncio.create_task(_start_after_install(app_row, task))
            return {"queued": True, "task": task.to_json(), **runner.state(app_id=app_row.id)}
        state = await runner.start(app_row)
        await asyncio.create_task(runner.wait_ready(app_row.id, timeout=settings.start_timeout))
        return state

    async def _start_after_install(app_row: App, task) -> None:
        while task.running:
            await asyncio.sleep(0.5)
        if not task.ok:
            await publish("app", {"app": _app_json(app_row, runner), "change": "install-failed"})
            return
        try:
            await runner.start(app_row)
            await runner.wait_ready(app_row.id, timeout=settings.start_timeout)
        except AppError:
            pass

    @app.post("/api/apps/{app_id}/start", dependencies=[Depends(check_token)])
    async def start(app_id: str) -> dict[str, object]:
        return await _start(get_app_or_404(app_id))

    @app.post("/api/apps/{app_id}/stop", dependencies=[Depends(check_token)])
    async def stop(app_id: str) -> dict[str, object]:
        get_app_or_404(app_id)
        return await runner.stop(app_id)

    @app.post("/api/apps/{app_id}/restart", dependencies=[Depends(check_token)])
    async def restart(app_id: str) -> dict[str, object]:
        app_row = get_app_or_404(app_id)
        await runner.stop(app_id)
        return await _start(app_row)

    @app.post("/api/apps/{app_id}/pull", dependencies=[Depends(check_token)])
    async def pull(app_id: str) -> dict[str, object]:
        app_row = get_app_or_404(app_id)
        if app_row.source_kind != "git":
            raise ValidationError("Only git-sourced apps can be updated this way.")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, sources.git_sync, app_row.path)
        ok = result.returncode == 0
        await publish("app", {"app": _app_json(app_row, runner), "change": "pulled"})
        return {
            "ok": ok,
            "output": (result.stdout or "") + (result.stderr or ""),
            "code": result.returncode,
        }

    @app.get("/api/apps/{app_id}/logs", dependencies=[Depends(check_token)])
    async def logs(app_id: str, lines: int = 200, kind: str = "app") -> PlainTextResponse:
        get_app_or_404(app_id)
        if kind not in {"app", "install", "build"}:
            raise ValidationError("kind must be app, install or build.")
        text = runner.tail(runner.log_path(app_id, kind), lines=max(1, min(lines, 5000)))
        return PlainTextResponse(text or "(no output yet)")

    @app.delete("/api/apps/{app_id}/logs", dependencies=[Depends(check_token)])
    async def clear_logs(app_id: str) -> dict[str, object]:
        get_app_or_404(app_id)
        runner.clear_log(app_id)
        return {"cleared": True}

    # ------------------------------------------------------------------
    # Events (SSE)
    # ------------------------------------------------------------------
    @app.get("/api/events", dependencies=[Depends(check_token)])
    async def events(request: Request) -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        subscribers.add(queue)

        async def stream():
            try:
                yield 'event: hello\ndata: {"ok":true}\n\n'
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"event: {payload['event']}\ndata: {json.dumps(payload['data'])}\n\n"
            finally:
                subscribers.discard(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------
    # Reverse proxy: /apps/<id>/... -> 127.0.0.1:<port>/...
    # ------------------------------------------------------------------
    @app.api_route(
        "/apps/{app_id}/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxied(app_id: str, rest: str, request: Request):
        if db.get_app(app_id) is None:
            raise NotFoundError(f"No app with id '{app_id}'.")
        body = await request.body()
        status, headers, content = await proxy.stream(
            app_id,
            request.method,
            "/" + rest,
            dict(request.headers),
            body,
            query=request.url.query or "",
        )
        return StreamingResponse(iter([content]), status_code=status, headers=headers)

    @app.websocket("/apps/{app_id}/{rest:path}")
    async def proxied_ws(websocket: WebSocket, app_id: str, rest: str) -> None:
        """Websocket upgrade for managed apps (Vite HMR, socket.io, …)."""
        if db.get_app(app_id) is None:
            await websocket.close(code=1008)
            return
        query = websocket.url.query or ""
        try:
            await proxy.tunnel(
                app_id,
                "/" + rest,
                query,
                websocket.scope,
                websocket,
                websocket.send,
            )
        except AppError:
            with contextlib.suppress(Exception):
                await websocket.close(code=1011)
        except (ConnectionError, OSError):
            with contextlib.suppress(Exception):
                await websocket.close(code=1011)

    # ------------------------------------------------------------------
    # HTML panel
    # ------------------------------------------------------------------
    def _ctx(request: Request, **extra) -> dict[str, object]:
        apps = [_app_json(a, runner) for a in db.list_apps()]
        base = {
            "request": request,
            "apps": apps,
            "version": VERSION,
            "display_name": DISPLAY_NAME,
            "auth_required": auth_required,
            "data_dir": str(settings.data_dir),
            "flash": request.query_params.get("flash", ""),
        }
        base.update(extra)
        return base

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        report = doctor.diagnose(settings.data_dir, managers=settings.packages)
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            _ctx(
                request,
                managers=doctor.manager_status(settings.packages),
                report=report,
                running=sum(1 for a in db.list_apps() if runner.status(a.id) == "running"),
                logs={a.id: runner.tail(runner.log_path(a.id), 40) for a in db.list_apps()},
            ),
        )

    @app.get("/apps/{app_id}", response_class=HTMLResponse)
    async def app_page(request: Request, app_id: str, tab: str = "overview"):
        app_row = get_app_or_404(app_id)
        kind = tab if tab in {"overview", "run", "config", "logs"} else "overview"
        return TEMPLATES.TemplateResponse(
            request,
            "app.html",
            _ctx(
                request,
                app=_app_json(app_row, runner),
                row=app_row,
                tab=kind,
                log=runner.tail(runner.log_path(app_id), 300),
                install_log=runner.tail(runner.log_path(app_id, "install"), 200),
                env_text="\n".join(f"{k}={v}" for k, v in app_row.env.items()),
                managers=doctor.manager_status(settings.packages),
                max_apps=settings.max_apps,
            ),
        )

    @app.get("/partials/apps", response_class=HTMLResponse)
    async def partial_apps(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "partials/app_list.html",
            _ctx(
                request, logs={a.id: runner.tail(runner.log_path(a.id), 25) for a in db.list_apps()}
            ),
        )

    @app.get("/partials/apps/{app_id}/logs", response_class=HTMLResponse)
    async def partial_logs(request: Request, app_id: str, lines: int = 300):
        get_app_or_404(app_id)
        return TEMPLATES.TemplateResponse(
            request,
            "partials/log.html",
            {
                "request": request,
                "app_id": app_id,
                "log": runner.tail(runner.log_path(app_id), lines),
                "status": runner.status(app_id),
            },
        )

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "register.html",
            _ctx(
                request,
                managers=doctor.manager_status(settings.packages),
                roots=list(settings.allowed_roots),
                git_ok=bool(shutil.which("git")),
            ),
        )

    @app.post("/register")
    async def register_form(request: Request):
        form = await request.form()
        data = {k: v for k, v in form.items()}
        data["autostart"] = str(form.get("autostart", "")).lower() in {"on", "1", "true"}
        created = await _create(data)
        return RedirectResponse(f"/apps/{created['id']}", status_code=303)

    @app.post("/upload")
    async def upload_form(request: Request):
        form = await request.form()
        files = {k: v for k, v in form.items()}
        upload_file = files.get("file")
        if upload_file is None or isinstance(upload_file, str):
            raise ValidationError("Choose a .zip or .tar.gz archive to upload.")
        # Re-use the API handler through a prepared multipart body.
        name = str(form.get("name", "")).strip()
        filename = Path(upload_file.filename or "upload.zip").name
        app_id = _unique_id(db, slugify(name or Path(filename).stem))
        staging = settings.workspace_dir / f".upload-{app_id}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        archive_path = staging / filename
        size = 0
        with open(archive_path, "wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > sources.MAX_UPLOAD_BYTES:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise ValidationError("Upload exceeds 100 MiB.")
                out.write(chunk)
        try:
            extract_dir = staging / "content"
            sources.extract_archive(archive_path, extract_dir)
            root = sources.find_project_root(extract_dir)
            workspace = settings.workspace_dir / app_id
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.move(str(root), str(workspace))
            plan = detect.analyse(workspace)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        app_row = App(
            id=app_id,
            name=name or app_id,
            source_kind="upload",
            source_path=filename,
            workdir=str(workspace),
            package_manager=plan.package_manager,
            install_command=plan.install_command,
            build_command=plan.build_command,
            start_command=plan.start_command,
            framework=plan.framework,
            port=assign_port(plan.port),
        )
        db.add_app(app_row)
        return RedirectResponse(f"/apps/{app_id}?flash=Uploaded+{filename}", status_code=303)

    # -- HTMX actions -------------------------------------------------
    @app.post("/ui/apps", response_class=HTMLResponse)
    async def ui_create(request: Request):
        form = await request.form()
        data = {k: v for k, v in form.items()}
        data["autostart"] = str(form.get("autostart", "")).lower() in {"on", "1", "true"}
        created = await _create(data)
        response = RedirectResponse(f"/apps/{created['id']}", status_code=303)
        return response

    @app.post("/ui/apps/{app_id}/config")
    async def ui_config(request: Request, app_id: str):
        app_row = get_app_or_404(app_id)
        form = await request.form()
        changes = {
            "name": form.get("name", app_row.name),
            "package_manager": form.get("package_manager", app_row.package_manager),
            "install_command": form.get("install_command", app_row.install_command),
            "build_command": form.get("build_command", app_row.build_command),
            "start_command": form.get("start_command", app_row.start_command),
            "port": form.get("port"),
            "env": str(form.get("env", "")),
            "autostart": str(form.get("autostart", "")).lower() in {"on", "1", "true"},
            "proxy_base": _flag(form.get("proxy_base"), default=False),
        }
        if "env" in changes:
            changes["env"] = _split_env(changes["env"])
        if "port" in changes:
            changes["port"] = _coerce_port(changes["port"])
        db.update_app(app_id, changes)
        return RedirectResponse(f"/apps/{app_id}?tab=config&flash=Saved", status_code=303)

    @app.post("/ui/apps/{app_id}/{action}", response_class=HTMLResponse)
    async def ui_action(request: Request, app_id: str, action: str):
        app_row = get_app_or_404(app_id)
        if action == "start":
            await _start(app_row)
        elif action == "stop":
            await runner.stop(app_id)
        elif action == "restart":
            await runner.stop(app_id)
            await _start(app_row)
        elif action == "install":
            await runner.run_task(app_row, "install", timeout=settings.install_timeout)
        elif action == "build":
            await runner.run_task(app_row, "build", timeout=settings.build_timeout)
        elif action == "clearlog":
            runner.clear_log(app_id)
            return TEMPLATES.TemplateResponse(
                request, "partials/log.html", {"request": request, "app_id": app_id, "log": ""}
            )
        elif action == "pull":
            if app_row.source_kind != "git":
                raise ValidationError("Only git-sourced apps can be pulled.")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, sources.git_sync, app_row.path)
            output = (result.stdout or "") + (result.stderr or "")
            return PlainTextResponse(f"{output.strip() or 'Already up to date.'}")
        elif action == "delete":
            await runner.stop(app_id)
            db.delete_app(app_id)
            runner.clear_log(app_id)
            return HTMLResponse("<div class='notice'>App removed. Refresh the page.</div>")
        else:
            raise ValidationError(f"Unknown action '{action}'.")
        return TEMPLATES.TemplateResponse(
            request,
            "partials/app_card.html",
            _ctx(
                request,
                app=_app_json(app_row, runner),
                row=app_row,
                log=runner.tail(runner.log_path(app_id), 25),
            ),
        )

    @app.post("/login")
    async def login_form(request: Request):
        form = await request.form()
        supplied = str(form.get("token", "")).strip()
        if auth_required and supplied != token:
            return RedirectResponse("/?flash=Invalid+token", status_code=303)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("apphost_token", supplied or token, httponly=True, samesite="strict")
        return response

    return app


app = create_app  # uvicorn apphost.api:create_app --factory
