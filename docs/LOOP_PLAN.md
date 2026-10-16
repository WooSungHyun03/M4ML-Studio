# Loop Engineering — execution plan with stop conditions

## How the Codex loop operates

Every iteration: **Inspect → hypothesize → implement smallest working vertical slice → test real outcome → fix → validate regression → record evidence → next slice**. Track stage and tests in `docs/STATUS.md`. A checked box means code exists *and* acceptance evidence exists. Keep work in git on a non-destructive branch; commit coherent slices when appropriate. If a stage is blocked, write explicit root-cause/trace and continue only to genuinely independent work without misreporting end-to-end readiness.

For each loop cycle record:
- Scope / assumptions and source code paths inspected.
- Code change summary and changed files.
- Exact checks invoked, exit codes, key logs, original bug and regression.
- Environment (GPU/driver/CUDA/Python/Torch) when applicable.
- Remaining blocker and next slice.

Failure policy: 2-3 repeated failures of the same cause => stop blind retries, construct minimal reproduction, inspect upstream code/issues/docs, change strategy, write decision. Never lower test standards or replace the requested models with mocks in production.

## Phase 0 — Ground truth / preserve local work

- [x] Inspect actual working directory: tree, `git status`, remotes, submodules, any existing modifications and provenance. If absent, clone recursive source with no overwrites; preserve checkpoint dir.
- [x] Inventory GPU(s), driver, CUDA build, available RAM/disk, COLMAP version, existing Conda/Python/Torch and checkpoints. Record in `docs/STATUS.md`.
- [x] Execute original Object-Aware smoke commands and inspect exact data/model conventions (even if real dataset unavailable, at least native imports and adapter preflight).
- [x] Pin SAM 3.1 source revision and validate checkpoint architecture; review licenses.

**Exit:** reproducible environment report; local scientific code preserved; working branch; actual blocker list.

## Phase 1 — ONE Python GPU environment compatibility (gating)

- [x] Bring genuine SAM 3.1 into Object-Aware Python 3.10/Torch 2.5.1/CUDA 11.8 environment **without breaking native GS extensions**.
- [x] Point-prompted SAM 3.1 *real weight* first-frame mask works; both positive and negative points verified.
- [x] Genuine short video/folder propagation with >=3 images works. Check GPU use and output dimensions.
- [x] Original Object-Aware native import/training smoke still works in same environment.
- [x] Document patches, pinned revisions, unsupported optional accelerators, reproducible install.

