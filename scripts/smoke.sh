#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$STUDIO_ROOT"
.runtime/bin/python -m unittest discover -s studio/tests -v
npm run build --prefix frontend
npm test --prefix frontend
CUDA_VISIBLE_DEVICES="${STUDIO_GPU:-0}" OMP_NUM_THREADS=4 .runtime/bin/python scripts/smoke_native.py
printf '%s\n' '단위 테스트·화면 빌드·CUDA 렌더러 검사 완료. 실제 COLMAP/SAM/학습/메시 E2E는 별도 데이터로 실행해야 합니다.'
