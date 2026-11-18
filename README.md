# App Host

**A Linux application server for JavaScript projects.** Point it at your code —
a folder, a git repo, or a zip — and it installs dependencies, starts the dev
server under supervision, and serves it behind one panel. Built for Node.js,
Vite and React; works for Next.js, Astro, Express and anything else with a
`package.json`.

No AI, no API keys, no cloud. Your code never leaves your machine.

```bash
git clone https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager.git
cd Whatsapp-MD-bot-Runner-Manager
./scripts/install.sh                                   # deps + venv + doctor
.venv/bin/apphost apps add ~/projects/whatsapp-bot     # register your project
.venv/bin/apphost serve                                # http://127.0.0.1:8080
```

Or install a package: `sudo apt install ./apphost_4.0.0_all.deb`

---

## What it actually does

1. **You give it code.** Any of three ways:
   - **Folder** — a directory on this machine that contains `package.json` (managed in place, so your edits and git state stay yours).
   - **Git** — `https://…`, `ssh://…` or `git@…`, shallow-cloned into the workspace.
   - **Upload** — a `.zip` / `.tar.gz`, extracted safely (archive traversal and symlinks are rejected).
2. **It works out how to run it.** Lockfile → package manager (`npm`/`pnpm`/`yarn`/`bun`), `vite.config.*` → Vite, `next.config.*` → Next.js, plus the port from your start script. Everything is shown before you save, and every command is editable.
3. **It installs and builds.** `npm install` / `pnpm install` / …, then an optional build, streamed to a per-app log with the exit code recorded.
4. **It starts and supervises.** The process runs in its own session so the whole tree (npm → node → esbuild) can be stopped; crashes are recorded with their exit code.
5. **It serves it.** Each app gets `/apps/<id>/` on the panel's origin, reverse-proxied to its own port. Absolute asset paths in HTML are rewritten so Vite/React apps work behind the prefix.

### Tested with a real Vite + React app

```
$ python3 scripts/smoke.py
==> panel on http://127.0.0.1:55357
    health: {"status":"ok","version":"4.0.0","node":true,...}
    registered 'smoke-app': npm run dev (port 5173)
    install: ok=True exit=0
    proxied page: 392 bytes
PASS: real project installed, started, and served through the proxy
```

That is `npm install` of React + Vite, a real dev server, and a real proxied page
— run by `scripts/smoke.py` in CI on every commit.

---

## Features

**Import & detection** — folder / git / zip; lockfile-based package manager detection; Vite, Next, CRA, Astro, Express and plain-Node recognition; port extraction from start scripts; start/install/build commands you can override.

**Process supervision** — one process tree per app, group SIGTERM then SIGKILL, crash exit codes surfaced, uptime, PID, live log tail, autostart on boot, and an honest `starting`/`running` distinction (an app is only `running` when its port accepts connections).

**Port handling that matches reality** — the host injects `PORT`, `VITE_PORT` and `APP_PORT`, then *checks which port the process actually listens on* (via `/proc`) and follows it. Vite ignores `PORT`; this is why that matters. A busy port moves instead of fighting another process.

**One origin** — `/apps/<id>/…` reverse proxy with HTML rewriting, `Location` rewriting, hop-by-hop header stripping, streaming, websockets for Vite HMR (via the same HTTP upgrade path), and per-app cookie isolation from the panel.

**Security defaults** — loopback binding, persistent token auth created on first run, path allow-listing, safe archive extraction, no shell (argv only, never `shell=True`), `no-new-privileges` in Docker, and a hardened systemd unit.

**Operations** — `.deb` package with systemd unit and maintainer scripts, Bash installer with `--system`/`--user` modes, Docker image with Node and Python, SQLite state, per-app log files, SSE status stream, JSON API, and an `apphost doctor` that tells you exactly what is missing.

---

## Install

### Packages

| Method | Command |
|---|---|
| Debian/Ubuntu | `sudo apt install ./apphost_4.0.0_all.deb` (build: `./packaging/build-deb.sh`) |
| Script, system-wide | `sudo ./scripts/install.sh --system` |
| Script, per-user | `./scripts/install.sh --user` |
| Script, dev checkout | `./scripts/install.sh` |
| Docker | `PROJECTS_DIR=~/projects docker compose up -d` |

### Toolchains

The host runs your code, so your code's runtime must exist:

| Tool | Needed for | Install |
|---|---|---|
| **Node.js ≥ 18** | every project | `sudo apt install nodejs npm` or `./scripts/install.sh --node` |
| npm / pnpm / yarn / bun | chosen by your lockfile | `corepack enable pnpm` etc. |
| git | cloning repositories | `sudo apt install git` |
| ffmpeg | projects that process media | `sudo apt install ffmpeg` |

`apphost doctor` reports each one, with the install command, and the panel shows
a banner instead of pretending a build will work.

---

## Using it

### Panel

`apphost serve` → <http://127.0.0.1:8080>. The token is in `<data>/token` (or
`APPHOST_TOKEN`); log in once and it is stored in a cookie.

Per app you get four tabs:

- **Overview** — status, PID, port, proxy URL, start/stop/restart, source, `git pull` for clones.
- **Run** — install and build with live output and exit codes.
- **Config** — package manager, commands, port, environment, autostart.
- **Logs** — streaming tail, refresh, clear on demand.

