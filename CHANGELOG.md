# Changelog

## 1.0.0 — 2026-10-17

First non-commercial research/evaluation release of M4ML Studio. Detailed record: `docs/V1_CHANGELOG.md`, `docs/V1_RELEASE_REPORT.md`, `docs/TEST_REPORT.md`.

- **Desktop editor** (PySide6 / Qt WebEngine): menus, workflow tabs, project explorer, inspector, task/log/GPU panels, dark/light themes. Korean UI with a bundled Noto Sans KR font, and Qt's own dialogs in Korean.
- **Projects:** "new project" analyses a folder read-only (photos, COLMAP, masks, training output, checkpoints, meshes) and reuses only results that belong to the same dataset.
- **Pipeline:** GPU COLMAP 4.2.1 registration → SAM 3.1 point prompts with propagation and review → original Object-Aware Loss / 2DGS training (provider settings, pause/resume with checkpoint compatibility checks) → TSDF colored mesh → PLY/GLB export.
- **3D model workspace:**
  - 실시간 렌더 (live CUDA rendering of the trained Gaussians through the 2DGS/SIBR remote protocol, pixel-identical to the original renderer);
  - 메시 (colored mesh viewer);
  - both orbit about the scene's real up axis derived from the training cameras.
- **Exports** are saved exactly at the path chosen in the save dialog: atomic replace, overwrite confirmation, unwritable-folder warning, and the existing file is kept on failure.
- **Installer:** per-user install/upgrade/uninstall that preserves projects and runtime, OverlayFS-safe retirement, verified manifest, SBOM.
- **Licensing:** corresponding source for the bundled copyleft runtime libraries is published with each binary release.

## 0.5.0 / 0.4.0 / 0.3.0

Internal builds: live Gaussian viewport, desktop editor and folder analysis, providers and GPU COLMAP. See `docs/STATUS.md`.
