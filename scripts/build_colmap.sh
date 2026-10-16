#!/usr/bin/env bash
# Reproducible CUDA-enabled COLMAP build for M4ML Studio.
#
#   ./scripts/build_colmap.sh [--profile dist|local] [--jobs N]
#
# dist  : portable build for many NVIDIA GPUs (sm_60 … sm_90 + PTX for newer GPUs).
# local : build only for the GPU(s) in this machine (CMAKE_CUDA_ARCHITECTURES=native).
#
# Output: runtime/colmap/  (bin/colmap, lib/ with bundled non-system shared libraries,
#         BUILD_INFO.json with commit, toolkit, architectures and linked libraries)
# Nothing is installed system-wide. The CUDA toolkit is taken from COLMAP_CUDA_ROOT
# (default: .build/cuda12, a private conda-forge CUDA 12.6 toolkit — see docs/GPU_COLMAP_BUILD.md).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE=dist
JOBS="$(nproc)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

COLMAP_REPO="https://github.com/colmap/colmap.git"
COLMAP_TAG="4.2.1"
COLMAP_COMMIT="bd1fcf654d2dd8fefa1466999c190a246f83f4b9"
CUDA_ROOT="${COLMAP_CUDA_ROOT:-$ROOT/.build/cuda12}"
SRC="$ROOT/.build/colmap-src"
BUILD="$ROOT/.build/colmap-build-$PROFILE"
STAGE="$ROOT/.build/colmap-install-$PROFILE"
OUT="${COLMAP_OUTPUT:-$ROOT/runtime/colmap}"

case "$PROFILE" in
  dist)  ARCHS="60-real;61-real;70-real;75-real;80-real;86-real;89-real;90" ;;
  local) ARCHS="native" ;;
  *) echo "profile must be dist or local" >&2; exit 2 ;;
esac

[[ -x "$CUDA_ROOT/bin/nvcc" ]] || { echo "nvcc not found in $CUDA_ROOT/bin (set COLMAP_CUDA_ROOT)" >&2; exit 1; }

if [[ ! -d "$SRC/.git" ]]; then
  git clone --depth 1 --branch "$COLMAP_TAG" "$COLMAP_REPO" "$SRC"
fi
actual="$(git -C "$SRC" rev-parse HEAD)"
if [[ "$actual" != "$COLMAP_COMMIT" ]]; then
  echo "COLMAP source is at $actual, expected $COLMAP_COMMIT (tag $COLMAP_TAG)" >&2
  exit 1
fi

# Minimal OpenImageIO (JPEG/PNG/TIFF/EXR) instead of the distro build that drags in
# OpenCV/FFmpeg/GDAL; see scripts/build_oiio_minimal.sh.
OIIO_PREFIX="${OIIO_PREFIX:-$ROOT/.build/oiio-install}"
if [[ ! -f "$OIIO_PREFIX/lib/cmake/OpenImageIO/OpenImageIOConfig.cmake" ]]; then
  OIIO_PREFIX="$OIIO_PREFIX" "$ROOT/scripts/build_oiio_minimal.sh"
fi

# Hermetic toolchain: only system compilers/libraries plus the chosen CUDA toolkit.
# User conda/miniforge prefixes must not leak headers or CMake packages into the build.
export PATH="$CUDA_ROOT/bin:/usr/local/bin:/usr/bin:/bin"
unset CONDA_PREFIX CMAKE_PREFIX_PATH LD_LIBRARY_PATH CPATH LIBRARY_PATH PKG_CONFIG_PATH
IGNORE_PREFIXES="$(ls -d "$HOME"/anaconda3 "$HOME"/miniconda3 "$HOME"/miniforge3 "$HOME"/mambaforge "$ROOT/.runtime" 2>/dev/null | paste -sd ";" || true)"
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$STAGE" \
  -DCMAKE_IGNORE_PREFIX_PATH="$IGNORE_PREFIXES" \
  -DCMAKE_PREFIX_PATH="$OIIO_PREFIX" \
  -DOpenImageIO_DIR="$OIIO_PREFIX/lib/cmake/OpenImageIO" \
  -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF \
  -DCMAKE_INSTALL_RPATH='$ORIGIN/../lib' \
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=OFF \
  -DCUDA_ENABLED=ON \
  -DCUDAToolkit_ROOT="$CUDA_ROOT" \
  -DCMAKE_CUDA_COMPILER="$CUDA_ROOT/bin/nvcc" \
  -DCMAKE_CUDA_ARCHITECTURES="$ARCHS" \
  -DGUI_ENABLED=OFF \
  -DOPENGL_ENABLED=OFF \
  -DONNX_ENABLED=OFF \
  -DCGAL_ENABLED=OFF \
  -DDOWNLOAD_ENABLED=OFF \
  -DTESTS_ENABLED=OFF \
  -DCCACHE_ENABLED=OFF \
  -DUNINSTALL_ENABLED=OFF
cmake --build "$BUILD" --parallel "$JOBS"
rm -rf "$STAGE"
cmake --install "$BUILD" >/dev/null

# Bundle: binary + every shared library that is not part of the base system ABI
# (glibc family) or the NVIDIA driver (libcuda is provided by the user's driver).
python3 "$ROOT/scripts/bundle_colmap.py" --stage "$STAGE" --out "$OUT" --cuda-root "$CUDA_ROOT" \
  --profile "$PROFILE" --archs "$ARCHS" --commit "$COLMAP_COMMIT" --tag "$COLMAP_TAG" \
  --lib-path "$OIIO_PREFIX/lib:$CUDA_ROOT/lib"
echo "COLMAP ($PROFILE) ready: $OUT/bin/colmap"
