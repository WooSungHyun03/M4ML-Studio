# GPU (CUDA) COLMAP — build, bundling and verification

M4ML Studio ships its own relocatable, CUDA-enabled COLMAP in `runtime/colmap/` and no
longer depends on a system `colmap` (the Ubuntu package on this host is 3.9.1 **without
CUDA**). The app resolves the engine in this order: settings → `STUDIO_COLMAP` → bundled
`runtime/colmap/bin/colmap` → installer record → `PATH`, and GPU jobs refuse a non-CUDA
build unless the user explicitly confirms a CPU run.

## 1. Versions (exact)

| Item | Value |
|---|---|
| COLMAP | tag **4.2.1**, commit **`bd1fcf654d2dd8fefa1466999c190a246f83f4b9`** (https://github.com/colmap/colmap) |
| Fetched by COLMAP's CMake (hash-pinned) | PoseLib `fa7280fee27f97aff31ae7f98bab7f583fac7d08` (BSD-3), faiss v1.14.1 (MIT) |
| Image I/O | OpenImageIO **v2.5.19.1**, commit `f32bf6e6f8de38ab6d197a72fd72366b66fd30a3`, minimal build (JPEG/PNG/TIFF/EXR) — `scripts/build_oiio_minimal.sh` |
| CUDA toolkit (compile) | **12.6.85** (`nvcc`), cudart 12.6.77, cuRAND 10.3.7.77 — private conda-forge prefix `.build/cuda12` (not system-wide) |
| Host compiler / build | GCC 13.3.0, CMake 3.28.3, Ninja 1.11.1, Ubuntu 24.04.3 x86_64 |
| Build host GPU / driver | NVIDIA GeForce RTX 4080 (compute 8.9), driver 580.173.02 |
| Other deps (system packages) | Ceres 2.2, Boost 1.83, Eigen 3.4, glog 0.6, gflags 2.2, METIS 5.1, SuiteSparse 7.6, SQLite 3.45, OpenEXR 3.1, libtiff/libpng/libjpeg-turbo |

Why CUDA 12.6 rather than the host's CUDA 13.0 toolkit: CUDA 13 requires driver ≥ 580 and
dropped pre-Turing GPUs. A 12.6 build runs on drivers ≥ 525 (CUDA 12 minor-version
compatibility) and supports Pascal → Hopper. The PyTorch runtime (CUDA 11.8 wheels) is a
separate runtime and is not used by COLMAP.

## 2. Build profiles

| Profile | `CMAKE_CUDA_ARCHITECTURES` | Use |
|---|---|---|
| `dist` (default, shipped) | `60-real;61-real;70-real;75-real;80-real;86-real;89-real;90` (SASS for Pascal…Hopper + PTX 9.0 JIT for newer GPUs) | distribution |
| `local` | `native` | fastest build for the build machine only |

CMake options (from `scripts/build_colmap.sh`):

```
-DCMAKE_BUILD_TYPE=Release -DCUDA_ENABLED=ON -DCUDAToolkit_ROOT=.build/cuda12
-DCMAKE_CUDA_COMPILER=.build/cuda12/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=<profile>
-DGUI_ENABLED=OFF -DOPENGL_ENABLED=OFF -DONNX_ENABLED=OFF -DCGAL_ENABLED=OFF
-DDOWNLOAD_ENABLED=OFF -DTESTS_ENABLED=OFF -DCCACHE_ENABLED=OFF
-DOpenImageIO_DIR=.build/oiio-install/lib/cmake/OpenImageIO
-DCMAKE_INSTALL_RPATH='$ORIGIN/../lib'
-DCMAKE_IGNORE_PREFIX_PATH=<user conda/miniforge prefixes>   # hermetic: no conda headers
```

GUI/OpenGL are off (M4ML Studio has its own UI); SiftGPU runs headless through CUDA.

## 3. Reproduce

```bash
# 1) private CUDA 12.6 toolkit + patchelf (no sudo, nothing system-wide)
conda create -y -p .build/cuda12 --override-channels -c conda-forge \
      cuda-nvcc=12.6 cuda-cudart-dev=12.6 libcurand-dev cuda-version=12.6 patchelf
# 2) Ubuntu 24.04 build dependencies (system packages; install once with apt if missing)
#    build-essential cmake ninja-build git libboost-program-options-dev libboost-graph-dev
#    libboost-system-dev libeigen3-dev libflann-dev libmetis-dev libgoogle-glog-dev
#    libgflags-dev libsqlite3-dev libceres-dev libsuitesparse-dev libopenexr-dev
#    libimath-dev libtiff-dev libpng-dev libjpeg-turbo8-dev
# 3) build (fetches COLMAP 4.2.1, minimal OIIO, verifies the commit hash)
./scripts/build_colmap.sh --profile dist      # or: --profile local
```

The script refuses to build if the checked-out source is not the pinned commit, strips
user conda prefixes from `PATH`/CMake search (a first attempt picked up an old glog header
from `~/anaconda3/include` and failed — fixed by the hermetic environment), installs to a
staging prefix and then runs `scripts/bundle_colmap.py`.

## 4. Bundle layout and dynamic libraries

```
runtime/colmap/
  bin/colmap          DT_RPATH=$ORIGIN/../lib (also applies to transitive deps)
  lib/*.so*           every non-base-system shared library, each with RUNPATH=$ORIGIN
  BUILD_INFO.json     tag, commit, profile, archs, toolkit, bundled/system libs, sha256
  COPYING.txt         COLMAP license
```

Not bundled (must come from the user's system): glibc family (`libc`, `libm`, `libpthread`,
`libdl`, `librt`, `libresolv`, `ld-linux`), the NVIDIA driver (`libcuda.so`). The bundler
re-runs `ldd` on the relocated binary and fails if any library resolves outside the
bundle except these. glibc of the build host is **2.39 (Ubuntu 24.04)**: the binary runs on
glibc ≥ 2.39 (Ubuntu 24.04+, Debian 13+, Fedora 40+). For Ubuntu 22.04 build on 22.04 with
the same script.

Size history: the first build linked Ubuntu's OpenImageIO, which pulled OpenCV, FFmpeg
(including GPL x264/x265), GDAL, OpenVDB, … — **261 libraries / 480 MB**. Rebuilding against
the minimal OpenImageIO removes those (see §6 for the final numbers and license list).

## 5. Real GPU verification (not inferred from build flags)

`scripts/verify_gpu_colmap.py IMAGES OUT [--cpu]` runs the production camera provider and
samples `nvidia-smi --query-compute-apps` while the GPU steps run; a step counts as GPU
only if the COLMAP process (`/proc/<pid>/exe` = bundled binary) held GPU memory.

GPU vs CPU per step in COLMAP 4.2.1:

| Step | Device |
|---|---|
| `feature_extractor` (SIFT) | **GPU** (`--FeatureExtraction.use_gpu 1 --FeatureExtraction.gpu_index 0`) |
| `exhaustive_matcher` / `sequential_matcher` | **GPU** (`--FeatureMatching.use_gpu 1`) |
| `mapper` (incremental SfM, bundle adjustment) | CPU (Ceres) |
| `image_undistorter` | CPU |

Option names are read from the binary's own `-h` output (`studio.engines.pick_option`);
4.x renamed `SiftExtraction.use_gpu` → `FeatureExtraction.use_gpu`. If the GPU switch cannot
be found the provider fails instead of silently running COLMAP defaults.

Measured on this host (RTX 4080, 16 CPU threads), South Building 128 × 3072×2304 photos:

| | extraction | matching (8,128 pairs) | mapper | undistortion | total | registered |
|---|---|---|---|---|---|---|
| GPU | **6.9 s** (peak 5,868 MB on GPU) | **34.8 s** (peak 1,536 MB) | 140.4 s | 3.7 s | 192 s | 128/128 |
| CPU (explicit) | 148.2 s | 222.5 s | 171.9 s | 4.5 s | 554 s | 128/128 |

Evidence: `evidence/gpu-colmap-128/verification.json`, `evidence/cpu-colmap-128/verification.json`
(+ `colmap.log` with exact argv), `evidence/gpu-colmap-16/` (16 photos, 4.3 s). Through the
app API (Mode A, 24 photos): `evidence/e2e-0.3/result.json` → `A.camera.engine.steps`
(`gpu_observed: true` for extraction and matching).

A defect found by this verification: the first comparison ran the "CPU" request on the GPU
because option probing read only stdout (COLMAP 4 prints usage on stderr) and so passed no
flags, leaving COLMAP's default `use_gpu=1`. Fixed (stdout+stderr probing, fail-loud on a
missing switch) and re-measured; the CPU run's argv now shows `--FeatureExtraction.use_gpu 0`.

