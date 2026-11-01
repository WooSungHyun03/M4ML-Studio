#!/usr/bin/env bash
# M4ML Studio Web — staging install / upgrade (operator only; needs sudo). Default is a dry run
# that prints every step; nothing changes until --apply. Never opens a tunnel or a firewall port.
#
#   deploy/web/scripts/install.sh                 # print the plan
#   sudo deploy/web/scripts/install.sh --apply    # do it (again for an upgrade)
#   sudo deploy/web/scripts/uninstall.sh --apply  # undo (keeps service data unless --purge)
#
# Leaves alone: the desktop install (~/.local/share/m4ml-studio), the desktop user's data,
# this checkout. The web service gets its own copies under /srv/m4ml-web. Every system file
# it replaces is first copied to /var/backups/m4ml-web/<time>/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
SRV=/srv/m4ml-web
LIBEXEC=/usr/local/libexec/m4ml-web
BACKUP=/var/backups/m4ml-web/$(date +%Y%m%d-%H%M%S)
GIT=(git -c safe.directory="$ROOT" -C "$ROOT")  # the checkout belongs to the operator, not root
COMMIT="$("${GIT[@]}" rev-parse HEAD)"
run() { echo "+ $*"; if [ "$APPLY" = 1 ]; then "$@"; fi; }
keep() {  # back up a system file before it is replaced
  if [ -e "$1" ]; then run install -d -m 0700 "$BACKUP"; run cp -a "$1" "$BACKUP/"; fi
}

echo "M4ML Studio Web staging install from $ROOT @ ${COMMIT:0:12} (apply=$APPLY)"
[ "$APPLY" = 1 ] && [ "$(id -u)" != 0 ] && { echo "--apply needs root (sudo)" >&2; exit 1; }
[ -f "$ROOT/frontend/dist/index.html" ] || { echo "build the UI first: (cd frontend && npm run build)" >&2; exit 1; }
[ -f "$ROOT/models/sam3.1/sam3.1_multiplex.pt" ] || { echo "SAM 3.1 checkpoint missing under models/sam3.1" >&2; exit 1; }

# 1) account and groups (no login shell, no home under /home)
getent group m4ml-gpu >/dev/null || run groupadd --system m4ml-gpu
id m4ml-web >/dev/null 2>&1 || run useradd --system --home-dir "$SRV" --shell /usr/sbin/nologin --user-group m4ml-web
run usermod -aG video,render,m4ml-gpu m4ml-web

# 2) folders: app/runtime/models read-only for the service, data writable
run install -d -o root -g m4ml-web -m 0750 "$SRV" "$SRV/runtime" "$SRV/models"
run install -d -o m4ml-web -g m4ml-web -m 0700 "$SRV/data"
run install -d -o root -g m4ml-web -m 0750 /etc/m4ml-web

# 3) application: exactly the committed tree (no datasets, evidence, local state) + built UI.
#    Built next to the running copy and swapped in; the previous copy stays as app.prev.
echo "+ git archive $COMMIT | tar -x -C $SRV/app.new"
if [ "$APPLY" = 1 ]; then
  rm -rf "$SRV/app.new"; install -d -o root -g m4ml-web -m 0750 "$SRV/app.new"
  "${GIT[@]}" archive "$COMMIT" | tar -x -C "$SRV/app.new"
fi
run cp -a "$ROOT/vendor/sam3/." "$SRV/app.new/vendor/sam3/"        # submodule with local patches
run cp -a "$ROOT/runtime/." "$SRV/app.new/runtime/"                # COLMAP / SIBR runtime (not in git)
run cp -a "$ROOT/frontend/dist" "$SRV/app.new/frontend/dist"       # built UI
run sh -c "echo $COMMIT > $SRV/app.new/COMMIT"
run rsync -a --delete "$ROOT/.runtime/" "$SRV/runtime/"            # research Python runtime copy
run install -d -o root -g m4ml-web -m 0750 "$SRV/models/sam3.1"
run install -o root -g m4ml-web -m 0640 "$ROOT/models/sam3.1/sam3.1_multiplex.pt" "$SRV/models/sam3.1/"
run chown -R root:m4ml-web "$SRV/app.new" "$SRV/runtime"
run chmod -R g+rX,g-w,o-rwx "$SRV/app.new" "$SRV/runtime"
if [ "$APPLY" = 1 ]; then
  rm -rf "$SRV/app.prev"; [ -d "$SRV/app" ] && mv "$SRV/app" "$SRV/app.prev"; mv "$SRV/app.new" "$SRV/app"
fi
echo "  UI bundle: $(sha256sum "$ROOT/frontend/dist/index.html" | cut -c1-16)"

