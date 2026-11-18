"""`apphost` command line: serve the panel, inspect the host, run projects."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import detect, sources
from .config import DISPLAY_NAME, VERSION, load_settings
from .db import App, Database
from .doctor import diagnose

cli = typer.Typer(
    add_completion=False, help=f"{DISPLAY_NAME} — run Node/Vite/React projects on Linux."
)
apps_cli = typer.Typer(help="Manage registered projects.")
cli.add_typer(apps_cli, name="apps")
console = Console()


def _db_and_settings():
    settings = load_settings()
    settings.prepare()
    return settings, Database(settings.database_path)


@cli.command()
def serve(
    host: str = typer.Option(None, help="Bind address (default 127.0.0.1)."),
    port: int = typer.Option(None, help="Port (default 8080)."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes."),
    open_browser: bool = typer.Option(False, "--open", help="Print the panel URL."),
) -> None:
    """Start the web panel and API."""
    import uvicorn

    settings = load_settings()
    settings.prepare()
    bind_host = host or settings.host
    bind_port = port or settings.port
    console.print(f"[bold]{DISPLAY_NAME}[/] v{VERSION}")
    console.print(f"  panel   http://{bind_host}:{bind_port}")
    console.print(f"  data    {settings.data_dir}")
    console.print(
        f"  auth    {'token required' if settings.auth_required else 'DISABLED (localhost only!)'}"
    )
    if settings.auth_required:
        token_path = settings.data_dir / "token"
        if token_path.exists():
            console.print(f"  token   {token_path} (login form on the panel)")
    if open_browser:
        console.print("  Open the URL above in your browser.")
    if reload:
        uvicorn.run(
            "apphost.api:create_app", factory=True, host=bind_host, port=bind_port, reload=False
        )
    else:
        from .api import create_app

        uvicorn.run(create_app(settings), host=bind_host, port=bind_port)


@cli.command()
def doctor() -> None:
    """Check that this machine can run Node/Vite/React projects."""
    settings, _ = _db_and_settings()
    report = diagnose(settings.data_dir, managers=settings.packages)
    for check in report.checks:
        mark = (
            "[green]ok[/]"
            if check.ok
            else ("[red]missing[/]" if check.required else "[yellow]warn[/]")
        )
        console.print(f"{mark:>16} {check.name:<10} {check.version or check.detail}")
        if not check.ok and check.hint:
            console.print(f"                 [dim]{check.hint}[/]")
    if report.ok:
        console.print("\n[green]This machine can install and run projects.[/]")
    else:
        console.print(
            "\n[red]Required tooling is missing:[/] "
            + ", ".join(c.name for c in report.missing_required)
        )
        raise typer.Exit(code=1)


@cli.command()
def version() -> None:
    """Print the host version."""
    console.print(f"{DISPLAY_NAME} {VERSION}")


@cli.command()
def inspect(
    path: str = typer.Argument(..., help="Project folder containing package.json."),
) -> None:
    """Show what the host would run for a folder (no side effects)."""
    try:
        plan = detect.analyse(Path(path))
    except detect.ProjectError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    table = Table("field", "value", title=str(plan.workdir))
    table.add_row("framework", plan.framework)
    table.add_row("package manager", plan.package_manager)
    table.add_row("install", plan.install_command)
    table.add_row("build", plan.build_command or "(none)")
    table.add_row("start", plan.start_command)
    table.add_row("port", str(plan.port))
    for note in plan.notes:
        table.add_row("note", note)
    console.print(table)


# -- apps ---------------------------------------------------------------
@apps_cli.command("list")
def apps_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """List registered projects."""
    _, db = _db_and_settings()
    apps = db.list_apps()
    if as_json:
        console.print_json(json.dumps([a.to_json() for a in apps]))
        return
    if not apps:
        console.print("No projects registered. Add one with: apphost apps add <path>")
        return
    table = Table("id", "name", "start command", "port", "source")
    for app in apps:
        table.add_row(app.id, app.name, app.start_command, str(app.port or "-"), app.source_kind)
    console.print(table)


@apps_cli.command("add")
def apps_add(
    path: str = typer.Argument(..., help="Folder containing package.json."),
    name: str = typer.Option("", help="Display name."),
) -> None:
    """Register a project folder."""
    settings, db = _db_and_settings()
    source = Path(path).expanduser().resolve()
    try:
        plan = detect.analyse(source)
    except detect.ProjectError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    app_id = plan.workdir.name.lower().replace(" ", "-") or "app"
    if db.id_taken(app_id):
        console.print(f"[red]{app_id} already registered.[/]")
        raise typer.Exit(code=1)
    db.add_app(
        App(
            id=app_id,
            name=name or plan.workdir.name,
            source_kind="folder",
            source_path=str(plan.workdir),
            workdir=str(plan.workdir),
            package_manager=plan.package_manager,
            install_command=plan.install_command,
            build_command=plan.build_command,
            start_command=plan.start_command,
            port=plan.port,
        )
    )
    console.print(f"[green]Added {app_id}[/] -> {plan.workdir}")


@apps_cli.command("rm")
def apps_rm(
    app_id: str = typer.Argument(...), delete_files: bool = typer.Option(False, "--files")
) -> None:
    """Remove a project from the host."""
    settings, db = _db_and_settings()
    app = db.get_app(app_id)
    if app is None:
        console.print(f"[red]No app '{app_id}'.[/]")
        raise typer.Exit(code=1)
    db.delete_app(app_id)
    if delete_files:
        target = Path(app.workdir)
        workspace = settings.workspace_dir.resolve()
        if target.resolve() != workspace and workspace in target.resolve().parents:
            shutil.rmtree(target, ignore_errors=True)
    console.print(f"[green]Removed {app_id}[/]")


@apps_cli.command("show")
def apps_show(app_id: str = typer.Argument(...)) -> None:
    """Print one project's configuration."""
    _, db = _db_and_settings()
    app = db.get_app(app_id)
    if app is None:
        console.print(f"[red]No app '{app_id}'.[/]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(app.to_json()))


@apps_cli.command("clone")
def apps_clone(
    url: str = typer.Argument(..., help="Git URL."),
    name: str = typer.Option("", help="Project name (defaults to the repository name)."),
) -> None:
    """Clone a repository into the workspace and register it."""
    import asyncio

    settings, db = _db_and_settings()
    label = name or Path(url.rstrip("/")).name.removesuffix(".git")
    app_id = label.lower().replace(" ", "-")
    if db.id_taken(app_id):
        console.print(f"[red]{app_id} already registered.[/]")
        raise typer.Exit(code=1)
    dest = settings.workspace_dir / app_id
    try:
        imported = asyncio.run(sources.clone(url, dest))
        plan = detect.analyse(imported.workdir)
    except (sources.ValidationError, detect.ProjectError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    db.add_app(
        App(
            id=app_id,
            name=label,
            source_kind="git",
            source_url=url,
            workdir=str(imported.workdir),
            package_manager=plan.package_manager,
            install_command=plan.install_command,
            build_command=plan.build_command,
            start_command=plan.start_command,
            port=plan.port,
        )
    )
    console.print(f"[green]Cloned {url} -> {imported.workdir}[/]")


def main() -> None:
    try:
        cli()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
