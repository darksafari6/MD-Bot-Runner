#!/usr/bin/env bash
# Build a .deb for App Host.
#
#   ./packaging/build-deb.sh            -> dist/apphost_<version>_all.deb
#   ./packaging/build-deb.sh 4.0.1      -> override the version
#
# The package is built from the working tree: a Python wheel is installed into
# /usr/lib/apphost/venv, the launcher goes to /usr/bin/apphost, and systemd
# gets a hardened unit. Requires dpkg-deb and a Python with `build`/hatchling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)}"
[ -n "$VERSION" ] || { echo "could not read version from pyproject.toml" >&2; exit 1; }

PKG="apphost"
ARCH="all"
OUT="$ROOT/dist"
STAGE="$OUT/stage"
DEB="$OUT/${PKG}_${VERSION}_${ARCH}.deb"
PYTHON="${PYTHON:-python3}"

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found (apt install dpkg-dev)" >&2; exit 1; }

echo "==> building $PKG $VERSION"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/lib/apphost" \
         "$STAGE/usr/lib/systemd/system" \
         "$STAGE/usr/share/doc/apphost" \
         "$STAGE/usr/share/applications" \
         "$STAGE/var/lib/apphost"

# ---- application ---------------------------------------------------------
# The venv is built at a staging path and then relocated, because a venv bakes
# absolute paths into bin/* shebangs and pyvenv.cfg. Every script must point at
# the final /usr/lib/apphost/venv or `apphost` cannot start after install.
VENV_REL="usr/lib/apphost/venv"
BUILD_VENV="$OUT/venv-build"
FINAL_PREFIX="/$VENV_REL"

echo "==> installing the Python package"
rm -rf "$BUILD_VENV"
"$PYTHON" -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install --quiet --upgrade pip wheel
"$BUILD_VENV/bin/pip" install --quiet "$ROOT"
"$BUILD_VENV/bin/python" -c "import apphost; print('   apphost', apphost.VERSION)"

