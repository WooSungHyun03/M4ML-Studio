#!/usr/bin/env bash
# Daily copy of gateway.sqlite (sessions, slots, leases, audit — no photos, no cookie
# secrets: only their hashes). Keeps 7 days; photos and projects are never backed up.
set -euo pipefail
dir="$1"; mkdir -p "$dir"; chmod 700 "$dir"
py="${STUDIO_WEB_PYTHON:-/srv/m4ml-web/runtime/bin/python}"
"$py" -m studio_web.admin backup "$dir/gateway-$(date +%Y%m%d-%H%M%S).sqlite"
find "$dir" -name 'gateway-*.sqlite' -mtime +7 -delete