Compatibility with the reconstruction trainer: the undistorted model written by 4.2.1 is
read by the unchanged `scene/colmap_loader.py` (verified by `validate_scene` and by full
training in the E2E run). 4.x additionally writes `rigs.bin`/`frames.bin`; they are kept
next to `cameras.bin`/`images.bin`/`points3D.bin` and ignored by the loader.

## 6. Distribution notes and licenses

* Ship `runtime/colmap/` inside the release archive (`scripts/package_release.py` copies it
  and records `camera_engine` with commit/archs/sha256 in `release-manifest.json`).
* Users need an NVIDIA driver ≥ 525 for this CUDA 12.6 build; GPUs with compute capability
  6.0–9.0 run native code, newer GPUs JIT the PTX 9.0 (first run slower).
* COLMAP: BSD-3-Clause (`runtime/colmap/COPYING.txt`). PoseLib BSD-3, faiss MIT,
  OpenImageIO Apache-2.0, Ceres BSD-3, glog/gflags BSD-3, Boost BSL-1.0, METIS Apache-2.0,
  SQLite public domain, libtiff/libpng/libjpeg-turbo permissive, OpenEXR/Imath BSD-3,
  CUDA runtime/cuRAND: NVIDIA CUDA EULA (redistributable runtime components).
  **SuiteSparse/CHOLMOD** (pulled in through Ceres) contains LGPL and GPL modules in the
  Ubuntu build; redistribution of the bundle must honour those terms (provide sources /
  relinking ability). This has not been reviewed by counsel; do not claim unrestricted
  commercial redistribution. The whole M4ML Studio product is additionally limited by the
  non-commercial Gaussian-Splatting license of the reconstruction code.