### CLI

```bash
apphost doctor                          # what can this machine run?
apphost inspect ~/projects/bot          # what would it run? (no side effects)
apphost apps add ~/projects/bot         # register a folder
apphost apps clone https://…/bot.git    # clone and register
apphost apps list                       # table of apps
apphost apps show bot                   # full config as JSON
apphost apps rm bot [--files]           # forget (or delete an uploaded copy)
apphost serve [--host 0.0.0.0] [--port 8080]
```

### HTTP API

All routes except `/api/health` require `Authorization: Bearer <token>`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | version, node presence, app counts (public) |
| `GET` | `/api/doctor` | toolchain and environment report |
| `GET` | `/api/toolchains` | package manager versions |
| `GET` | `/api/apps` | list apps with live state |
| `POST` | `/api/apps` | register (folder or git) |
| `POST` | `/api/apps/upload` | register from an archive (multipart) |
| `GET` | `/api/apps/inspect?path=` | detection preview for a folder |
| `GET`/`PATCH`/`DELETE` | `/api/apps/{id}` | read / update / remove (`?delete_files=true` for uploads) |
| `POST` | `/api/apps/{id}/install\|build` | run a task |
| `POST` | `/api/apps/{id}/start\|stop\|restart` | lifecycle |
| `POST` | `/api/apps/{id}/pull` | `git pull --ff-only` |
| `GET` | `/api/apps/{id}/logs?kind=app\|install\|build` | raw log text |
| `GET` | `/api/events` | SSE status stream |
| `ANY` | `/apps/{id}/…` | reverse proxy to the app |

```bash
TOKEN=$(cat ~/.local/share/apphost/token)
curl -s -X POST localhost:8080/api/apps \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"WhatsApp Bot","source":"folder","path":"/home/me/whatsapp-bot"}'
curl -s -X POST localhost:8080/api/apps/whatsapp-bot/install -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8080/api/apps/whatsapp-bot/start   -H "Authorization: Bearer $TOKEN"
```

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `APPHOST_HOST` | `127.0.0.1` | bind address |
| `APPHOST_PORT` | `8080` | port |
| `APPHOST_DATA_DIR` | `~/.local/share/apphost` (`/var/lib/apphost` for root) | database, logs, imported projects |
| `APPHOST_TOKEN` | auto-generated | API/panel access token |
| `APPHOST_AUTH` | on | set `0` to disable auth (only if already loopback-only) |
| `APPHOST_ROOTS` | `/` | colon-separated roots the panel may import from |
| `APPHOST_MAX_APPS` | `10` | concurrent managed projects |
| `APPHOST_INSTALL_TIMEOUT` | `1800` | seconds before an install is killed |
| `APPHOST_START_TIMEOUT` | `300` | seconds to wait for an app's port |
| `APPHOST_AUTOSTART` | on | start apps marked autostart when the host boots |

---

## How it works

```
apphost/
├── config.py     settings, data dir, token creation
├── db.py         SQLite: apps (configuration only)
├── detect.py     package manager / framework / port detection (pure)
├── sources.py    folder, git clone, safe zip/tar extraction
├── runner.py     process trees, logs, tasks, port discovery, reverse proxy
├── doctor.py     toolchain diagnostics
├── api.py        REST + HTMX panel + proxy routes
├── cli.py        `apphost` command
├── templates/    Jinja2 pages
└── static/       CSS, small JS, vendored HTMX (offline)
packaging/        .deb build (relocated venv, systemd unit, maintainer scripts)
scripts/          install.sh, smoke.py
tests/            unit + real-process + HTTP tests, with Vite/Node fixtures
```

Design rules this project follows:

- **Nothing is faked.** If Node is missing, the panel says so. If an app never opens a port, its state stays `starting` with the timeout error, never `running`.
- **Your folder is yours.** Folder imports are managed in place; nothing is copied, moved, or deleted without an explicit request.
- **argv, never a shell.** Commands are parsed with `shlex` and executed directly, so a project name cannot become a shell expansion.
- **Config in the database, state in memory.** A restart of the host never resurrects a stale PID.

---

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                    # 100 tests, including real Node processes
ruff check apphost tests
python scripts/smoke.py      # real npm install + Vite + proxy
./packaging/build-deb.sh     # build the .deb
```

The suite starts actual Node processes on real ports, registers projects over
HTTP, runs `npm install`, and asserts that a proxied page contains the app's
markup. Tests that need Node skip cleanly if it is absent.

---

## Limitations (read this)

- **One host, one user.** Apps run as the user running the panel. There is no per-app sandbox — treat panel access as shell access.
- **Dev servers, not production serving.** Vite's dev server is for development. Build a static bundle and serve it with a real web server for production.
- **No websocket proxying for arbitrary paths.** Vite's HMR works through the standard path; other websocket endpoints may need a direct port connection.
- **Uploads are capped** at 100 MiB and 50 000 files; use git for large repositories.
- **Linux only.** It depends on `systemd` conventions, `/proc` port discovery and POSIX process groups.

## License

MIT — see [LICENSE](LICENSE). Vendored HTMX keeps its own MIT license
(`apphost/static/HTMX-LICENSE`).
