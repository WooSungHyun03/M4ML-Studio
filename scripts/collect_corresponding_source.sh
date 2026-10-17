#!/usr/bin/env bash
# Corresponding source for the copyleft parts of the bundled runtime (release asset).
#
#   ./scripts/collect_corresponding_source.sh OUT_DIR
#
# runtime/colmap redistributes Ubuntu 24.04 binaries of SuiteSparse (CHOLMOD/SPQR: GPL-2+,
# other modules LGPL/BSD) and the GCC 14 runtime (libstdc++, libgcc_s, libgomp, libgfortran:
# GPL-3+ with the GCC Runtime Library Exception), linked into COLMAP and Ceres. This script
# assembles the complete corresponding source of that combined work:
#   * the exact Ubuntu source packages (.dsc + orig + debian) the bundled libraries were built
#     from (versions read from licenses/colmap-runtime/inventory.json),
#   * COLMAP at the pinned commit and the custom OpenImageIO build source (git archive),
#   * the build scripts used (scripts/build_colmap.sh, scripts/build_oiio_minimal.sh),
# and writes SHA256SUMS. Downloads come only from archive.ubuntu.com (signed .dsc kept).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?usage: collect_corresponding_source.sh OUT_DIR}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
mkdir -p "$OUT/ubuntu-source" "$OUT/upstream" "$OUT/build-scripts"
POOL="http://archive.ubuntu.com/ubuntu/pool"

fetch_pkg() {  # component/letter/source  version  orig-version
  local dir="$1" ver="$2" orig="$3" name="${1##*/}"
  local files=("${name}_${ver}.dsc" "${name}_${ver}.debian.tar.xz")
  local listing
  listing="$(curl -fsS "$POOL/$dir/")"
  local o
  local re_orig="${orig//./\\.}"
  re_orig="${re_orig//+/\\+}"
  o="$(grep -oE "${name}_${re_orig}\.orig\.tar\.[a-z]+" <<<"$listing" | head -1)"
  [[ -n "$o" ]] || { echo "orig tarball for $name $orig not found" >&2; exit 1; }
  files+=("$o")
  for f in "${files[@]}"; do
    [[ -f "$OUT/ubuntu-source/$f" ]] || curl -fsS -o "$OUT/ubuntu-source/$f" "$POOL/$dir/${f//+/%2B}"
  done
}

fetch_pkg main/s/suitesparse "7.6.1+dfsg-1build1" "7.6.1+dfsg"
fetch_pkg main/g/gcc-14 "14.2.0-4ubuntu2~24.04.1" "14.2.0"
fetch_pkg universe/c/ceres-solver "2.2.0+dfsg-4.1ubuntu2" "2.2.0+dfsg"

COLMAP_COMMIT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["colmap_commit"])' "$ROOT/licenses/colmap-runtime/inventory.json")"
git -C "$ROOT/.build/colmap-src" archive --format=tar.gz --prefix="colmap-$COLMAP_COMMIT/" -o "$OUT/upstream/colmap-$COLMAP_COMMIT.tar.gz" "$COLMAP_COMMIT"
if [[ -d "$ROOT/.build/oiio-src/.git" ]]; then
  OIIO="$(git -C "$ROOT/.build/oiio-src" rev-parse HEAD)"
  git -C "$ROOT/.build/oiio-src" archive --format=tar.gz --prefix="OpenImageIO-$OIIO/" -o "$OUT/upstream/OpenImageIO-$OIIO.tar.gz" "$OIIO"
fi
cp "$ROOT/scripts/build_colmap.sh" "$ROOT/scripts/build_oiio_minimal.sh" "$ROOT/scripts/bundle_colmap.py" "$OUT/build-scripts/"
cp "$ROOT/runtime/colmap/BUILD_INFO.json" "$ROOT/licenses/colmap-runtime/inventory.json" "$OUT/"
cat > "$OUT/README.txt" <<EOF
M4ML Studio — corresponding source for the bundled COLMAP runtime (runtime/colmap)

The release package redistributes, unmodified, Ubuntu 24.04 shared libraries listed in
inventory.json together with a COLMAP executable built by build-scripts/build_colmap.sh.
Copyleft components and their exact source packages (from archive.ubuntu.com):
  SuiteSparse 1:7.6.1+dfsg-1build1 (CHOLMOD, SPQR: GPL-2.0-or-later; others LGPL/BSD)
  GCC 14 14.2.0-4ubuntu2~24.04.1 runtime libraries (GPL-3.0-or-later WITH GCC-exception-3.1)
  Ceres Solver 2.2.0+dfsg-4.1ubuntu2 (BSD-3-Clause; links SuiteSparse)
COLMAP ${COLMAP_COMMIT} (BSD-3-Clause) and the custom OpenImageIO build (Apache-2.0) are
included as upstream/ git archives. Rebuild: see build-scripts/ and BUILD_INFO.json.
The bundled libraries are ordinary shared objects in runtime/colmap/lib and may be replaced
by modified builds (relinking). This offer of source is included with every binary release.
EOF
( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
echo "corresponding source in $OUT ($(du -sh "$OUT" | cut -f1))"
