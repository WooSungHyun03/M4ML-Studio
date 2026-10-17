# M4ML Studio 1.0.0 — release readiness

Updated 2026-10-17 by the Claude release session (continuing the Codex solo-finish harness). Evidence paths are relative to the project root, and evidence folders are not in Git. Numbers marked *(Codex)* come from the earlier Codex session's logs, which were re-read but not re-run here.

## Gates

| Gate | Evidence | State |
|---|---|---|
| G0 Recovery | Codex branch `codex/v1-solo-finish` @20987ff and uncommitted QA scripts preserved and committed; last native I/O log re-read (`evidence/v1/install/native-io-final/result.json`, 6/6 PASS) | VERIFIED |
| G1 UI/UX | 104 real-Qt page captures, 1366×768 and 1920×1080 × dark/light: welcome, 6 stages, live + mesh, 6 menus, 4 settings tabs, 7 help dialogs; 0 JS errors, no horizontal overflow (`evidence/v1/ux-final/result.json`). Fixed: bottom panel squeezing the mask editor on short windows; scene-up orientation of live/mesh/sparse viewers (`evidence/v1/orientation/photo-vs-live.png`); English Qt dialogs | VERIFIED (scoped to these profiles) |
| G2 Native file I/O | Real Qt dialogs (offscreen platform, product code unmodified), 11/11: folder/file pick, drag-and-drop upload, PLY + GLB byte-identical at the exact chosen path, cancel writes nothing, overwrite only after confirmation (no "(1)" copy), unwritable folder warns and reopens, source data unchanged, dialogs in Korean (`evidence/v1/io-final-host/result.json`) | VERIFIED |
| G3 GPU pipeline | Installed final package in a fresh container — see "Installed package" below. *(Codex)* source and candidate-D runs: raw16 COLMAP 16/16, SAM 3.1, non-default 1000-iteration resume, TSDF, CUDA frame | see below |
| G4 Tests | Source: Python 116/116, frontend 12/12, TypeScript/build PASS. CI emulation (Python 3.10 venv without GPU): 108 tests PASS; `test_sam_compat` and `test_scientific_contract` are GPU-runtime only (`scripts/ci_tests.py`) | VERIFIED |
| G5 Architecture | Provider interfaces, renderer lifecycle, GPU lock/handover, and the atomic export path reviewed; no rewrite | VERIFIED (bounded) |
| G6 Package | `release/v1.0.0-final/M4ML-Studio-1.0.0-linux-x86_64.tar.gz`, 2250 files, 116,669,421 bytes, SHA256 `e6b98056eac18b12ef1cc2f8ddaef0f869f98d29f536d4890f2da1e52cbcbb8b`, source commit 58e7ce2. No weights, user data, logs, PLY/GLB, `.git` or Python environment. Manifest channel `noncommercial-release` | VERIFIED |
| G7 Licence | All component licences permit non-commercial redistribution with their texts and notices: Inria/MPII Gaussian-Splatting (`LICENSE.md`), Inria SIBR, SAM License (code only, weights excluded), BSD/MIT/OFL, NVIDIA cudart EULA. Copyleft runtime parts (SuiteSparse GPL/LGPL, GCC 14 runtime GPLv3+exception) are covered by `M4ML-Studio-1.0.0-corresponding-source.tar` (209,397,760 bytes, SHA256 `d5ced93f4af2b46d8523d046b33d6d2b517cd472ec71d424c090734e55b224cf`). Its Ubuntu tarballs match the SHA256 in their GPG-signed `.dsc`, and COLMAP @bd1fcf65 and OpenImageIO @f32bf6e6 are git archives. Commercial use is **not** permitted. No legal review | VERIFIED for non-commercial distribution |
| G8 Security | Loopback API with token and Origin checks, desktop-only token injection, renderer on an OS-assigned loopback port, no secrets in tracked files or full history (pattern scan), personal paths removed from current docs | VERIFIED (single-user workstation scope) |
| G9 GitHub | Target `https://github.com/WooSungHyun03/M4ML-Studio` (private, empty). Remote `m4ml` was **not added**: `git push` was blocked by this session's permission policy | **BLOCKED — needs the user** |

## Installed package (fresh container)

- Image: Ubuntu 24.04 with Miniforge.
- User: new non-root `studio-user` (UID 1101), empty home.
- System fonts: 0 Korean.
- System packages: the README `apt` list.
- Runtime: no developer runtime mounted.

Steps: checksum check → extract → `./scripts/install.sh`, exit 0.

- Both CUDA extensions built from source; SAM 3.1 installed; PySide6 6.8.1 installed.
- Diagnostics: everything passed except the SAM checkpoint, which is expected (weights are user-supplied).

Post-install results, all on the INSTALLED copy (`evidence/v1/final-install/`):

- **Installed unit tests:** 116 ran, OK, 1 skipped (Git-only check that cannot apply to an archive).
- **Backend `/api/about`:** version 1.0.0, release 1.0.0, channel `noncommercial-release`, source commit 58e7ce2, install root under `~/.local/share/m4ml-studio/apps/1.0.0`.
- **`/api/health`:** RTX 4080 detected; bundled GPU COLMAP available with CUDA.
- **SAM checkpoint path:** configured through the API (3,502,755,717 bytes; host weights mounted read-only and **not** copied into the package).
- **GPU pipeline** (`scripts/v1_gpu_qa.py`, `gpu.json` passed), on 16 fresh photos:
  - real GPU COLMAP 16/16 registered;
  - official SAM 3.1 positive/negative clicks (latest-wins);
  - 16-view propagation, manual correction, explicit skip;
  - original training to 1000 iterations with resume from checkpoint 100 and the non-default setting alpha 0.27 (12,425 Gaussians);
  - automatic coloured TSDF 128 mesh;
  - real CUDA live-render frame;
  - source photo hashes unchanged.
  This is integration proof, not quality convergence.
- **Installed desktop app**, launched with the desktop entry's `Exec` command:
  - desktop shell confirmed (token injected, no browser);
  - bundled Noto Sans KR active with 0 system Korean fonts;
  - Korean welcome UI;
  - RTX 4080 diagnosed in the UI;
  - the GPU-run project opens with 6 workflow tabs.
- **Not verified in the installed GUI:** mesh viewer and live-render view. The container's offscreen Qt has no OpenGL (WebGL unavailable; the app shows its clear "3D 화면을 열 수 없습니다" message). The Xvfb run that would have provided software GL was blocked by this session's permission policy. Both views were verified in the real Qt app from the source tree (G1), and the installed backend served a real CUDA frame.

## Release state

Release assets ready in `release/v1.0.0-final/`:

- `M4ML-Studio-1.0.0-linux-x86_64.tar.gz` (+ `.sha256`)
- `M4ML-Studio-1.0.0-corresponding-source.tar` (+ `.sha256`)
- `SHA256SUMS`
- `RELEASE_NOTES.md`

**Not pushed, no GitHub Release created.** `git push` to the target repository was refused by the session's permission policy (auto-mode classifier: data exfiltration), so the GitHub upload, Actions run, release and post-release download check remain for the user. Exact commands are in `docs/STATUS.md`.
