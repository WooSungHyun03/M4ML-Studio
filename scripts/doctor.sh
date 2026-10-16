#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
STUDIO_RUNTIME="$(python3 "$STUDIO_ROOT/scripts/runtime_path.py")"
STUDIO_PYTHON="${STUDIO_PYTHON:-$STUDIO_RUNTIME/bin/python}"
if [[ ! -x "$STUDIO_PYTHON" ]]; then
  STUDIO_PYTHON=python3
fi
exec "$STUDIO_PYTHON" -m studio.doctor "$@"
