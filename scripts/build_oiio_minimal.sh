#!/usr/bin/env bash
# Minimal OpenImageIO for the bundled COLMAP: JPEG / PNG / TIFF / OpenEXR only.
# Ubuntu's libopenimageio pulls in OpenCV, FFmpeg (incl. GPL x264/x265), GDAL, OpenVDB…
# none of which COLMAP needs; this keeps the redistributed runtime small and its license
# surface limited (OIIO itself: Apache-2.0).
#   ./scripts/build_oiio_minimal.sh   → .build/oiio-install
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="v2.5.19.1"
SRC="$ROOT/.build/oiio-src"
BUILD="$ROOT/.build/oiio-build"
PREFIX="${OIIO_PREFIX:-$ROOT/.build/oiio-install}"
JOBS="${JOBS:-$(nproc)}"
export PATH="/usr/local/bin:/usr/bin:/bin"
unset CONDA_PREFIX CMAKE_PREFIX_PATH LD_LIBRARY_PATH CPATH LIBRARY_PATH PKG_CONFIG_PATH
IGNORE_PREFIXES="$(ls -d "$HOME"/anaconda3 "$HOME"/miniconda3 "$HOME"/miniforge3 "$HOME"/mambaforge "$ROOT/.runtime" 2>/dev/null | paste -sd ";" || true)"
[[ -d "$SRC/.git" ]] || git clone --depth 1 --branch "$TAG" https://github.com/AcademySoftwareFoundation/OpenImageIO.git "$SRC"
echo "OpenImageIO $(git -C "$SRC" describe --tags) $(git -C "$SRC" rev-parse HEAD)"
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_IGNORE_PREFIX_PATH="$IGNORE_PREFIXES" \
  -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF \
  -DOpenImageIO_BUILD_MISSING_DEPS=fmt\;Robinmap \
  -DOIIO_BUILD_TOOLS=OFF -DOIIO_BUILD_TESTS=OFF -DBUILD_DOCS=OFF -DINSTALL_DOCS=OFF \
  -DUSE_PYTHON=OFF -DUSE_QT=OFF -DUSE_OPENGL=OFF \
  -DUSE_FFMPEG=OFF -DUSE_OPENCV=OFF -DUSE_OPENVDB=OFF -DUSE_PTEX=OFF -DUSE_LIBRAW=OFF \
  -DUSE_DCMTK=OFF -DUSE_GIF=OFF -DUSE_LIBHEIF=OFF -DUSE_OPENJPEG=OFF -DUSE_JXL=OFF \
  -DUSE_WEBP=OFF -DUSE_FREETYPE=OFF -DUSE_OPENCOLORIO=OFF -DUSE_OCIO=OFF -DUSE_TBB=OFF \
  -DUSE_Nuke=OFF -DUSE_R3DSDK=OFF -DUSE_JPEGTURBO=ON -DUSE_PNG=ON \
  -DOIIO_INTERNALIZE_FMT=ON -DLINKSTATIC=OFF
cmake --build "$BUILD" --parallel "$JOBS"
cmake --install "$BUILD" >/dev/null
echo "minimal OpenImageIO installed in $PREFIX"
