#!/usr/bin/env bash
# Install WhatsApp MD Bot Runner Manager on a Linux host.
#
#   ./scripts/install.sh              # venv install in this checkout
#   ./scripts/install.sh --systemd    # also install + enable the systemd unit
#   ./scripts/install.sh --user       # per-user systemd unit (no root)
#
# Idempotent: safe to re-run after a git pull.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
INSTALL_SYSTEMD=0
USER_UNIT=0
SKIP_SYSTEM_DEPS=0

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --systemd) INSTALL_SYSTEMD=1 ;;
    --user)    INSTALL_SYSTEMD=1; USER_UNIT=1 ;;
    --no-system-deps) SKIP_SYSTEM_DEPS=1 ;;
    -h|--help)
      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

# ---------------------------------------------------------------- preflight
log "Checking prerequisites"
command -v python3 >/dev/null || die "python3 is required (>= 3.10)"
python3 - <<'PY' || die "Python 3.10 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
log "python3 $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

# ------------------------------------------------------------ system deps
if [[ "$SKIP_SYSTEM_DEPS" -eq 0 ]]; then
  if command -v apt-get >/dev/null; then
    SUDO=""
    [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null && SUDO="sudo"
    if ! dpkg -s libmagic1 >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null; then
      log "Installing system packages (needs sudo): libmagic1 ffmpeg"
      $SUDO apt-get update -qq
      $SUDO apt-get install -y -qq libmagic1 ffmpeg python3-venv >/dev/null
    else
      log "System packages already present"
    fi
  else
    warn "apt-get not found. Install 'libmagic' and 'ffmpeg' with your package manager."
  fi
fi

command -v ffmpeg >/dev/null || warn "ffmpeg missing: media sending will fail, text bots still work"

# ------------------------------------------------------------------- venv
if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtualenv at .venv"
  python3 -m venv "$VENV_DIR"
else
  log "Reusing existing virtualenv"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

log "Installing Python dependencies (this pulls the WhatsApp engine)"
python -m pip install --quiet --upgrade pip wheel
python -m pip install --quiet -e "${ROOT_DIR}"

# ------------------------------------------------------------------- env
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  log "Creating .env from template"
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
  chmod 600 "${ROOT_DIR}/.env"
else
  log ".env already exists, leaving it alone"
fi

log "Running diagnostics"
"${VENV_DIR}/bin/wa" doctor || warn "doctor reported problems (see above)"

# --------------------------------------------------------------- systemd
if [[ "$INSTALL_SYSTEMD" -eq 1 ]]; then
  UNIT_DIR="/etc/systemd/system"
  UNIT_NAME="wamanager.service"
  SERVICE_USER="$(id -un)"
  if [[ "$USER_UNIT" -eq 1 ]]; then
    UNIT_DIR="${HOME}/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
  else
    [[ "$(id -u)" -ne 0 ]] && die "--systemd needs root (use --user for a per-user unit)"
  fi

  log "Writing ${UNIT_DIR}/${UNIT_NAME}"
  cat > "${UNIT_DIR}/${UNIT_NAME}" <<UNIT
[Unit]
Description=WhatsApp MD Bot Runner Manager
Documentation=file://${ROOT_DIR}/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${ROOT_DIR}
EnvironmentFile=-${ROOT_DIR}/.env
ExecStart=${VENV_DIR}/bin/wa serve
Restart=on-failure
RestartSec=5
# WhatsApp credentials live in ./data — keep them private.
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only

[Install]
WantedBy=$([[ "$USER_UNIT" -eq 1 ]] && echo default.target || echo multi-user.target)
UNIT

  if [[ "$USER_UNIT" -eq 1 ]]; then
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT_NAME"
    log "Enabled as a user service. Logs: journalctl --user -u ${UNIT_NAME} -f"
  else
    systemctl daemon-reload
    systemctl enable --now "$UNIT_NAME"
    log "Enabled system service. Logs: journalctl -u ${UNIT_NAME} -f"
  fi
fi

cat <<DONE

$(log "Installed")

  Start the panel:   ${VENV_DIR}/bin/wa serve
  Terminal UI:       ${VENV_DIR}/bin/wa tui
  Diagnostics:       ${VENV_DIR}/bin/wa doctor
  Then open:         http://127.0.0.1:8080

  Activate the venv for the short command: source ${VENV_DIR}/bin/activate && wa --help

DONE
