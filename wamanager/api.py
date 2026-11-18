"""HTTP surface: JSON REST API plus server-rendered HTMX pages."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .ai import AiClient
from .commands import format_uptime
from .config import VERSION, Settings, get_settings
from .db import DEFAULT_CONFIG, Bot, Database
from .engine import Engine
from .errors import AppError, ValidationError
from .throttle import MAX_GAP_MS, MAX_PER_MINUTE, MIN_GAP_MS, MIN_PER_MINUTE

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"

ID_RE = re.compile(r"^[a-z0-9-]{3,40}$")


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24]
    return base or "bot"


def _unique_id(name: str, existing: set[str]) -> str:
    bot_id = slugify(name)
    while bot_id in existing:
        bot_id = f"{bot_id}-{int(time.time() * 1000) % 10000}"
    return bot_id


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare()
    db = Database(settings.database_path)  # type: ignore[arg-type]
    ai = AiClient(settings)
    engine = Engine(settings=settings, db=db, ai=ai)

    # ---------------------------- live event fan-out (SSE) ------------------
    subscribers: set[asyncio.Queue[str]] = set()

    def publish(event: str, payload: dict[str, Any]) -> None:
        frame = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        for queue in list(subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

    async def _on_change(bot: Bot) -> None:
        publish("bot", {"id": bot.id, "status": bot.status, "error": bot.last_error})

    engine.on_change(_on_change)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        for bot in db.list_bots():
            if bot.autostart and bot.status in {"connected", "reconnecting", "starting"}:
                with contextlib.suppress(Exception):
                    await engine.start(bot.id)
        yield
        await engine.stop_all()
        db.close()

    app = FastAPI(title="WhatsApp MD Bot Runner Manager", version=VERSION, lifespan=lifespan)
    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.filters["uptime"] = format_uptime

    # ------------------------------------------------------------------ auth
    def check_token(authorization: str | None = Header(default=None)) -> None:
        if not settings.auth_required:
            return
        provided = ""
        if authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if provided != settings.api_token:
            raise HTTPException(status_code=401, detail="Invalid or missing API token")

    api_guard = [Depends(check_token)]

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    def get_bot_or_404(bot_id: str) -> Bot:
        if not ID_RE.match(bot_id):
            raise ValidationError("Invalid bot id")
        bot = db.get_bot(bot_id)
        if bot is None:
            raise AppError(f'Bot "{bot_id}" not found', 404)
        return bot

    def create_bot(name: str) -> Bot | None:
        clean = (name or "").strip()[:60]
        if not clean:
            raise ValidationError("A bot name is required")
        if len(db.list_bots()) >= settings.max_instances:
            raise ValidationError(
                f"Instance limit reached (MAX_INSTANCES={settings.max_instances})"
            )
        bot_id = _unique_id(clean, {bot.id for bot in db.list_bots()})
        bot = db.create_bot(bot_id, clean)
        publish("bot", {"id": bot.id, "status": bot.status, "event": "created"})
        return bot

    # =================================================================== API
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": VERSION,
            "auth_required": settings.auth_required,
            "engine": engine.status(),
            "ai": {"configured": ai.configured()},
            "python": __import__("sys").version.split()[0],
        }

    @app.get("/api/bots", dependencies=api_guard)
    def list_bots() -> dict[str, Any]:
        return {"bots": [_bot_json(bot) for bot in db.list_bots()]}

    @app.post("/api/bots", status_code=201, dependencies=api_guard)
    async def create_bot_endpoint(request: Request) -> dict[str, Any]:
        """Create a bot from JSON `{"name": ...}`, a form field, or `?name=`."""
        name = request.query_params.get("name", "")
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/json"):
            payload = await request.json()
            name = str(payload.get("name", ""))
        elif ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            name = str(form.get("name", ""))
        return {"bot": _bot_json(create_bot(name))}  # type: ignore[arg-type]

    @app.post("/api/bots/json", status_code=201, dependencies=api_guard)
    async def create_bot_json(request: Request) -> dict[str, Any]:
        payload = await request.json()
        bot = create_bot(str(payload.get("name", "")))
        return {"bot": _bot_json(bot)}  # type: ignore[arg-type]

    @app.get("/api/bots/{bot_id}", dependencies=api_guard)
    def get_bot_endpoint(bot_id: str) -> dict[str, Any]:
        return {"bot": _bot_json(get_bot_or_404(bot_id))}

    @app.patch("/api/bots/{bot_id}", dependencies=api_guard)
    async def patch_bot(bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        bot = get_bot_or_404(bot_id)
        fields: dict[str, Any] = {}

        if "name" in payload:
            name = str(payload["name"]).strip()[:60]
            if not name:
                raise ValidationError("Name cannot be empty")
            fields["name"] = name
        if "autostart" in payload:
            fields["autostart"] = bool(payload["autostart"])
        if isinstance(payload.get("config"), dict):
            fields["config"] = _validate_config(payload["config"], bot.config)
        if "commands" in payload:
            db.replace_commands(bot_id, _validate_commands(payload["commands"]))

        if fields:
            db.update_bot(bot_id, **fields)
        publish("bot", {"id": bot_id, "event": "updated"})
        return {"bot": _bot_json(get_bot_or_404(bot_id))}

    @app.delete("/api/bots/{bot_id}", dependencies=api_guard)
    async def delete_bot_endpoint(bot_id: str) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        with contextlib.suppress(Exception):
            await engine.stop(bot_id)
        db.delete_bot(bot_id)
        publish("bot", {"id": bot_id, "event": "deleted"})
        return {"deleted": True}

    @app.post("/api/bots/{bot_id}/start", dependencies=api_guard)
    async def start_bot(bot_id: str) -> dict[str, Any]:
        return {"bot": _bot_json(await engine.start(bot_id))}

    @app.post("/api/bots/{bot_id}/stop", dependencies=api_guard)
    async def stop_bot(bot_id: str) -> dict[str, Any]:
        return {"bot": _bot_json(await engine.stop(bot_id))}

    @app.post("/api/bots/{bot_id}/restart", dependencies=api_guard)
    async def restart_bot(bot_id: str) -> dict[str, Any]:
        await engine.stop(bot_id)
        return {"bot": _bot_json(await engine.start(bot_id))}

    @app.post("/api/bots/{bot_id}/logout", dependencies=api_guard)
    async def logout_bot(bot_id: str) -> dict[str, Any]:
        return {"bot": _bot_json(await engine.stop(bot_id, logout=True))}

    @app.get("/api/bots/{bot_id}/qr", dependencies=api_guard)
    def qr_endpoint(bot_id: str) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return engine.qr(bot_id)

    @app.post("/api/bots/{bot_id}/pairing-code", dependencies=api_guard)
    async def pairing_code(bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return await engine.request_pairing_code(bot_id, str(payload.get("phone", "")))

    @app.post("/api/bots/{bot_id}/messages", dependencies=api_guard)
    async def send_message(bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        result = await engine.send(bot_id, str(payload.get("to", "")), str(payload.get("text", "")))
        publish("message", {"id": bot_id})
        return result

    @app.get("/api/bots/{bot_id}/messages", dependencies=api_guard)
    def list_messages(
        bot_id: str, chat_jid: str | None = None, limit: int = Query(default=100, le=1000)
    ) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return {
            "messages": db.list_messages(bot_id, chat_jid, limit),
            "throttle": engine.throttle_status(bot_id),
        }

    @app.get("/api/bots/{bot_id}/conversations", dependencies=api_guard)
    def conversations(bot_id: str) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return {"conversations": db.conversations(bot_id)}

    @app.delete("/api/bots/{bot_id}/messages", dependencies=api_guard)
    def clear_messages(bot_id: str) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return {"removed": db.clear_messages(bot_id)}

    @app.delete("/api/bots/{bot_id}/memory", dependencies=api_guard)
    def clear_memory(bot_id: str, chat_jid: str | None = None) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return {"removed": db.clear_memory(bot_id, chat_jid)}

    @app.get("/api/bots/{bot_id}/ai/usage", dependencies=api_guard)
    def ai_usage(bot_id: str) -> dict[str, Any]:
        get_bot_or_404(bot_id)
        return db.ai_usage_summary(bot_id)

    @app.post("/api/ai/check", dependencies=api_guard)
    async def ai_check(request: Request) -> dict[str, Any]:
        """Round-trip the provider so the panel can prove it works."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return ai.check(payload.get("config") or {})

    @app.get("/api/events")
    async def events(token: str | None = None) -> StreamingResponse:
        if settings.auth_required and token != settings.api_token:
            raise HTTPException(status_code=401, detail="Invalid token")
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        subscribers.add(queue)

        async def stream() -> AsyncIterator[bytes]:
            try:
                yield b": connected\n\n"
                while True:
                    try:
                        yield (await asyncio.wait_for(queue.get(), timeout=20)).encode()
                    except asyncio.TimeoutError:
                        yield b": ping\n\n"
            finally:
                subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # ================================================================= pages
    @app.get("/", response_class=HTMLResponse)
    def page_dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "bots": db.list_bots(),
                "engine": engine.status(),
                "version": VERSION,
                "ai_configured": ai.configured(),
            },
        )

    @app.get("/bots/{bot_id}", response_class=HTMLResponse)
    def page_bot(
        request: Request, bot_id: str, tab: str = "overview", chat: str = ""
    ) -> HTMLResponse:
        bot = db.get_bot(bot_id)
        if bot is None:
            raise HTTPException(status_code=404, detail="Bot not found")
        return templates.TemplateResponse(
            request,
            "bot.html",
            {
                "bot": bot,
                "tab": tab,
                "selected": chat or None,
                "version": VERSION,
                "throttle": engine.throttle_status(bot_id),
                "ai_configured": ai.configured(bot.config),
                "usage": db.ai_usage_summary(bot_id),
                "conversations": db.conversations(bot_id),
                "messages": db.list_messages(bot_id, chat or None, 100),
                "limits": {
                    "min_per_minute": MIN_PER_MINUTE,
                    "max_per_minute": MAX_PER_MINUTE,
                    "min_gap_ms": MIN_GAP_MS,
                    "max_gap_ms": MAX_GAP_MS,
                },
            },
        )

    # ------------------------------------------------------------- partials
    @app.get("/partials/bots", response_class=HTMLResponse)
    def partial_bots(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/bot_list.html", {"bots": db.list_bots()}
        )

    @app.get("/partials/bots/{bot_id}/qr", response_class=HTMLResponse)
    def partial_qr(request: Request, bot_id: str) -> HTMLResponse:
        data = engine.qr(bot_id)
        data["qr_svg"] = _qr_svg(data.get("qr"))
        return templates.TemplateResponse(
            request, "partials/qr.html", {"qr": data, "bot_id": bot_id}
        )

    @app.get("/partials/bots/{bot_id}/messages", response_class=HTMLResponse)
    def partial_messages(
        request: Request, bot_id: str, chat_jid: str | None = None
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "partials/transcript.html",
            {
                "messages": db.list_messages(bot_id, chat_jid, 100),
                "conversations": db.conversations(bot_id),
                "bot_id": bot_id,
                "selected": chat_jid,
            },
        )

    # --------------------------------------------------- HTMX action posts
    @app.post("/ui/bots", response_class=HTMLResponse)
    async def ui_create(request: Request) -> HTMLResponse:
        form = await request.form()
        with contextlib.suppress(AppError):
            create_bot(str(form.get("name", "")))
        return templates.TemplateResponse(
            request, "partials/bot_list.html", {"bots": db.list_bots()}
        )

    @app.post("/ui/bots/{bot_id}/ai-check", response_class=HTMLResponse)
    def ui_ai_check(bot_id: str) -> HTMLResponse:
        bot = db.get_bot(bot_id)
        if bot is None:
            return HTMLResponse('<p class="error-line">Bot not found</p>')
        try:
            result = ai.check(bot.config)
        except AppError as exc:
            return HTMLResponse(f'<p class="error-line">{exc.message}</p>')
        except Exception as exc:  # network failure, provider outage
            return HTMLResponse(f'<p class="error-line">{exc}</p>')
        return HTMLResponse(
            f'<p class="ok">Provider OK · {result["model"]} · {result["latency_ms"]}ms '
            f"(replied: {result['sample'][:40]!r})</p>"
        )

    @app.post("/ui/bots/{bot_id}/{action}", response_class=HTMLResponse)
    async def ui_action(request: Request, bot_id: str, action: str) -> HTMLResponse:
        if db.get_bot(bot_id) is None:
            return HTMLResponse('<p class="error-line">Bot not found</p>', status_code=200)
        try:
            if action == "start":
                await engine.start(bot_id)
            elif action == "stop":
                await engine.stop(bot_id)
            elif action == "restart":
                await engine.stop(bot_id)
                await engine.start(bot_id)
            elif action == "logout":
                await engine.stop(bot_id, logout=True)
            elif action == "delete":
                await engine.stop(bot_id)
                db.delete_bot(bot_id)
        except AppError as exc:
            log.warning("ui action %s failed for %s: %s", action, bot_id, exc)
            return HTMLResponse(f'<p class="error-line">{exc.message}</p>', status_code=200)
        except Exception as exc:  # engine/dependency failures must not 500 the UI
            log.warning("ui action %s crashed for %s: %s", action, bot_id, exc)
            return HTMLResponse(f'<p class="error-line">{exc}</p>', status_code=200)
        return templates.TemplateResponse(
            request, "partials/bot_list.html", {"bots": db.list_bots()}
        )

    @app.post("/ui/bots/{bot_id}/send", response_class=HTMLResponse)
    async def ui_send(
        request: Request,
        bot_id: str,
        to: str = "",
        text: str = "",
        chat_jid: str = "",
    ) -> HTMLResponse:
        error = ""
        try:
            await engine.send(bot_id, to or chat_jid, text, origin="manual")
        except AppError as exc:
            error = exc.message
        except Exception as exc:
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "partials/transcript.html",
            {
                "messages": db.list_messages(bot_id, chat_jid or None, 100),
                "conversations": db.conversations(bot_id),
                "bot_id": bot_id,
                "selected": chat_jid or None,
                "error": error,
            },
        )

    # ------------------------------------------------ plain form posts (no JS)
    @app.post("/bots/{bot_id}/commands")
    async def form_commands(request: Request, bot_id: str) -> RedirectResponse:
        get_bot_or_404(bot_id)
        form = await request.form()
        names = [str(n) for n in form.getlist("name[]")]
        responses = [str(r) for r in form.getlist("response[]")]
        enabled = set(form.getlist("enabled[]"))
        exact = set(form.getlist("exact[]"))
        commands = []
        for index, name in enumerate(names):
            name = name.strip()
            response = responses[index].strip() if index < len(responses) else ""
            if not name or not response:
                continue
            # Checkbox groups are posted independently, so rows are matched by
            # position; an index that was not sent means "unchecked".
            commands.append(
                {
                    "name": name,
                    "response": response,
                    "enabled": str(index) in enabled,
                    "exact": str(index) in exact,
                }
            )
        db.replace_commands(bot_id, commands)
        return RedirectResponse(f"/bots/{bot_id}?tab=commands", status_code=303)

    @app.post("/bots/{bot_id}/behaviour")
    async def form_behaviour(request: Request, bot_id: str) -> RedirectResponse:
        bot = get_bot_or_404(bot_id)
        form = await request.form()
        config = _validate_config(
            {
                "command_prefix": form.get("command_prefix", bot.command_prefix),
                "respond_to_groups": form.get("respond_to_groups") is not None,
                "respond_to_dms": form.get("respond_to_dms") is not None,
                "auto_read": form.get("auto_read") is not None,
                "typing_indicator": form.get("typing_indicator") is not None,
                "outbound_per_minute": form.get("outbound_per_minute", 20),
                "outbound_min_gap_ms": form.get("outbound_min_gap_ms", 1200),
                "allowed_numbers": _split_numbers(form.get("allowed_numbers", "")),
                "blocked_numbers": _split_numbers(form.get("blocked_numbers", "")),
            },
            bot.config,
        )
        name = str(form.get("name", bot.name)).strip()[:60] or bot.name
        db.update_bot(bot_id, config=config, name=name)
        return RedirectResponse(f"/bots/{bot_id}?tab=behaviour", status_code=303)

    @app.post("/bots/{bot_id}/ai")
    async def form_ai(request: Request, bot_id: str) -> RedirectResponse:
        bot = get_bot_or_404(bot_id)
        form = await request.form()
        config = _validate_config(
            {
                "ai_enabled": form.get("ai_enabled") is not None,
                "ai_in_groups": form.get("ai_in_groups") is not None,
                "ai_model": form.get("ai_model", ""),
                "ai_base_url": form.get("ai_base_url", ""),
                "ai_persona": form.get("ai_persona", ""),
                "ai_history_turns": form.get("ai_history_turns", 8),
            },
            bot.config,
        )
        db.update_bot(bot_id, config=config)
        return RedirectResponse(f"/bots/{bot_id}?tab=ai", status_code=303)

    return app


