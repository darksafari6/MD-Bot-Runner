# WhatsApp MD Bot Runner Manager

A **Linux-native, all-Python** control panel and terminal app for running multiple
WhatsApp Multi-Device bots — with AI replies over any OpenAI-compatible model.

No Node.js. No Electron. No simulated states. If WhatsApp is unreachable, the bot says so.

```bash
git clone https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager.git
cd Whatsapp-MD-bot-Runner-Manager
./scripts/install.sh          # installs deps, creates .env, runs diagnostics
.venv/bin/wa serve            # http://127.0.0.1:8080
```

---

## Why the rewrite

This project has been through two honest corrections:

1. **It started as a mock.** The first version drew a dashboard and faked the QR code and
   connection with `setTimeout`. That was replaced with a real TypeScript/Baileys manager.
2. **Then it moved to Python.** The goal is a Linux-native, AI-centric tool, so the
   TypeScript/React tree was **deleted entirely**. Everything now runs on Python and Bash:
   the WhatsApp engine, the panel, the terminal UI, the CLI and the installer.

New in v3.0 alongside the port: **AI replies**, **SQLite persistence**, a **Textual TUI**,
a **`wa` CLI**, and a **systemd-aware Bash installer**.

---

## Features

**WhatsApp engine** — [neonize](https://github.com/neonize/neonize) (a Python binding over
`whatsmeow`), one client per bot: QR linking, phone-number pairing codes, automatic reconnect
with exponential backoff, unlinked-device detection with credential cleanup, presence/typing,
read receipts, and media kinds.

**AI replies** — a single OpenAI-compatible client. Point `AI_BASE_URL` at OpenAI, Groq,
Together, OpenRouter, vLLM, LM Studio or a local **Ollama** (`/v1`). Per-bot model, persona,
group toggle and memory depth. Tokens, latency and failures are recorded, and a **"Test
provider"** button performs a real round trip.

**No pretending.** With no provider configured, the AI tab shows an explicit error and the bot
answers nothing — it never fabricates a reply.

**Beyond commands** — command rules with `{{sender}}`, `{{args}}`, `{{bot}}`, `{{uptime}}`,
`{{commands}}`; group/DM toggles; allow/block lists; inbound fall-through to AI.

**Inbox** — send to any number or group from the panel, per-chat transcripts, and outbound
pacing (sliding window + minimum gap) so a number is not flagged for spam.

**Three interfaces** — FastAPI web panel (server-rendered HTMX, no JS build step),
a Textual terminal dashboard for SSH, and a Typer CLI for scripting.

**Operations** — SQLite in WAL mode, optional bearer-token auth, live SSE status, graceful
shutdown that closes every socket, Docker image, and a systemd unit with sandboxing.

---

## Install

### Requirements

| Requirement | Why |
|---|---|
| Python ≥ 3.10 | runtime |
| `libmagic1` | required by the WhatsApp engine |
| `ffmpeg` | media messages (text bots work without it) |

`./scripts/install.sh` installs these with `apt`, creates `.venv`, installs the package, writes
`.env`, and runs `wa doctor`.

```bash
./scripts/install.sh              # local virtualenv
./scripts/install.sh --systemd    # + system unit (root)
./scripts/install.sh --user       # + per-user unit (no root)
```

### Docker

```bash
docker compose up -d --build
# AI key via env, data on a named volume:
AI_API_KEY=sk-... docker compose up -d
```

### Manual

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
wa doctor
wa serve
```

---

## Usage

### Web panel

`wa serve` → <http://127.0.0.1:8080>. Create a bot, press **Start**, then scan the QR code
(rendered locally as inline SVG — the payload never leaves your host) or request a pairing
code.

Tabs per bot: **Overview · Inbox · Commands · Behaviour · AI**.

### Terminal UI

```bash
wa tui      # s = start, x = stop, r = restart, q = quit
```

Shares the same SQLite database as the panel, so it works over SSH with no open port.

### CLI

```bash
wa bot add "Support Bot"      # create
wa bot list                   # status table
wa bot commands support-bot   # command rules
wa bot messages support-bot   # recent traffic
wa ai check                   # round-trip the provider
wa ai ask "Summarise today"   # one-off prompt
wa doctor                     # dependency + config report
```

---

## AI configuration

Any OpenAI-compatible endpoint works; only the base URL and model change.

```bash
# OpenAI
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini

# Local Ollama — no API key required for loopback endpoints
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_MODEL=llama3.1
```

Per-bot overrides live in the **AI** tab (model, base URL, persona, memory turns, group
toggle). The panel reports a provider as configured **only** when a call could actually
succeed — a remote base URL without a key is reported as unconfigured, never as "ready".

---

## Configuration

`.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8080` | Bind address |
| `API_TOKEN` | *empty* | Bearer token required on `/api/*` |
| `WAMANAGER_DATA_DIR` | `./data` | SQLite database + WhatsApp sessions |
| `MAX_INSTANCES` | `10` | Concurrent bots |
| `LOG_LEVEL` | `INFO` | Verbosity |
| `AI_BASE_URL` | `https://api.openai.com/v1` | Provider endpoint |
| `AI_API_KEY` | *empty* | Provider key (loopback endpoints exempt) |
| `AI_MODEL` | `gpt-4o-mini` | Default model |
| `AI_TIMEOUT` | `60` | Request timeout (seconds) |

`/api/health` stays unauthenticated so container healthchecks work.

---

## HTTP API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Version, engine, AI status (public) |
| `GET` | `/api/bots` | List bots |
| `POST` | `/api/bots` | Create — JSON `{"name": ...}`, form field, or `?name=` |
| `PATCH` | `/api/bots/{id}` | Update name, config, commands |
| `DELETE` | `/api/bots/{id}` | Stop and delete |
| `POST` | `/api/bots/{id}/start\|stop\|restart\|logout` | Lifecycle |
| `GET` | `/api/bots/{id}/qr` | Current QR / pairing code |
| `POST` | `/api/bots/{id}/pairing-code` | `{"phone": "92300…"}` |
| `POST` | `/api/bots/{id}/messages` | `{"to": "+92300…" \| "…@g.us", "text": "…"}` |
| `GET` | `/api/bots/{id}/messages` | Transcript + throttle state |
| `GET` | `/api/bots/{id}/conversations` | One row per chat |
| `DELETE` | `/api/bots/{id}/messages\|memory` | Clear history / AI memory |
| `GET` | `/api/bots/{id}/ai/usage` | Tokens, calls, failures |
| `POST` | `/api/ai/check` | Live provider round trip |
| `GET` | `/api/events` | SSE status stream |

Interactive docs: <http://127.0.0.1:8080/docs>.

```bash
curl -X POST localhost:8080/api/bots -H 'Content-Type: application/json' \
  -d '{"name":"Support Bot"}'
curl -X POST localhost:8080/api/bots/support-bot/start
curl -X POST localhost:8080/api/bots/support-bot/messages \
  -H 'Content-Type: application/json' \
  -d '{"to":"+923001234567","text":"hello from the panel"}'
```

---

## Project layout

```
wamanager/
├── config.py      Environment + settings (no extra deps)
├── db.py          SQLite: bots, commands, messages, AI usage, memory
├── jid.py         Phone/jid parsing (pure)
├── throttle.py    Outbound pacing, injectable clock (pure)
├── commands.py    Command matching + templating (pure)
├── ai.py          OpenAI-compatible client, local-endpoint detection
├── engine.py      neonize lifecycle, reconnect, inbox, AI dispatch
├── api.py         FastAPI REST + HTMX pages
├── tui.py         Textual terminal dashboard
├── cli.py         Typer CLI (`wa`)
├── templates/     Jinja2 pages and HTMX partials
└── static/        CSS, app.js, vendored htmx.min.js (offline)
scripts/install.sh Bash installer + systemd unit
tests/             88 tests (unit, engine, HTTP, templates)
```

---

## Development

```bash
source .venv/bin/activate
pytest -q                  # 88 tests
ruff check wamanager tests
ruff format wamanager tests
wa serve --reload          # auto-reload
```

Tests never touch WhatsApp: the engine tests use protobuf-shaped fixtures, and the HTTP tests
stub the engine boundary. CI runs the suite on Python 3.10–3.12, lints, checks the installer
with `bash -n`, and smoke-tests a live server.

---

## Troubleshooting

**`neonize is not installed` / `failed to find libmagic`**
Install the system dependency: `sudo apt install libmagic1 ffmpeg`, then re-run
`./scripts/install.sh`. `wa doctor` names exactly what is missing.

**Media sending fails**
`ffmpeg` is missing. Text bots are unaffected.

**`409 This bot is not connected`**
Start and link the bot first. The Overview tab shows the current status and the real error.

**QR keeps rotating**
WhatsApp rotates QR codes every ~20 s; the panel refetches automatically. If it never
completes, check the host clock (NTP) and outbound HTTPS.

**`502 AI provider unreachable` / `401 API key`**
Check `AI_BASE_URL`, `AI_API_KEY` and `AI_MODEL`, then press **Test provider** in the AI tab.

---

## Limitations & responsible use

- neonize/whatsmeow is **unofficial**. Automating WhatsApp can get a number **banned** —
  use a dedicated number and human-like volumes (the pacing defaults exist for this reason).
- Bots run **in one process**. For very large fleets, run several instances with separate
  data directories behind a reverse proxy.
- Message history is stored in SQLite on your host. It is your data — back it up and protect
  it accordingly.
- Not affiliated with, endorsed by, or supported by WhatsApp or Meta.

## License

MIT — see [LICENSE](LICENSE). Vendored HTMX keeps its own MIT license
(`wamanager/static/HTMX-LICENSE`).

## Acknowledgements

[neonize](https://github.com/neonize/neonize) / [whatsmeow](https://github.com/tulir/whatsmeow),
FastAPI, Jinja2, HTMX, Textual, Typer and Rich.
