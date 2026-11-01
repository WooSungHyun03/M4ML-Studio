#!/usr/bin/env bash
# Undo deploy/web/scripts/install.sh (operator only; needs sudo). Dry run unless --apply.
# Keeps /srv/m4ml-web/data (service data) and the m4ml-web account unless --purge is added.
#
#   sudo deploy/web/scripts/uninstall.sh --apply           # stop and remove the service
#   sudo deploy/web/scripts/uninstall.sh --apply --purge   # also delete service data + account
#   sudo deploy/web/scripts/uninstall.sh --apply --rollback  # switch back to /srv/m4ml-web/app.prev
set -euo pipefail
APPLY=0; PURGE=0; ROLLBACK=0
for a in "$@"; do case "$a" in --apply) APPLY=1;; --purge) PURGE=1;; --rollback) ROLLBACK=1;; *) echo "unknown: $a" >&2; exit 2;; esac; done
SRV=/srv/m4ml-web
run() { echo "+ $*"; if [ "$APPLY" = 1 ]; then "$@"; fi; }
[ "$APPLY" = 1 ] && [ "$(id -u)" != 0 ] && { echo "--apply needs root (sudo)" >&2; exit 1; }

if [ "$ROLLBACK" = 1 ]; then
  [ -d "$SRV/app.prev" ] || { echo "no previous version at $SRV/app.prev" >&2; exit 1; }
  run systemctl stop m4ml-web-gateway.service
  run mv "$SRV/app" "$SRV/app.failed"
  run mv "$SRV/app.prev" "$SRV/app"
  run systemctl start m4ml-web-gateway.service
  echo "rolled back to $(cat "$SRV/app/COMMIT" 2>/dev/null || echo '?'); the failed copy is $SRV/app.failed"
  exit 0
fi

run systemctl disable --now m4ml-web-tunnel.service m4ml-web-gateway.service m4ml-web-backup.timer || true
for f in /etc/systemd/system/m4ml-web-tunnel.service /etc/systemd/system/m4ml-web-gateway.service /etc/systemd/system/m4ml-web-backup.service \
         /etc/systemd/system/m4ml-web-backup.timer /etc/tmpfiles.d/m4ml-gpu.conf; do
  [ -e "$f" ] && run rm -f "$f"
done
if [ -e /etc/apparmor.d/m4ml-bwrap ]; then
  run apparmor_parser -R /etc/apparmor.d/m4ml-bwrap || true
  run rm -f /etc/apparmor.d/m4ml-bwrap
fi
run rm -rf /usr/local/libexec/m4ml-web
run systemctl daemon-reload
run rm -rf "$SRV/app" "$SRV/app.prev" "$SRV/app.new" "$SRV/runtime" "$SRV/models"
if [ "$PURGE" = 1 ]; then
  run rm -rf "$SRV" /etc/m4ml-web /run/m4ml-gpu
  id m4ml-web >/dev/null 2>&1 && run userdel m4ml-web
  getent group m4ml-gpu >/dev/null && run groupdel m4ml-gpu
else
  echo "kept: $SRV/data, /etc/m4ml-web, account m4ml-web (add --purge to remove)"
fi
echo "backups of replaced system files: /var/backups/m4ml-web/"
