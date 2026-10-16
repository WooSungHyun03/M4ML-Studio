#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
STUDIO_PYTHON="${STUDIO_PYTHON:-$STUDIO_ROOT/.runtime/bin/python}"
if [[ ! -x "$STUDIO_PYTHON" ]]; then
  STUDIO_PYTHON=python3
fi
exec "$STUDIO_PYTHON" -m studio.doctor "$@"
