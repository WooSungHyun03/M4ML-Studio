# Third-party notices — M4ML Studio 1.0.0

M4ML Studio is distributed for **non-commercial research and evaluation only**. This table summarises the actual licence files shipped in the source tree and the installation package. The licence texts themselves are authoritative. No legal review has been performed.

| Component | Where | Licence (file) | Redistribution in this release |
|---|---|---|---|
| M4ML Studio application, Object-Aware Loss, inherited 2D Gaussian Splatting / Gaussian-Splatting code | source tree | Inria/MPII Gaussian-Splatting License (`LICENSE.md`) | Non-commercial; full licence text and all notices are retained; derivative works stay under the same use limitation |
| diff-surfel-rasterization, simple-knn | git submodules (built at install time) | their own licence files (Gaussian-Splatting licence family) | Fetched from upstream at their pinned commits; non-commercial |
| SIBR remote viewer (Gaussian-Splatting-Monitor @2b6190c + `patches/sibr`) | `runtime/sibr` in the package; build `scripts/build_sibr.sh` | Inria SIBR / Gaussian-Splatting (`licenses/SIBR-LICENSE.md`, `licenses/Gaussian-Splatting-Monitor-LICENSE.md`; also in `runtime/sibr/licenses/`) | Non-commercial; only SIBR's own libraries are bundled |
| SAM 3.1 code + local patches | `vendor/sam3` submodule, `patches/sam3` | SAM License (`licenses/SAM-source-LICENSE`) | Code under the SAM License with a copy of the agreement. **Weights are not included** (`licenses/SAM-checkpoint-LICENSE`) |
| COLMAP 4.2.1 | `runtime/colmap/bin/colmap` | BSD-3-Clause (`licenses/colmap-runtime/COLMAP-COPYING.txt`) | Binary built by `scripts/build_colmap.sh` |
| 47 shared libraries of the COLMAP runtime (SuiteSparse, Ceres, Boost, OpenEXR, OpenImageIO, OpenBLAS, GCC 14 runtime, …) | `runtime/colmap/lib` | per-library texts in `licenses/colmap-runtime/`, hashes in `inventory.json` | Unmodified binaries. **Copyleft:** SuiteSparse CHOLMOD/SPQR (GPL-2.0-or-later) and other LGPL modules, GCC 14 runtime (GPL-3.0-or-later WITH GCC-exception-3.1). Their complete corresponding source (plus COLMAP, Ceres, OpenImageIO sources and build scripts) is the release asset `M4ML-Studio-1.0.0-corresponding-source.tar` (`scripts/collect_corresponding_source.sh`). The libraries are replaceable shared objects |
| NVIDIA CUDA runtime 12.6 (cudart) | `runtime/colmap/lib` | NVIDIA CUDA EULA (`licenses/colmap-runtime/CUDA-12.6-EULA`) | Redistributable component under the EULA. The NVIDIA driver is never included |
| React, Three.js, Lucide and other bundled frontend packages | `frontend/dist` | MIT/ISC (`licenses/frontend-MIT-NOTICES`) | Notices retained |
| Noto Sans KR (Adobe) | `frontend/public/fonts/NotoSansKR.ttf` | SIL OFL 1.1 (`licenses/NotoSansKR-OFL.txt`) | Unmodified; not relicensed; not sold by itself |
| PyTorch, Open3D, PySide6 / Qt WebEngine, NumPy and other Python packages | downloaded by `scripts/setup.sh` | their own licences (Qt: LGPL-3.0, `licenses/LGPL-3.0.txt`) | **Not redistributed** in the package; installed from upstream providers |
| M4ML logo | `Logo/`, icons | — | Product identification only; no logo licence is granted |

A machine-readable SBOM is generated into `licenses/sbom.json` of every package, and the in-app list is under 도움말 → 라이선스.

Excluded from both the repository and the package: user projects, photos, masks, checkpoints, trained Gaussians and meshes, model weights, credentials and test evidence.