**Exit:** all four GPU gates pass on host, or document a real **BLOCKED** incompatibility (don't silently use 2nd env/SAM2).

## Phase 2 — Project skeleton and state durability

- [x] Scaffold API/frontend, config and startup/setup/doctor.
- [x] Implement project CRUD, SQLite durable jobs, formal stage FSM and restart reconciliation.
- [x] Build polished Korean shell UI: sidebar/header, six-step progress, project home, loading/errors, GPU health indicator.
- [x] Tests: project lifecycle, invalid transitions, frontend build and no external service at runtime.

**Exit:** local launch opens real UI, project state survives restart; no fake inference outcomes.

## Phase 3 — Import with image safety

- [x] Folder/import UI + canonicalization, EXIF orientation, hashes, dimensions, thumbnails, duplicate detection and error reports.
- [x] Persist immutable source mapping, prevent path escape and invalid file crashes.
- [x] Tests: multiple extensions, spaces/Hangul, duplicate stems, corrupted images, huge inputs, restart.

**Exit:** imported images represented and inspectable with stable canonical names.

## Phase 4 — Genuine COLMAP + registration diagnostics

- [x] Safely wrap COLMAP feature extraction, matching, mapper, undistorter with logs/progress/cancel/retry.
- [x] Parse database for feature and verified matching and sparse output for registered camera poses. Show `matched` vs `registered` separately and all exclusions.
- [x] Support multiple sparse components, choose valid one and build verified undistorted `scene/images` + `sparse/0` with consistent names/calibration.
- [x] Tests: fixture partial-registration, synthetic real COLMAP scene, empty mapper output, mismatched names, unsupported camera and recovery.

**Exit:** training-ready COLMAP bundle contains ONLY selected registered views, with audited counts.

## Phase 5 — Initial SAM click and propagation

- [x] Registered-only thumbnail selection; +point / -point canvas with zoom/correct coordinate transforms; correct SAM checkpoint/model.
- [x] Deterministic capture/camera-aware ordering and bidirectional/interval propagation; image/frame name map persisted.
- [x] Genuine mask prediction persists 0/255 candidates, dimensions and QA flags; handling of occlusions, missing predictions, discontinuous viewpoints and GPU OOM.
- [x] Tests: click coordinate mapping, propagation sequence mapping, real SAM 3.1 three-frame GPU smoke, preservation of object identity across views.

**Exit:** one-frame input generates inspectable *real* candidates for all registered images, with failures honestly shown.

## Phase 6 — Human mask review/editor

- [x] Responsive overlay/zoom/pan, positive and negative prompt correction, brush/eraser, undo/redo, accept/reset, previous/next.
- [x] `남은 검토 모두 건너뛰기` confirmation and provenance status without auto-approving invalid masks.
- [x] On corrections, update local mask and optionally propagate to unchecked neighbors without overwriting confirmed frames. Atomic writes; per-frame review state survives restart.
- [x] Validate mask stem + exact undistorted image dimensions + binary values; test training mask loader.
- [x] Tests: correction persists, skip block on invalid, downstream invalidation, refresh/resume, keyboard navigation.

**Exit:** all training masks validated; review/skip recorded; training gate unlocked.

## Phase 7 — Real Object-Aware training

- [x] GPU picker lists actual devices (not fakes) and verifies selected CUDA device inside worker.
- [x] Preflight dataset, disk/VRAM, loss defaults, selected image subset; explicit train approval.
- [x] Run original `train.py`, parse real logs and progress, support cancel/restart-safe checkpoint resume if validated.
- [x] Tests: numeric masked loss/pruning invariants, child process failure status, 100-iteration smoke or suitable lightweight real GPU run, default 30K configuration unchanged.

**Exit:** verified Gaussian output from genuine Object-Aware training, no silent scientific divergence.

## Phase 8 — Mesh, viewer, export

- [x] Run original `render.py` bounded TSDF extraction, collect `fuse.ply`/post mesh; validate triangles and dimensions.
- [x] Real 3D Three.js mesh viewport, vertex color where available, orbit/pan/zoom/reset/wireframe; PLY export, optional GLB/OBJ.
- [x] Tests: mesh fixture geometry/color/export, invalid empty mesh, actual GPU extract run and visual UI inspection.

**Exit:** saved and displayed triangle mesh produced from true training artifacts.

## Phase 9 — End-to-end, resilience, polish

- [x] Test complete real sequence on local NVIDIA host using user-provided/reusable legally accessible multiview dataset, including partial COLMAP failure and manual mask correction.
- [x] Simulate interruption/restart at each stage; duplicate clicks; no GPU; OOM; subprocess nonzero; insufficient disk; mismatched masks; multiple projects.
- [x] QA: Korean wording, accessibility, keyboard, empty/failed/loading states, transparent progress; native packaging and clean-install docs.
- [x] `docs/ACCEPTANCE_TESTS.md` evidence rows all PASS; mark truly unexecutable tests NOT RUN (never PASS); review licenses, no secrets/weights committed.

**Exit / DONE:** genuine end-to-end plus documented cold-install on supported host; no critical blockers; reproducible source and artifact provenance.

## Reporting cadence

At every phase transition summarize: delivered behavior, changed paths, tests PASS/FAIL/NOT RUN with evidence, known limitations, and next phase. Finish with concise final report including exact launch command and results; only claim real GPU validation when actual host execution occurred.

## Completed local execution evidence (2026-10-15)
All checked gates refer to the actual host runs and explicitly scoped fixture tests in `docs/STATUS.md`. Full default30K physical E2E and fresh private install passed. The checklist does not certify other GPUs, arbitrary-view mask accuracy, complete geometry, or a factory-reset OS. OOM used a real per-process CUDA allocator quota; no-GPU/low-disk gates used controlled fixtures. GUI resume remains intentionally unexposed; original trusted-checkpoint CLI resume passed100→110.
