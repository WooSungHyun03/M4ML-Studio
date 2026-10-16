#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
STUDIO_RUNTIME="$(python3 "$STUDIO_ROOT/scripts/runtime_path.py")"
if [[ ! -x "$STUDIO_RUNTIME/bin/python" || ! -f frontend/dist/index.html ]]; then
  printf '%s\n' '먼저 ./scripts/setup.sh로 설치와 화면 빌드를 완료하세요.' >&2
  exit 1
fi
STUDIO_PORT="${STUDIO_PORT:-8765}"
if [[ ! "$STUDIO_PORT" =~ ^[0-9]+$ ]] || (( STUDIO_PORT < 1024 || STUDIO_PORT > 65535 )); then
  printf '%s\n' '포트는 1024~65535 사이의 숫자여야 합니다.' >&2
  exit 1
fi
printf 'M4ML Studio: http://127.0.0.1:%s\n종료하려면 Ctrl+C를 누르세요. 실행 중인 작업에 중지를 요청합니다.\n' "$STUDIO_PORT"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
exec "$STUDIO_RUNTIME/bin/python" -m uvicorn studio.api:app --host 127.0.0.1 --port "$STUDIO_PORT" --no-access-log --timeout-graceful-shutdown 10
