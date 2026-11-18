"""Terminal dashboard built with Textual.

Runs against the same SQLite database as the web panel, so it can be used
over SSH without exposing any port.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from .ai import AiClient
from .config import VERSION, get_settings
from .db import Bot, Database
from .engine import Engine

STATUS_COLOURS = {
    "connected": "green",
    "qr": "yellow",
    "pairing": "yellow",
    "starting": "yellow",
    "reconnecting": "cyan",
    "stopped": "grey62",
    "logged_out": "orange3",
    "error": "red",
}


class BotTable(DataTable):
    """Bot list with vim-style navigation."""

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns("Bot", "Status", "Number", "In", "Out", "Commands", "AI")


class Dashboard(App):
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #bots { width: 60%; border: round $primary; }
    #side { width: 40%; }
    #detail { height: 1fr; border: round $secondary; padding: 0 1; }
    #log { height: 1fr; border: round $accent; }
    """

    BINDINGS = [
        ("s", "start_bot", "Start"),
        ("x", "stop_bot", "Stop"),
        ("r", "restart_bot", "Restart"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.settings.prepare()
        self.db = Database(self.settings.database_path)  # type: ignore[arg-type]
        self.engine = Engine(settings=self.settings, db=self.db, ai=AiClient(self.settings))
        self.selected_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield BotTable(id="bots")
            with Vertical(id="side"):
                yield Static("Select a bot", id="detail")
                yield RichLog(id="log", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "WhatsApp MD Bot Runner"
        self.sub_title = f"v{VERSION}"
        self.refresh_bots()
        self.set_interval(3.0, self.refresh_bots)

    # ------------------------------------------------------------- rendering
    def refresh_bots(self) -> None:
        table = self.query_one(BotTable)
        cursor = table.cursor_row
        table.clear()
        for bot in self.db.list_bots():
            colour = STATUS_COLOURS.get(bot.status, "white")
            table.add_row(
                bot.name,
                f"[{colour}]{bot.status}[/{colour}]",
                f"+{bot.identity_number}" if bot.identity_number else "-",
                str(bot.stats.get("messages_in", 0)),
                str(bot.stats.get("messages_out", 0)),
                str(bot.stats.get("commands_handled", 0)),
                "on" if bot.ai_enabled else "off",
                key=bot.id,
            )
        if table.row_count:
            table.move_cursor(row=min(cursor, table.row_count - 1))
            self.update_detail()

    def update_detail(self) -> None:
        table = self.query_one(BotTable)
        detail = self.query_one("#detail", Static)
        if not table.row_count:
            detail.update('No bots yet.\n\nCreate one with:\n  wa bot add "My Bot"')
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        bot_id = str(row_key.value)
        self.selected_id = bot_id
        bot = self.db.get_bot(bot_id)
        if bot is None:
            return
        usage = self.db.ai_usage_summary(bot_id)
        detail.update(
            f"[bold]{bot.name}[/bold]\n"
            f"id: {bot.id}\n"
            f"status: {bot.status}\n"
            f"number: {bot.identity_number or '-'}\n"
            f"errors: {bot.stats.get('errors', 0)}\n"
            f"ai replies: {bot.stats.get('ai_replies', 0)}\n"
            f"tokens: {usage['prompt_tokens'] + usage['output_tokens']}\n\n"
            + (f"[red]{bot.last_error}[/red]" if bot.last_error else "")
        )

    def write_log(self, message: str) -> None:
        self.query_one(RichLog).write(message)

    # --------------------------------------------------------------- events
    @on(DataTable.RowHighlighted, "#bots")
    def _row_highlighted(self) -> None:
        self.update_detail()

    # -------------------------------------------------------------- actions
    def _selected(self) -> Bot | None:
        bot_id = self.selected_id
        return self.db.get_bot(bot_id) if bot_id else None

    @work(exclusive=True)
    async def action_start_bot(self) -> None:
        bot = self._selected()
        if bot is None:
            return
        self.write_log(f"[cyan]starting {bot.name}…[/cyan]")
        try:
            await self.engine.start(bot.id)
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            self.write_log(f"[red]{exc}[/red]")
        self.refresh_bots()

    @work(exclusive=True)
    async def action_stop_bot(self) -> None:
        bot = self._selected()
        if bot is None:
            return
        await self.engine.stop(bot.id)
        self.write_log(f"[grey62]stopped {bot.name}[/grey62]")
        self.refresh_bots()

    @work(exclusive=True)
    async def action_restart_bot(self) -> None:
        bot = self._selected()
        if bot is None:
            return
        await self.engine.stop(bot.id)
        try:
            await self.engine.start(bot.id)
            self.write_log(f"[cyan]restarted {bot.name}[/cyan]")
        except Exception as exc:  # noqa: BLE001
            self.write_log(f"[red]{exc}[/red]")
        self.refresh_bots()

    async def on_unmount(self) -> None:
        await self.engine.stop_all()
        self.db.close()


def run_tui() -> None:
    Dashboard().run()


if __name__ == "__main__":
    run_tui()
