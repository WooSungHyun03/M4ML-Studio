# M4ML Studio v1.0.0

Multi-view photos → GPU camera registration → SAM 3.1 object masks → Object-Aware 2D Gaussian Splatting → colored 3D mesh, in a local Korean desktop application. All data stays on the computer: no login, no cloud upload, no telemetry.

**Licence: non-commercial research and evaluation only.** See `LICENSE.md`, `NOTICE` and `THIRD_PARTY_NOTICES.md`. Commercial use is not permitted.

## Downloads

| File | Content |
|---|---|
| `M4ML-Studio-1.0.0-linux-x86_64.tar.gz` | Installation package: application, static UI, bundled GPU COLMAP runtime, SIBR viewer, licences, SBOM. No Python environment, no model weights, no user data |
| `M4ML-Studio-1.0.0-linux-x86_64.tar.gz.sha256` | Checksum of the package |
| `M4ML-Studio-1.0.0-corresponding-source.tar` (+ `.sha256`) | Corresponding source for the copyleft parts of the bundled COLMAP runtime: SuiteSparse and GCC 14 Ubuntu source packages, Ceres, COLMAP and OpenImageIO sources, build scripts |
| `SHA256SUMS` | Checksums of all assets |

## System requirements

- **Verified:** Ubuntu 24.04 x86_64 (glibc 2.39), X11 session, NVIDIA RTX 4080 16 GB, driver 580.173.02. Other GPUs, drivers, Ubuntu versions and Wayland are **not certified**.
- **NVIDIA GPU:** a CUDA-capable GPU with a driver supporting CUDA 12.x (bundled COLMAP uses CUDA 12.6; training uses PyTorch 2.5.1 + CUDA 11.8). 16 GB is the tested capacity, not a guaranteed minimum. The driver is never installed or changed.
- **Before installation:** Python 3, Git, curl, Miniforge/Conda, GCC/G++ 11, and the OpenGL/X11/Qt libraries listed in README. The installer downloads the Python environment (internet and free disk space required).
- **SAM 3.1 weights:** obtain `sam3.1_multiplex.pt` from the official source under its terms, then set the path in 설정 → 모델 파일.

## Install

```bash
sha256sum -c M4ML-Studio-1.0.0-linux-x86_64.tar.gz.sha256
tar -xzf M4ML-Studio-1.0.0-linux-x86_64.tar.gz
cd M4ML-Studio-1.0.0
./scripts/install.sh
```

Open **M4ML Studio** from the application menu (or run `python3 scripts/launch.py`).

- **Upgrading from 0.4.0** keeps projects, settings and the runtime. See `docs/V1_MIGRATION.md`.
- **Uninstall:** `./scripts/install.sh --uninstall`. It keeps projects and the runtime.

## Known limitations

- Only the configuration above was verified on real hardware. A full validation run on other GPUs/OSes, very large photo sets (500+) and overnight runs has not been done.
- Temporal mask propagation can fail across wide viewpoint changes or occlusions; review and correct.
- Meshes may have holes or partial surfaces where views are missing; watertightness is not guaranteed.
- The local API and the live-render socket are protected for a single-user workstation (loopback, token, Origin checks). They are not an OS multi-user security boundary.
- The external SIBR viewer needs Ubuntu's OpenCV/FFmpeg/GLFW/Embree libraries. The in-app live view does not.
- Texture/material baking for GLB is not supported (vertex colors only).