# 4) configuration and secrets (credential file, never the environment file).
#    An existing gateway.env is kept: it holds the operator's choices (host name, site key).
[ -f /etc/m4ml-web/gateway.env ] || run install -o root -g m4ml-web -m 0640 "$ROOT/deploy/web/systemd/gateway.env.example" /etc/m4ml-web/gateway.env
[ -f /etc/m4ml-web/turnstile.secret ] || run install -o root -g root -m 0600 /dev/null /etc/m4ml-web/turnstile.secret
# Public name and Turnstile site key (both public values) when given:
#   sudo M4ML_PUBLIC_HOST=studio.example.com M4ML_TURNSTILE_SITEKEY=0x4AAA... install.sh --apply
setenv() {  # KEY VALUE: replace or append one line of gateway.env
  run sed -i "/^$1=/d" /etc/m4ml-web/gateway.env
  run sh -c "echo '$1=$2' >> /etc/m4ml-web/gateway.env"
}
if [ -n "${M4ML_PUBLIC_HOST:-}" ]; then
  [[ "$M4ML_PUBLIC_HOST" =~ ^[a-z0-9.-]+$ ]] || { echo "bad host name" >&2; exit 1; }
  keep /etc/m4ml-web/gateway.env
  setenv STUDIO_WEB_HOSTS "127.0.0.1,localhost,$M4ML_PUBLIC_HOST"
  setenv STUDIO_WEB_PUBLIC_HOST "$M4ML_PUBLIC_HOST"
  setenv STUDIO_WEB_TRUST_CLOUDFLARE 1   # the gateway listens on 127.0.0.1; only cloudflared reaches it
fi
if [ -n "${M4ML_TURNSTILE_SITEKEY:-}" ]; then
  [[ "$M4ML_TURNSTILE_SITEKEY" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "bad site key" >&2; exit 1; }
  setenv STUDIO_WEB_TURNSTILE_SITEKEY "$M4ML_TURNSTILE_SITEKEY"
  [ -s /etc/m4ml-web/turnstile.secret ] || echo "  WARNING: /etc/m4ml-web/turnstile.secret is empty: new sessions will be refused until it is filled"
fi

# 5) sandbox: a service-only bubblewrap copy, the only binary the AppArmor userns profile covers
run install -d -o root -g root -m 0755 "$LIBEXEC"
run install -o root -g m4ml-web -m 0750 /usr/bin/bwrap "$LIBEXEC/bwrap"
keep /etc/apparmor.d/m4ml-bwrap
run install -o root -g root -m 0644 "$ROOT/deploy/web/apparmor/m4ml-bwrap" /etc/apparmor.d/m4ml-bwrap
run apparmor_parser -r /etc/apparmor.d/m4ml-bwrap

# 6) shared GPU lock folder, service units, backup timer
keep /etc/tmpfiles.d/m4ml-gpu.conf
run install -o root -g root -m 0644 "$ROOT/deploy/web/tmpfiles.d/m4ml-gpu.conf" /etc/tmpfiles.d/m4ml-gpu.conf
run systemd-tmpfiles --create /etc/tmpfiles.d/m4ml-gpu.conf
for unit in m4ml-web-gateway.service m4ml-web-backup.service m4ml-web-backup.timer; do
  keep "/etc/systemd/system/$unit"
  run install -o root -g root -m 0644 "$ROOT/deploy/web/systemd/$unit" "/etc/systemd/system/$unit"
done
# The tunnel unit is installed always but enabled only once its token file is filled
# (sudo install -m 600 -o root /dev/stdin /etc/m4ml-web/tunnel.token, paste, Ctrl-D).
keep /etc/systemd/system/m4ml-web-tunnel.service
run install -o root -g root -m 0644 "$ROOT/deploy/web/systemd/m4ml-web-tunnel.service" /etc/systemd/system/m4ml-web-tunnel.service
run systemd-analyze verify /etc/systemd/system/m4ml-web-gateway.service
run systemctl daemon-reload
run systemctl enable m4ml-web-gateway.service m4ml-web-backup.timer
run systemctl restart m4ml-web-gateway.service
run systemctl start m4ml-web-backup.timer
if [ -s /etc/m4ml-web/tunnel.token ]; then
  run systemctl enable m4ml-web-tunnel.service
  run systemctl restart m4ml-web-tunnel.service
else
  echo "  tunnel not started: /etc/m4ml-web/tunnel.token is empty"
fi

# 7) checks (T10/T20 acceptance)
if [ "$APPLY" = 1 ]; then
  for _ in $(seq 60); do curl -sf -H 'Host: localhost' http://127.0.0.1:8800/api/web/ready && break; sleep 1; done; echo
  systemctl --no-pager --lines=0 status m4ml-web-gateway.service || true
fi
cat <<'EOF'
Verify next (as the operator, no sudo needed for most):
  sudo -u m4ml-web ls "$HOME"                          -> Permission denied
  curl -s -H 'Host: localhost' http://127.0.0.1:8800/api/web/ready   -> {"ready":true,...}
  systemd-analyze security m4ml-web-gateway.service
  web-harness/scripts/web_e2e.mjs against http://localhost:8800 (real GPU, sandbox=bwrap)
EOF