find "$BUILD_VENV" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_VENV" -name "*.pyc" -delete 2>/dev/null || true
# direct_url.json records the build path; the package is a plain install.
rm -f "$BUILD_VENV"/lib/python*/site-packages/*.dist-info/direct_url.json

echo "==> relocating the venv to $FINAL_PREFIX"
python3 - "$BUILD_VENV" "$FINAL_PREFIX" <<'RELOCATE'
import sys
from pathlib import Path

venv, final = Path(sys.argv[1]), sys.argv[2]
old = str(venv)

# pyvenv.cfg / activate scripts / console-script shebangs all embed the path.
for path in venv.rglob("*"):
    if path.is_symlink() or not path.is_file():
        continue
    interesting = (
        path.suffix in {".cfg", ".json", ""}
        or path.name in {"activate", "activate.csh", "activate.fish", "RECORD", "pip3.11"}
    )
    if not interesting:
        continue
    try:
        data = path.read_bytes()
    except OSError:
        continue
    if old.encode() not in data:
        continue
    path.write_bytes(data.replace(old.encode(), final.encode()))

# The interpreter inside the venv is a symlink to the system python; leave it.
print(f"   rewrote paths in {sum(1 for _ in venv.rglob('*'))} entries")
RELOCATE

mkdir -p "$STAGE/$VENV_REL"
cp -a "$BUILD_VENV/." "$STAGE/$VENV_REL/"
"$STAGE/$VENV_REL/bin/python" - <<'VERIFY'
import sys
import apphost

print(f"   relocated interpreter: {sys.prefix}")
print(f"   importable: apphost {apphost.VERSION}")
VERIFY

ln -sf "$FINAL_PREFIX/bin/apphost" "$STAGE/usr/bin/apphost"

# ---- systemd unit --------------------------------------------------------
cat > "$STAGE/usr/lib/systemd/system/apphost.service" <<'UNIT'
[Unit]
Description=App Host — run Node/Vite/React projects on this machine
Documentation=https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=apphost
Group=apphost
Environment=APPHOST_HOST=127.0.0.1
Environment=APPHOST_PORT=8080
Environment=APPHOST_DATA_DIR=/var/lib/apphost
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/apphost serve
Restart=on-failure
RestartSec=3
KillMode=mixed
TimeoutStopSec=20

# Hardening. ProtectHome=read-only keeps /home readable so projects under a
# user's home can still be imported, but the service cannot write there.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
UNIT

# ---- desktop entry (optional convenience) --------------------------------
cat > "$STAGE/usr/share/applications/apphost.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=App Host
Comment=Run Node.js, Vite and React projects on this machine
Exec=xdg-open http://127.0.0.1:8080
Icon=utilities-terminal
Terminal=false
Categories=Development;
DESKTOP

# ---- docs ---------------------------------------------------------------
cp "$ROOT/README.md" "$STAGE/usr/share/doc/apphost/README.md"
cp "$ROOT/LICENSE" "$STAGE/usr/share/doc/apphost/copyright"
gzip -9n -c "$ROOT/README.md" > "$STAGE/usr/share/doc/apphost/README.md.gz"
rm "$STAGE/usr/share/doc/apphost/README.md"

# ---- maintainer scripts -------------------------------------------------
INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: ${PKG}
Version: ${VERSION}
Section: devel
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-venv, python3-pip, git, tar
Recommends: nodejs (>= 18), npm, unzip
Suggests: pnpm, yarn, ffmpeg
Installed-Size: ${INSTALLED_SIZE}
Maintainer: App Host contributors <noreply@example.com>
Homepage: https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager
Description: run Node.js, Vite and React projects from one panel
 App Host is a Linux application server for JavaScript projects. It imports a
 project from a folder, a git repository or an uploaded archive, detects the
 package manager and the Vite/React/Next scripts, installs dependencies, runs
 the dev server under supervision and reverse-proxies it under /apps/<id>/ so
 the panel and the app share one origin.
 .
 Features: process supervision with process-group shutdown, per-app logs,
 dependency and build tasks, loopback-only binding by default, token auth,
 local QR-free operation, and a systemd unit. No cloud service, no telemetry.
CONTROL

cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

getent group apphost >/dev/null || addgroup --system apphost
getent passwd apphost >/dev/null || \
  adduser --system --ingroup apphost --home /var/lib/apphost \
          --no-create-home --disabled-login --gecos "App Host" apphost

mkdir -p /var/lib/apphost
chown apphost:apphost /var/lib/apphost
chmod 700 /var/lib/apphost

if [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
  systemctl enable apphost.service || true
  echo "App Host installed. Start it with: systemctl start apphost"
  echo "Panel: http://127.0.0.1:8080  (token: /var/lib/apphost/token)"
fi

if ! command -v node >/dev/null 2>&1; then
  echo "NOTE: Node.js is not installed. JavaScript projects cannot run until you" >&2
  echo "      install it: sudo apt install nodejs npm   (Node 18 or newer)" >&2
fi

exit 0
POSTINST

cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then
  systemctl stop apphost.service || true
  systemctl disable apphost.service || true
fi
exit 0
PRERM

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
fi
if [ "$1" = "purge" ]; then
  echo "Data in /var/lib/apphost was kept (project sessions and tokens live there)."
  echo "Remove it with: sudo rm -rf /var/lib/apphost"
fi
exit 0
POSTRM

chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
chmod 644 "$STAGE/DEBIAN/control"

# ---- build ---------------------------------------------------------------
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f \( -name "*.py" -o -name "*.html" -o -name "*.css" -o -name "*.js" \) -exec chmod 644 {} + 2>/dev/null || true
# keep interpreter + console scripts executable, symlinks untouched
find "$STAGE/$VENV_REL/bin" -type f -exec chmod 755 {} +
# Pip's own bootstrap leaves caches with build paths; they are not needed at runtime.
find "$STAGE/$VENV_REL" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
chmod 644 "$STAGE/DEBIAN/control"

echo "==> packaging $DEB"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
echo "==> done: $DEB ($(du -h "$DEB" | cut -f1))"
echo
echo "Inspect:  dpkg-deb -I $DEB"
echo "Install:  sudo apt install $DEB"
echo "Remove:   sudo apt remove apphost"
