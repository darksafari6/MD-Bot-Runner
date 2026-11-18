#!/usr/bin/env bash
# App Host installer for Debian/Ubuntu and other Linux distributions.
#
#   ./scripts/install.sh              local virtualenv in the current checkout
#   ./scripts/install.sh --system    install to /opt + systemd system unit (root)
#   ./scripts/install.sh --user      install to ~/.local + systemd user unit
#   ./scripts/install.sh --node      also install Node.js LTS from NodeSource
#
# Idempotent: safe to re-run after an update.
set -euo pipefail

APP_NAME="apphost"
DISPLAY_NAME="App Host"
INSTALL_DIR_DEFAULT="/opt/apphost"
USER_DIR="${HOME}/.local/share/apphost-venv"

MODE="local"
WITH_NODE=0
HOST="127.0.0.1"
PORT="8080"

CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
info()  { printf '%s==>%s %s\n' "$CYAN" "$RESET" "$*"; }
ok()    { printf '%s  ok%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '%swarn%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()   { printf '%serr %s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Options:
  --system           install to ${INSTALL_DIR_DEFAULT} + system systemd unit (needs root)
  --user             install to a user venv + systemd --user unit
  --local            (default) virtualenv in this checkout, no service
  --node             install Node.js LTS from NodeSource when node is missing
  --host HOST        bind address for the service (default ${HOST})
  --port PORT        port for the service (default ${PORT})
  --no-service       install files only
  -h, --help         this text
EOF
}

SERVICE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --system) MODE="system" ;;
    --user) MODE="user" ;;
    --local) MODE="local" ;;
    --node) WITH_NODE=1 ;;
    --no-service) SERVICE=0 ;;
    --host) HOST="${2:?--host needs a value}"; shift ;;
    --port) PORT="${2:?--port needs a value}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/pyproject.toml" ] || die "run this from the repository (pyproject.toml not found in $ROOT)"

have() { command -v "$1" >/dev/null 2>&1; }
as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; elif have sudo; then sudo "$@"; else die "need root for: $*"; fi; }

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
install_system_packages() {
  if have apt-get; then
    local missing=()
    for pkg in python3 python3-venv python3-pip git tar; do
      dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      info "installing: ${missing[*]}"
      as_root apt-get update -qq
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
    fi
    ok "python, venv, pip, git, tar present"
  elif have dnf; then
    as_root dnf install -y -q python3 python3-pip git tar
  elif have pacman; then
    as_root pacman -Sy --noconfirm --needed python python-pip git tar
  else
    warn "unknown package manager; ensure python3 (>=3.10), venv, pip, git are installed"
  fi
}

install_node() {
  if have node; then
    local major
    major="$(node --version | sed 's/^v\([0-9]*\).*/\1/')"
    if [ "${major:-0}" -ge 18 ]; then
      ok "node $(node --version)"
      return
    fi
    warn "node $(node --version) is too old (need 18+)"
  else
    warn "node is not installed — apps cannot run without it"
  fi

  if [ "$WITH_NODE" -eq 0 ]; then
    cat <<EOF
${DIM}Install Node.js 18+ yourself, or re-run with --node to let this script do it:
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
or use nvm: https://github.com/nvm-sh/nvm${RESET}
EOF
    return
  fi

  info "installing Node.js 20 LTS from NodeSource"
  if have apt-get; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | as_root bash -
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs
  else
    die "automatic Node install is only implemented for apt; install node 20 manually"
  fi
  ok "node $(node --version)"
}

# ---------------------------------------------------------------------------
# 2. Python environment
# ---------------------------------------------------------------------------
make_venv() {
  local dir="$1"
  if [ -d "$dir" ] && [ -x "$dir/bin/python" ]; then
    ok "reusing venv at $dir"
  else
    info "creating venv at $dir"
    python3 -m venv "$dir" || die "python3-venv is missing (apt install python3-venv)"
  fi
  "$dir/bin/pip" install --quiet --upgrade pip wheel
}

