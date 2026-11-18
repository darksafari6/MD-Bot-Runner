# WhatsApp MD Bot Runner Manager

A self-hosted control panel for running **multiple WhatsApp Multi-Device bots** on
[Baileys](https://github.com/WhiskeySockets/Baileys). Create a bot, link it by QR code or
pairing code, define commands, and watch every connection live from one dashboard.

![status](https://img.shields.io/badge/build-passing-brightgreen)
![node](https://img.shields.io/badge/node-%3E%3D20.11-blue)
![license](https://img.shields.io/badge/license-MIT-black)

---

## Why this rewrite

The previous version of this repository was a **UI mock**: it drew a dashboard and faked the
entire bot lifecycle with `setTimeout` — a hard-coded QR payload, a fake phone number, and a
"connected" state that never touched WhatsApp. Meanwhile the README documented a Next.js API,
a database and a plugin system that did not exist in the tree.

This version does the real thing, and the documentation below describes only what is actually
implemented.

| | Before | Now |
|---|---|---|
| WhatsApp connection | `setTimeout` pretending | Real Baileys sockets, one per bot |
| Linking | Fake QR string | Live QR + 8-digit pairing code |
| Backend | None | Express REST API + SSE log stream |
| Persistence | None | Atomic JSON store + Baileys credential files |
| Auth | None | Optional `API_TOKEN` (constant-time compare) |
| Reconnects | None | Exponential backoff, session restore, unlink detection |
| Tests | None | 108 unit, API and component tests |
| Desktop | `nodeIntegration: true` mock | Hardened Electron shell (sandboxed, isolated) |
| Deployment | Manual | `npm start`, Docker, Compose, CI |

---

## Features

**Bot management**
- Create unlimited bot instances (bounded by `MAX_INSTANCES`), each with its own session
- Start / stop / restart / unlink, per bot and in bulk via the API
- Automatic reconnect with exponential backoff; unlinked devices are detected and their stale
  credentials deleted
- Optional resume of connected bots after a manager restart
- Live per-bot counters: uptime, messages seen, replies sent, commands handled, errors

**Linking**
- Scan a QR code (rotated automatically) **or** use a phone-number pairing code
- Credentials persist in `data/sessions/<bot-id>/` so relinking is rare

**Inbox & sending**
- Send messages to any number or group from the panel, paced by a per-bot throttle
- Two-pane inbox: chat list with unread badges, transcript, live updates over SSE
- Every inbound and outbound message is recorded with direction and origin
  (`command` vs `manual`)
- History is memory-only by design — no transcript is written to disk

**Ban-safety pacing**
- Sliding-window rate limit with a minimum gap between sends, per bot
- Configurable limit (1–60/min) and gap (250 ms–30 s), clamped server-side
- Optional "typing…" presence with a length-based, jittered delay
- Replies that must wait report the delay instead of silently hanging

**Command engine**
- Per-bot prefix (default `!`), per-bot command list, enable/disable each rule
- Placeholders: `{{sender}}`, `{{args}}`, `{{instance}}`, `{{status}}`, `{{uptime}}`,
  `{{received}}`, `{{prefix}}`, `{{commands}}`
- Exact-match rules (reply to a bare word with no prefix)
- Group / DM toggles, allowlist and blocklist by number
- Optional auto-read receipts

**Operations**
- Real-time console via Server-Sent Events, with level/instance/text filters
- Health endpoint, structured logs, graceful shutdown that closes every socket
- Optional bearer-token auth; CORS allowlist for split deployments
- Docker image running as a non-root user with a healthcheck and a `/data` volume

---

## Quick start

```bash
git clone https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager.git
cd Whatsapp-MD-bot-Runner-Manager
npm install
npm run dev
```

`npm run dev` starts two processes:

| Process | URL | Notes |
|---|---|---|
| API + Baileys runtime | http://localhost:3001 | `tsx watch` |
| UI dev server | http://localhost:5173 | Vite, proxies `/api` to the API |

Open **http://localhost:5173**, click **New bot**, press **Start**, then scan the QR code or
request a pairing code.

### Production

```bash
npm run build     # bundles the UI into dist/ and the server into dist-server/
npm start         # single process on :3001 serving both API and UI
```

### Docker

```bash
docker compose up -d --build
# or
docker build -t wamanager .
docker run -d -p 3001:3001 -v wamanager-data:/data -e API_TOKEN=change-me wamanager
```

The `wamanager-data` volume holds WhatsApp credentials. Lose it and every bot must be relinked.

---

## Configuration

Copy `.env.example` to `.env`. Everything is optional.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `3001` | HTTP port |
| `HOST` | `0.0.0.0` | Bind address (`127.0.0.1` for loopback-only) |
| `API_TOKEN` | *empty* | When set, every `/api` request needs `Authorization: Bearer <token>` |
| `WAMANAGER_DATA_DIR` | `./data` | Sessions + `state.json` |
| `MAX_INSTANCES` | `10` | Hard cap on concurrent WhatsApp sockets |
| `LOG_BUFFER` | `2000` | In-memory log ring size |
| `LOG_LEVEL` | `info` | Manager verbosity |
| `BAILEYS_LOG_LEVEL` | `silent` | Baileys' own logging (`error`/`warn` for debugging) |
| `CORS_ORIGINS` | *empty* | Comma-separated extra origins allowed to call the API |

> ⚠️ **Security:** with `API_TOKEN` unset the panel is open to anyone who can reach the port.
> That is fine on `127.0.0.1`; set a token before exposing it to a network or the internet.
> Whoever can reach this panel controls the linked WhatsApp accounts.

---

## API

All routes are under `/api`. Errors return `{ "error": "..." }`.

| Method | Route | Description |
|---|---|---|
| `GET` | `/health` | Version, uptime, instance counts |
| `GET` | `/instances` | List bots (includes live QR when pending) |
| `POST` | `/instances` | Create a bot — body `{ "name": "Support" }` |
| `GET` | `/instances/:id` | Single bot |
| `PATCH` | `/instances/:id` | Update `name`, `config`, `commands` |
| `DELETE` | `/instances/:id` | Stop and delete |
| `POST` | `/instances/:id/start` | Open the socket |
| `POST` | `/instances/:id/stop` | Close the socket, keep the session |
| `POST` | `/instances/:id/restart` | Stop then start |
| `POST` | `/instances/:id/logout` | Unlink device and delete credentials |
| `GET` | `/instances/:id/qr` | Current QR + pairing code |
| `POST` | `/instances/:id/pairing-code` | Body `{ "phoneNumber": "92300…" }` |
| `POST` | `/instances/:id/messages` | Send a message — body `{ "to": "+92300…" \| "…@g.us", "text": "…" }` |
| `GET` | `/instances/:id/messages` | Recent messages (`?chatJid=&direction=&limit=`) plus throttle state |
| `DELETE` | `/instances/:id/messages` | Clear this bot's in-memory inbox |
| `GET` | `/instances/:id/messages/stream` | SSE: inbox changed |
| `GET` | `/instances/:id/conversations` | One row per chat, newest first |
| `POST` | `/instances/:id/conversations/:chatJid/read` | Clear unread badge |
| `GET` | `/logs?limit=&instanceId=` | Recent log lines |
| `GET` | `/logs/stream` | SSE stream (`?token=` for EventSource) |
| `POST` | `/logs/clear` | Clear the ring buffer |
| `GET`/`PATCH` | `/settings` | Manager preferences |

```bash
curl -X POST localhost:3001/api/instances \
  -H 'Content-Type: application/json' \
  -d '{"name":"Support Bot"}'

curl -X POST localhost:3001/api/instances/support-bot/start

curl -X PATCH localhost:3001/api/instances/support-bot \
  -H 'Content-Type: application/json' \
  -d '{"commands":[{"name":"hours","response":"We are open 9–5, {{sender}}."}]}'
```

---

## Project layout

```
├── shared/types.ts          # Types shared by server and UI (single source of truth)
├── server/
│   ├── index.ts             # Express bootstrap, static UI, graceful shutdown
│   ├── api.ts               # REST routes + validation
│   ├── runtime.ts           # Baileys socket lifecycle, reconnects, message dispatch
│   ├── commands.ts          # Pure command matching + template rendering (unit tested)
│   ├── jid.ts               # Phone/jid parsing and normalisation (pure)
│   ├── throttle.ts          # Outbound pacing policy (pure, clock injected)
│   ├── messages.ts          # Inbound extraction + disconnect policy (pure)
│   ├── inbox.ts             # Bounded in-memory message store + conversations
│   ├── message-stream.ts    # SSE fan-out for live inbox updates
│   ├── store.ts             # Atomic JSON persistence + normalisation
│   ├── logger.ts            # Ring buffer + SSE fan-out
│   ├── auth.ts              # Optional token auth, rate limiting
│   ├── baileys-logger.ts    # pino-compatible adapter that redacts QR/creds
│   └── config.ts            # Environment parsing
├── src/
│   ├── App.tsx              # Shell, hash routing, token gate, toasts
│   ├── state/AppStore.tsx   # Data layer (polling + SSE)
│   ├── views/               # Dashboard, InstanceDetail, Settings
│   ├── components/          # Cards, console, connect panel, command/config editors
│   └── lib/                 # API client, formatting helpers
├── electron/                # Hardened desktop shell (contextIsolation, sandbox)
├── test/                    # Vitest: 108 tests (logic, HTTP API, jsdom UI)
└── scripts/                 # dev runner + esbuild server bundler
```

---

## Development

```bash
npm run dev          # API + UI with hot reload
npm run typecheck    # tsc --noEmit (strict)
npm test             # 108 tests
npm run format       # prettier
npm run build        # production bundle
npm start            # run the production bundle
```

CI (`.github/workflows/ci.yml`) typechecks, tests, builds and smoke-tests `/api/health`
on every push and pull request.

---

## Troubleshooting

**“Cannot reach WhatsApp servers … TLS / network socket”**
The host running the manager cannot open a TLS connection to WhatsApp. Check outbound HTTPS,
DNS, corporate proxies and IPv6. This is the most common reason a container fails to link.

**QR appears and immediately expires**
WhatsApp rotates QR codes roughly every 20 seconds. The panel refetches automatically; if it
keeps rotating, your clock may be skewed — sync NTP.

**`Device was unlinked`**
Someone removed the linked device, or WhatsApp invalidated the session. The manager deletes the
dead credentials; press Start and scan again.

**A send takes several seconds / says "queued"**
That is the outbound throttle protecting the number. Raise **Max per minute** or lower
**Minimum gap** under Behaviour, or set `sendTypingIndicator` off to drop the typing pause.

**`409 This bot is not connected`**
The bot must be started *and* linked before the panel can send. Check the Overview tab for the
current status and any connection error.

**`Port 3001 is already in use`**
Set `PORT` in `.env`, or stop the other process.

**Bots stop after a host reboot**
Set `autostartConnectedInstances` (Settings) and run the manager as a service
(`docker compose` with `restart: unless-stopped`, or a systemd unit).

---

## Limitations & responsible use

- Baileys is an **unofficial** WhatsApp Web client. Automating WhatsApp can get a number
  **banned**; use a dedicated number and human-like volumes.
- This manager runs bots **in one process**. For hundreds of instances, run several managers
  behind a reverse proxy with separate data volumes.
- Logs **and message history** are in memory only; pipe stdout to your log stack if you need
  retention, and expect the inbox to empty on restart.
- Not affiliated with, endorsed by, or supported by WhatsApp or Meta.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built on [Baileys](https://github.com/WhiskeySockets/Baileys), React, Vite, Tailwind CSS and
Express.