## 7.0.3 recovery audit corrections (2026-10-16)

The actual `BUILD_INFO.json` lists **47 bundled libraries** and **11 host-system libraries**.
In addition to glibc/driver, GL/GLX/GLdispatch/OpenGL/X11/xcb must be provided by the
host; the headless SIFT target retains GL/GLEW linkage even though Qt GUI is disabled.
There are no Qt shared libraries in this runtime. `ldd` of the relocated final package
is the authority; do not interpret the earlier generic "everything except glibc/driver"
wording as the actual dependency list. The current bundle contains cudart12.6.77 and
no cuRAND `.so` (the compiler prefix contains more components than the shipped runtime).

CUDA12 minor-version compatibility's525 floor has feature/PTX restrictions. CUDA12.6
PTX JIT may need a sufficiently new driver; only580.173.02/RTX4080 was physically tested.
The fatbinary architecture list is build coverage, not proof that every such GPU works
with the complete SAM/training application. Ubuntu22.04/glibc2.35 is not supported by
this Ubuntu24.04/glibc2.39 binary. See [NVIDIA compatibility limitations](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).

The0.3 archive is **internal-research only** pending corresponding-source/relinking and
license-compatibility resolution. `NOTICE` and `licenses/colmap-runtime/` now include
unmodified notices for actual ELF dependencies, static PoseLib/faiss, minimal OIIO and
the actual CUDA12.6 EULA, with hashes. This does not by itself clear public distribution.
A non-root fresh installation/relocation/ELF check is recorded separately in TEST_REPORT.