install_app() {
  local venv="$1"
  info "installing $APP_NAME from $ROOT"
  "$venv/bin/pip" install --quiet --upgrade "$ROOT"
  "$venv/bin/python" -c "import apphost" || die "import failed after install"
  ok "$("$venv/bin/apphost" version)"
}

# ---------------------------------------------------------------------------
# 3. Service
# ---------------------------------------------------------------------------
write_unit() {
  local bin="$1" runs_as="$2" target="$3" kind="$4"
  local data_dir
  if [ "$kind" = "system" ]; then
    data_dir="/var/lib/apphost"
  else
    data_dir="${HOME}/.local/share/apphost"
  fi

  local extra=""
  if [ "$kind" = "system" ]; then
    extra="$(cat <<'EOF'
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only
RestrictSUIDSGID=yes
EOF
)"
  fi

  as_root tee "$target" >/dev/null <<EOF
[Unit]
Description=${DISPLAY_NAME} — run Node/Vite/React projects
Documentation=https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${runs_as}
Environment=APPHOST_HOST=${HOST}
Environment=APPHOST_PORT=${PORT}
Environment=APPHOST_DATA_DIR=${data_dir}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${bin} serve
Restart=on-failure
RestartSec=3
KillMode=mixed
TimeoutStopSec=20
${extra}
[Install]
WantedBy=$([ "$kind" = "system" ] && echo multi-user.target || echo default.target)
EOF
  ok "unit written to $target"
}

setup_system_mode() {
  [ "$(id -u)" -eq 0 ] || die "--system needs root (try sudo ./scripts/install.sh --system)"
  install_system_packages
  install_node
  local venv="${INSTALL_DIR_DEFAULT}/venv"
  mkdir -p "$INSTALL_DIR_DEFAULT"
  make_venv "$venv"
  install_app "$venv"
  id -u apphost >/dev/null 2>&1 || useradd --system --home /var/lib/apphost --shell /usr/sbin/nologin apphost
  mkdir -p /var/lib/apphost
  chown -R apphost:apphost /var/lib/apphost
  chmod 700 /var/lib/apphost
  if [ "$SERVICE" -eq 1 ] && have systemctl; then
    write_unit "${venv}/bin/apphost" apphost /etc/systemd/system/apphost.service system
    systemctl daemon-reload
    systemctl enable --now apphost.service
    ok "apphost.service enabled"
    printf '\nOpen http://%s:%s and use the token from /var/lib/apphost/token\n' "$HOST" "$PORT"
  fi
}

setup_user_mode() {
  install_system_packages
  install_node
  make_venv "$USER_DIR"
  install_app "$USER_DIR"
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  if [ "$SERVICE" -eq 1 ] && have systemctl; then
    as_root() { "$@"; }
    write_unit "${USER_DIR}/bin/apphost" "$(id -un)" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/apphost.service" user
    systemctl --user daemon-reload || warn "systemd --user unavailable in this session"
    systemctl --user enable --now apphost.service || warn "could not start the user unit now"
    ok "user unit installed; survives login with: loginctl enable-linger $(id -un)"
  fi
}

setup_local_mode() {
  install_system_packages
  install_node
  local venv="$ROOT/.venv"
  make_venv "$venv"
  install_app "$venv"
  cat <<EOF

${GREEN}Installed.${RESET} Start it with:
  ${venv}/bin/apphost serve
  ${venv}/bin/apphost doctor
  ${venv}/bin/apphost apps add /path/to/your/whatsapp-bot

Panel: http://${HOST}:${PORT}
EOF
}

# ---------------------------------------------------------------------------
case "$MODE" in
  system) setup_system_mode ;;
  user) setup_user_mode ;;
  local) setup_local_mode ;;
esac

if [ -x "$ROOT/.venv/bin/apphost" ] || [ "$MODE" != "local" ]; then
  echo
  info "diagnostics"
  "${ROOT}/.venv/bin/apphost" doctor 2>/dev/null || \
    "${INSTALL_DIR_DEFAULT}/venv/bin/apphost" doctor 2>/dev/null || \
    "${USER_DIR}/bin/apphost" doctor 2>/dev/null || true
fi
