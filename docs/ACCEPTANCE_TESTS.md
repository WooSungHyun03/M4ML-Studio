# Acceptance Tests — Do not mark PASS without evidence

Use table statuses: `NOT RUN / PASS / FAIL / BLOCKED`; put command, test fixture, log or screenshot file references in `docs/STATUS.md`. 'Passed on mocked subprocess' never implies genuine COLMAP/SAM/GS ran on GPU. Prefer automation plus real manual scenarios.

| ID | Acceptance criterion | Required evidence |
|---|---|---|
| ENV-01 | Object-Aware anchor Python/Torch/CUDA preserved and rasterizer imports | exact version output, native import test |
| ENV-02 | SAM **3.1** checkpoint load + positive and negative point clicks run in **same** Python env | checkpoint identity, GPU name, model type, masks, log |
| ENV-03 | SAM 3.1 3+ frames genuine propagation | frame map + binary mask image/log |
| ENV-04 | Object-Aware still trains (smoke) after SAM adaptation | actual original train command output |
| UI-01 | One-command startup, UI works locally with no cloud connection | launcher log, live UI screenshot |
| UI-02 | Six-stage clear step indicator, state survives restart | persistent job tests + manual browser test |
| IMP-01 | Mixed images, Korean/space names, EXIF orientation and duplicates imported | input fixture + manifest verification |
| IMP-02 | Invalid/corrupt images fail individually, originals unchanged | negative unit test + source checksums |
| CLM-01 | Genuine COLMAP feature/match/map/undistort runs on suitable real/synthetic multi-view sample | logs + actual sparse cameras/images |
| CLM-02 | Separate matched / registered / other component / failed statuses; no excluded view enters training | partial-failure fixture + manifest |
| CLM-03 | Camera model and undistorted photo calibration agree, sparse images parsed | scene loader smoke |
| SAM-01 | Click coordinate maps accurately after zoom/pan/resizing, + and - correct | UI mapping unit/integration tests |
| SAM-02 | One initial selected registered image prompts propagation to the other registered images | real model outputs + registered-only evidence |
| SAM-03 | Unordered views, jumps, empty masks and occlusions produce accurate warnings, not invented masks | QA fixture + manual demo |
| REV-01 | Previous/next and save/accept/undo/redo function with persistent masks | UI interaction test + reload |
| REV-02 | `남은 검토 모두 건너뛰기` records skip but blocks missing/invalid mask | skip gating tests |
| REV-03 | All saved mask PNG are single-channel uint8, only 0/255, same stem & size as undistorted registered images | binary/data integrity script |
| REV-04 | Editing mask invalidates old training and mesh outputs in state, never falsely reuses them | fingerprint invalidation test |
| TRN-01 | Chosen physical GPU used by original `train.py`, no implicit CPU fallback | worker device log and GPU telemetry |
| TRN-02 | Full original loss/pruning preserved; default param snapshot matches repo | source diff / config + loss tests |
| TRN-03 | Real train produces valid Gaussian PLY; real iterations, loss and progress shown | process log, output files, frontend check |
| TRN-04 | Stop/error/OOM are handled without 'completed' status, no corruption, resume claims tested | process failure/restart tests |
| MSH-01 | Original `render.py` TSDF mesh generated with finite vertices and triangles | real PLY read/geometry report |
| MSH-02 | 3D viewport displays **triangle mesh** and supports orbit/pan/zoom/fit/wireframe | visual browser test, screenshot |
| MSH-03 | Export original PLY and optional valid GLB/OBJ with explicit color/material limitation | load-back geometry test |
| OPS-01 | Restart recovery at each stage, no duplicate GPU workers or stale success | service/integration fault tests |
| OPS-02 | File path traversal, unsafe filenames, subprocess quoting, localhost binding & large files controlled | security tests |
| OPS-03 | Correct upstream license notices, no checkpoints/data/secret files in git artifacts | git diff / license audit |
| E2E-01 | Real Ubuntu + NVIDIA full workflow import→COLMAP→SAM3.1→review→Object-Aware train→mesh viewer | real device/commands, log directory, screenshot, generated mesh |

## Preflight test sequence

1. Run linters/typechecks/unit tests for API, frontend and finite-state machine.
2. Run COLMAP real small-scene command, verify sparse camera count; use artificial/fake images only for **negative** path tests, not proof of reconstruction.
3. Run authentic SAM 3.1 point + 3-frame propagation in Object-Aware anchor env.
4. Train Object-Aware on minimal valid scene with real masks and check `point_cloud/iteration_N/point_cloud.ply` and logs.
5. Extract mesh from genuine trained model and parse with Open3D/trimesh, validate finite triangles.
6. UI walkthrough via actual browser/desktop session, including review corrections, skip, cancel/retry, reboot/reopen.
7. Run user-facing default run with 30,000 iteration setting if adequate resources/dataset; if infeasible, report sampled smoke test only and do not claim full convergence.

## Test data policy

- Unit fixtures can use generated tiny PNGs, camera mocks and mesh fixtures.
- COLMAP integration needs **geometrically consistent** views (calibrated renders or photographed object); do not use random images and mark expected failure as pipeline success.
- SAM3.1 integration needs local model weights and genuine registered frames; no substitute predictor.
- Training integration needs true COLMAP scene and masks. If host model or dataset unavailable, mark GPU E2E `BLOCKED` or `NOT RUN` and preserve honest limitation.

## Executed evidence index (2026-10-15)

All criteria have host-specific PASS entries in `docs/STATUS.md`; distinguish their evidence levels. Primary physical run: actual UI16-photo import/COLMAP/SAM/manual correction/explicit30K/automatic1024 TSDF/viewer/export. Final independent audit: `evidence/e2e-release.json`. Fresh private installation: `evidence/cold-install-setup.log`; no global environment replacement. Deterministic Python27 and frontend2 tests cover guards/negative fixtures, not stand-in inference. Physical failure evidence includes actual GPU stop, original-train allocator OOM, CPU worker/server death and shared GPU queue cancellation. Source hashes and licenses are retained. Browser screenshots and original logs remain local/ignored; no model/data artifacts are committed.
