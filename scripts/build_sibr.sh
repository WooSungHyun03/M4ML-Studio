#!/usr/bin/env bash
# Reproducible build of the 2DGS-compatible SIBR remote Gaussian viewer for M4ML Studio.
#
#   ./scripts/build_sibr.sh [--jobs N]
#
# Source : Gaussian-Splatting-Monitor (the SIBR fork the 2DGS README points to), pinned commit,
#          plus patches/sibr/*.patch (Ubuntu 24.04: Embree 4 API, FFmpeg >= 5 encoder API).
# Builds : SIBR core + projects/basic + projects/remote (Release). No CUDA needed: the remote
#          viewer only displays frames rendered by the Object-Aware renderer process.
# Output : runtime/sibr/ (bin/SIBR_remoteGaussian_app, SIBR's own shared libraries, shaders,
#          resources, BUILD_INFO.json). Ubuntu system libraries (OpenGL, GLEW, GLFW, Boost,
#          OpenCV, assimp, Embree, FFmpeg) are NOT bundled; BUILD_INFO.json lists them and
#          `python -m studio.live_render --check-external` reports any that are missing.
# Nothing is installed system-wide and no sudo is used.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
JOBS="$(nproc)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

REPO="https://github.com/RongLiu-Leo/Gaussian-Splatting-Monitor.git"
COMMIT="2b6190c5c1c35b477a70da09dc9b720395ea6293"
SRC="${SIBR_SOURCE:-$ROOT/.build/gs-monitor}"
BUILD="$ROOT/.build/sibr-build"
OUT="${SIBR_OUTPUT:-$ROOT/runtime/sibr}"

for tool in git cmake ninja c++; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done

if [[ ! -d "$SRC/.git" ]]; then
  git clone "$REPO" "$SRC"
fi
git -C "$SRC" fetch --quiet origin "$COMMIT" || true
# Reset tracked SIBR sources to the pinned commit, then apply exactly our patches.
git -C "$SRC" checkout --quiet "$COMMIT" -- SIBR_viewers
git -C "$SRC" checkout --quiet "$COMMIT"
for patch in "$ROOT"/patches/sibr/*.patch; do
  git -C "$SRC" apply --check "$patch"
  git -C "$SRC" apply "$patch"
done

cmake -S "$SRC/SIBR_viewers" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_IBR_REMOTE=ON -DBUILD_IBR_BASIC=ON -DBUILD_IBR_ULR=OFF -DBUILD_IBR_DATASET_TOOLS=OFF
ninja -C "$BUILD" -j "$JOBS" install

INSTALL="$SRC/SIBR_viewers/install"   # SIBR always installs into its source tree
APP="$INSTALL/bin/SIBR_remoteGaussian_app"
[[ -x "$APP" ]] || { echo "build did not produce $APP" >&2; exit 1; }

STAGE="$(mktemp -d "$ROOT/.build/sibr-stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/bin" "$STAGE/licenses"
cp "$APP" "$STAGE/bin/"
# Bundle only libraries that resolve inside SIBR's install tree; keep their sonames.
LD_LIBRARY_PATH="$INSTALL/bin" ldd "$APP" | awk '/=> \// {print $3}' | while read -r lib; do
  case "$lib" in "$INSTALL"/*) cp -L "$lib" "$STAGE/bin/" ;; esac
done
strip --strip-unneeded "$STAGE"/bin/* 2>/dev/null || true
cp -r "$INSTALL/shaders" "$INSTALL/resources" "$STAGE/"
[[ -f "$INSTALL/ibr_resources.ini" ]] && cp "$INSTALL/ibr_resources.ini" "$STAGE/"
cp "$SRC/SIBR_viewers/LICENSE.md" "$STAGE/licenses/SIBR-LICENSE.md"
cp "$SRC/LICENSE.md" "$STAGE/licenses/Gaussian-Splatting-Monitor-LICENSE.md"

SYSTEM_LIBS="$(LD_LIBRARY_PATH="$STAGE/bin" ldd "$STAGE/bin/SIBR_remoteGaussian_app" | awk '/=> \// {print $3}' | grep -v "^$STAGE" | sort -u | tr '\n' ' ')"
python3 - "$STAGE" "$COMMIT" "$REPO" "$SYSTEM_LIBS" <<'PY'
import hashlib, json, pathlib, platform, subprocess, sys
stage, commit, repo, system = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4].split()
patches = sorted(pathlib.Path(stage).parents[1].glob("patches/sibr/*.patch"))
info = {
    "name": "SIBR_remoteGaussian_app (Gaussian-Splatting-Monitor remote viewer)",
    "repository": repo, "commit": commit,
    "patches": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in patches},
    "build_type": "Release", "compiler": subprocess.run(["c++", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
    "os": platform.platform(),
    "bundled": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((stage / "bin").iterdir())},
    "system_libraries": system,
    "license": "Inria non-commercial research and evaluation license (licenses/SIBR-LICENSE.md)",
}
(stage / "BUILD_INFO.json").write_text(json.dumps(info, indent=2))
PY
rm -rf "$OUT.new"
mv "$STAGE" "$OUT.new"
trap - EXIT
rm -rf "$OUT.old"
[[ -d "$OUT" ]] && mv "$OUT" "$OUT.old"
mv "$OUT.new" "$OUT"
rm -rf "$OUT.old"
echo "SIBR remote viewer staged in $OUT ($(du -sh "$OUT" | cut -f1))"
