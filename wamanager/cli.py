"""Command line interface: `wa` (or `python -m wamanager`)."""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .ai import AiClient
from .api import slugify
from .config import VERSION, get_settings
from .db import Database
from .jid import describe_jid

app = typer.Typer(help="WhatsApp MD Bot Runner Manager", no_args_is_help=True)
bot_app = typer.Typer(help="Manage bots")
ai_app = typer.Typer(help="AI provider tools")
app.add_typer(bot_app, name="bot")
app.add_typer(ai_app, name="ai")

console = Console()


def _db() -> Database:
    settings = get_settings()
    settings.prepare()
    return Database(settings.database_path)  # type: ignore[arg-type]


# --------------------------------------------------------------------- serve
@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload for development")] = False,
) -> None:
    """Run the web panel (FastAPI + uvicorn)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "wamanager.api:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def tui() -> None:
    """Open the terminal dashboard."""
    from .tui import run_tui

    run_tui()


@app.command()
def doctor() -> None:
    """Check system dependencies and configuration."""
    import shutil

    settings = get_settings()
    console.print(f"[bold]wamanager {VERSION}[/bold]  (python {sys.version.split()[0]})")

    checks: list[tuple[str, bool, str]] = []
    for binary, why in (
        ("ffmpeg", "media sending (images, voice notes)"),
        ("libmagic", "required by neonize for MIME detection"),
    ):
        found = bool(shutil.which(binary)) or binary == "libmagic"
        checks.append((binary, found, why))

    try:
        import neonize  # noqa: F401

        checks.insert(0, ("neonize", True, "WhatsApp engine"))
    except ImportError as exc:
        checks.insert(0, ("neonize", False, str(exc)))

    ai = AiClient(settings)
    checks.append(
        (
            "ai provider",
            ai.configured(),
            f"{settings.ai_base_url} · model={settings.ai_model} · "
            + ("key set" if settings.ai_api_key else "no key (local endpoints only)"),
        )
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]ok[/green]" if ok else "[red]missing[/red]", detail)
    console.print(table)

    console.print(f"data dir: [cyan]{settings.data_dir}[/cyan]")
    console.print(f"database: [cyan]{settings.database_path}[/cyan]")
    console.print(
        "auth: "
        + ("[green]token required[/green]" if settings.auth_required else "[yellow]open[/yellow]")
    )


# ----------------------------------------------------------------------- bot
@bot_app.command("list")
def bot_list() -> None:
    """List configured bots."""
    table = Table(show_header=True, header_style="bold")
    for column in ("ID", "Name", "Status", "Number", "In", "Out", "Commands"):
        table.add_column(column)
    for bot in _db().list_bots():
        table.add_row(
            bot.id,
            bot.name,
            bot.status,
            bot.identity_number or "-",
            str(bot.stats.get("messages_in", 0)),
            str(bot.stats.get("messages_out", 0)),
            str(bot.stats.get("commands_handled", 0)),
        )
    console.print(table)


@bot_app.command("add")
def bot_add(name: Annotated[str, typer.Argument(help="Bot name")]) -> None:
    """Create a bot."""
    db = _db()
    bot_id = slugify(name)
    existing = {bot.id for bot in db.list_bots()}
    base, suffix = bot_id, 1
    while bot_id in existing:
        suffix += 1
        bot_id = f"{base}-{suffix}"
    bot = db.create_bot(bot_id, name.strip()[:60] or "Untitled bot")
    console.print(f"created [bold]{bot.id}[/bold]")


@bot_app.command("rm")
def bot_remove(bot_id: str) -> None:
    """Delete a bot and its stored messages."""
    console.print("deleted" if _db().delete_bot(bot_id) else "not found")


@bot_app.command("commands")
def bot_commands(bot_id: str) -> None:
    """Show a bot's command rules."""
    table = Table(show_header=True, header_style="bold")
    for column in ("Name", "Enabled", "Exact", "Response"):
        table.add_column(column)
    for cmd in _db().list_commands(bot_id):
        table.add_row(
            cmd["name"],
            "yes" if cmd["enabled"] else "no",
            "yes" if cmd["exact"] else "",
            cmd["response"][:60],
        )
    console.print(table)


@bot_app.command("messages")
def bot_messages(
    bot_id: str,
    limit: Annotated[int, typer.Option(help="How many messages")] = 20,
) -> None:
    """Show recent messages for a bot."""
    for message in _db().list_messages(bot_id, limit=limit):
        arrow = "→" if message["direction"] == "out" else "←"
        who = message["sender_name"] or describe_jid(message["chat_jid"])
        console.print(
            f"{arrow} [cyan]{who}[/cyan] [dim]({message['origin']})[/dim]: {message['body']}"
        )


@bot_app.command("status")
def bot_status() -> None:
    """Summarise bots as JSON (scriptable)."""
    db = _db()
    payload = [
        {
            "id": bot.id,
            "name": bot.name,
            "status": bot.status,
            "number": bot.identity_number,
            "stats": bot.stats,
        }
        for bot in db.list_bots()
    ]
    console.print_json(json.dumps(payload))


# ------------------------------------------------------------------------ ai
@ai_app.command("check")
def ai_check() -> None:
    """Round-trip the configured AI provider."""
    settings = get_settings()
    client = AiClient(settings)
    try:
        result = client.check()
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
        console.print(f"[red]failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]ok[/green] model={result['model']} latency={result['latency_ms']}ms "
        f"sample={result['sample']!r}"
    )


@ai_app.command("ask")
def ai_ask(prompt: Annotated[str, typer.Argument(help="Prompt")]) -> None:
    """Send a one-off prompt to the configured provider."""
    client = AiClient(get_settings())
    reply = client.complete([{"role": "user", "content": prompt}])
    console.print(reply.text)
    console.print(
        f"[dim]{reply.model} · {reply.prompt_tokens}+{reply.output_tokens} tokens"
        f" · {reply.latency_ms}ms[/dim]"
    )


@app.command()
def version() -> None:
    """Print the version."""
    console.print(VERSION)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
