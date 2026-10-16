#!/usr/bin/env python3
"""Make a relocatable COLMAP runtime: copy the binary and its non-system shared libraries.

The glibc family and the NVIDIA driver library (libcuda) are intentionally NOT bundled:
they must come from the user's system / driver. Everything else that the binary links
(Ceres, Boost, OpenImageIO, CUDA runtime, cuRAND, libstdc++, ...) is copied into lib/ and
found through RPATH=$ORIGIN/../lib, so the result does not depend on the build machine.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

SYSTEM = re.compile(
    r"^(linux-vdso|ld-linux|libc\.so|libm\.so|libmvec\.so|libpthread\.so|libdl\.so|librt\.so|"
    r"libresolv\.so|libutil\.so|libcuda\.so|libnvidia-|libGL\.so|libGLX|libGLdispatch|libEGL|libOpenGL|libX11|libxcb)"
)


LIB_PATH = ""


def ldd(path):
    env = dict(os.environ, LD_LIBRARY_PATH=LIB_PATH) if LIB_PATH else None
    out = subprocess.run(["ldd", str(path)], capture_output=True, text=True, check=True, env=env).stdout
    libs, missing = {}, []
    for line in out.splitlines():
        m = re.match(r"\s*(\S+) => (\S+)", line)
        if m:
            if m.group(2) == "not":
                missing.append(m.group(1))
            else:
                libs[m.group(1)] = m.group(2)
    return libs, missing


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for name in ("stage", "out", "cuda-root", "profile", "archs", "commit", "tag"):
        ap.add_argument("--" + name, required=True)
    ap.add_argument("--lib-path", default="")
    a = ap.parse_args()
    global LIB_PATH
    LIB_PATH = a.lib_path
    patchelf = shutil.which("patchelf", path=f"{a.cuda_root}/bin:{os.environ.get('PATH', '')}")
    if not patchelf:
        sys.exit("patchelf is required (conda install -p .build/cuda12 -c conda-forge patchelf)")
    stage, out = Path(a.stage), Path(a.out)
    tmp = Path(tempfile.mkdtemp(prefix="colmap-bundle-", dir=out.parent if out.parent.exists() else None))
    tmp.chmod(0o755)  # mkdtemp creates 0700; installed/shared copies must be readable by other users
    (tmp / "bin").mkdir()
    (tmp / "lib").mkdir()
    binary = tmp / "bin/colmap"
    shutil.copy2(stage / "bin/colmap", binary)
    libs, missing = ldd(stage / "bin/colmap")
    if missing:
        sys.exit(f"unresolved libraries at build time: {missing}")
    bundled, system = [], []
    for name, path in sorted(libs.items()):
        if SYSTEM.match(name):
            system.append(name)
            continue
        dst = tmp / "lib" / name
        shutil.copy2(os.path.realpath(path), dst)
        os.chmod(dst, 0o755)
        subprocess.run([patchelf, "--set-rpath", "$ORIGIN", str(dst)], check=True)
        bundled.append(name)
    # DT_RPATH (not RUNPATH) on the executable is honoured for transitive dependencies too.
    subprocess.run([patchelf, "--force-rpath", "--set-rpath", "$ORIGIN/../lib", str(binary)], check=True)
    os.chmod(binary, 0o755)
    nvcc = subprocess.run([f"{a.cuda_root}/bin/nvcc", "--version"], capture_output=True, text=True).stdout
    info = {
        "schema": 1,
        "engine": "COLMAP",
        "tag": a.tag,
        "commit": a.commit,
        "profile": a.profile,
        "cuda_architectures": a.archs,
        "cuda_toolkit": (re.search(r"release ([\d.]+), V([\d.]+)", nvcc) or [None, None]).group(0) if nvcc else None,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bundled_libraries": bundled,
        "system_libraries_required": system,
        "binary_sha256": sha256(binary),
        "license": "BSD-3-Clause (COLMAP, see COPYING.txt); bundled library licenses: docs/GPU_COLMAP_BUILD.md",
    }
    (tmp / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n")
    for item in tmp.rglob("*"):
        item.chmod(0o755 if item.is_dir() or os.access(item, os.X_OK) or item.suffix == "" or ".so" in item.name else 0o644)
    license_file = Path(a.stage).parent / "colmap-src/COPYING.txt"
    if license_file.exists():
        shutil.copy2(license_file, tmp / "COPYING.txt")
    # Atomic replace of the previous runtime (kept as .previous for rollback).
    out.parent.mkdir(parents=True, exist_ok=True)
    prev = out.with_name(out.name + ".previous")
    if out.exists():
        if prev.exists():
            shutil.rmtree(prev)
        out.rename(prev)
    tmp.rename(out)
    # Verify the relocated binary resolves everything from the bundle / base system.
    LIB_PATH = ""
    libs2, missing2 = ldd(out / "bin/colmap")
    leaked = [n for n, p in libs2.items() if not SYSTEM.match(n) and not p.startswith(str(out))]
    if missing2 or leaked:
        sys.exit(f"bundle check failed: missing={missing2} resolved-outside-bundle={leaked}")
    print(json.dumps({k: info[k] for k in ("tag", "commit", "profile", "cuda_architectures", "cuda_toolkit")}))
    print(f"{len(bundled)} libraries bundled, {len(system)} system libraries required")


if __name__ == "__main__":
    main()