# ---------------------------------------------------------------- helpers
def _split_numbers(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _qr_svg(payload: str | None) -> str | None:
    """Render a QR code to inline SVG locally.

    Deliberately avoids an external image service: the panel must work offline,
    and a QR payload is a login credential that should never leave the host.
    """
    if not payload:
        return None
    try:
        import segno

        buffer = io.BytesIO()
        segno.make(payload, error="m").save(
            buffer, kind="svg", scale=4, border=2, dark="#0b0b0d", light="#ffffff"
        )
        svg = buffer.getvalue().decode("utf-8")
        # Drop the XML prolog: inlining it in HTML is invalid markup.
        return svg[svg.index("<svg") :] if "<svg" in svg else svg
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("QR rendering failed: %s", exc)
        return None


def _bot_json(bot: Bot) -> dict[str, Any]:
    return {
        "id": bot.id,
        "name": bot.name,
        "status": bot.status,
        "created_at": bot.created_at,
        "identity": {
            "jid": bot.identity_jid,
            "name": bot.identity_name,
            "number": bot.identity_number,
        },
        "config": bot.config,
        "stats": bot.stats,
        "commands": bot.commands,
        "last_error": bot.last_error,
        "autostart": bot.autostart,
    }


def _validate_config(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_CONFIG, **current}

    for key in (
        "respond_to_groups",
        "respond_to_dms",
        "auto_read",
        "typing_indicator",
        "ai_enabled",
        "ai_in_groups",
    ):
        if key in payload:
            merged[key] = bool(payload[key])

    if "command_prefix" in payload:
        prefix = str(payload["command_prefix"]).strip()[:3]
        if not prefix:
            raise ValidationError("Command prefix cannot be empty")
        merged["command_prefix"] = prefix

    for key, bounds in (
        ("outbound_per_minute", (MIN_PER_MINUTE, MAX_PER_MINUTE)),
        ("outbound_min_gap_ms", (MIN_GAP_MS, MAX_GAP_MS)),
        ("ai_history_turns", (0, 30)),
    ):
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{key} must be a number") from exc
            merged[key] = max(bounds[0], min(value, bounds[1]))

    for key in ("allowed_numbers", "blocked_numbers"):
        if key in payload:
            values = payload[key]
            if not isinstance(values, list):
                raise ValidationError(f"{key} must be a list")
            cleaned = []
            for entry in values:
                digits = re.sub(r"\D", "", str(entry))
                if 8 <= len(digits) <= 15:
                    cleaned.append(digits)
            merged[key] = sorted(set(cleaned))

    for key in ("ai_model", "ai_base_url", "ai_persona"):
        if key in payload:
            value = payload[key]
            merged[key] = str(value).strip()[:2000] if value else None

    return merged


def _validate_commands(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValidationError("commands must be a list")
    if len(payload) > 100:
        raise ValidationError("Too many commands (max 100)")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"\s+", "", str(item.get("name", "")).lower())
        if not name:
            raise ValidationError("Every command needs a name")
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
            raise ValidationError(f'Invalid command name "{name}"')
        if name in seen:
            raise ValidationError(f'Duplicate command "{name}"')
        seen.add(name)
        response = str(item.get("response", "")).strip()
        if not response:
            raise ValidationError(f'Command "{name}" needs a response')
        result.append(
            {
                "name": name,
                "response": response[:4000],
                "enabled": bool(item.get("enabled", True)),
                "exact": bool(item.get("exact", False)),
            }
        )
    return result
