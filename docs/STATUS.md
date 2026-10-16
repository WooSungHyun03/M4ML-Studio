# Implementation status — update after EVERY loop

**Initialized:** 2026-10-15 (documentation generated remotely; **no user-host GPU execution performed**)
**Current gate:** Phase 9 completed on the inspected Ubuntu/NVIDIA host
**Overall status:** PASS — implemented and physically verified full 30K workflow + fresh private install; input-quality limitations below
**Workspace:** `/home/m4ml/Desktop/Object-Aware`

> `NOT RUN` is not `PASS`. Do not overwrite audit history; append per-cycle notes. Mark completion only with evidence. The remote repository facts in `COMPATIBILITY.md` are not proof that local sources, checkpoint, drivers or GPU work.

## Phase checklist

| Phase | Scope | State | Evidence |
|---|---|---|---|
| 0 | Machine/source inventory | PASS | `evidence/phase0-after-setup.json`, `evidence/native-smoke-baseline.log` |
| 1 | Single-env SAM 3.1 + Object-Aware GPU compatibility | PASS | `evidence/train-smoke-100.log`, `evidence/native-smoke-after-sam.log`, `evidence/sam31-smoke/result.json` |
| 2 | App skeleton, launch, durable state | PASS | `evidence/app-release-start.log`, SQLite/API tests, actual browser restart |
| 3 | Image import | PASS | 16 real UI imports + EXIF/Unicode/duplicate/corrupt/size tests |
| 4 | COLMAP registration audit | PASS | `evidence/colmap-final-cold/`, 17 input / 16 selected registered; real component selection |
| 5 | SAM 3.1 click and propagation | PASS | `evidence/sam31-cold-smoke/`, UI16-frame run, `sam31-local-cold/` |
| 6 | Mask editor/review/skip | PASS | actual UI edit/undo/redo/save/skip; `missing-mask-ui-result.json` |
| 7 | Original Object-Aware training | PASS | 30K original train:437838 Gaussians; cold100, resume110, actual GPU stop/OOM tests |
| 8 | Mesh viewer and exports | PASS | 383475 vertices / 704258 triangles; actual viewer/download hashes |
| 9 | E2E resilience and release | PASS | `evidence/cold-install-setup.log`, `e2e-release.json`,27 Python +2 frontend tests, actual faults |

## Environment observations (Codex must fill after actual inspection)

- UTC/local inspection time: 2026-10-15 actual host runs; original inventory11:21 UTC /20:21 KST, full run11:54 UTC onward
- Git branch and source commit: `studio/phase-0`; original `3221821b165865dc77b7636598e55675043b87f4`; app local commit recorded below
- SAM upstream revision: `7f473cfd983d5eb43040ff608f66bff0d7bdcb53` +3 retained compatibility patches
- Checkpoint list/SHA256 and verified identity: `sam3.1_multiplex.pt`,3502755717 bytes, SHA256 `0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6`; all1623 final-model keys/shapes match
- Linux distribution/kernel: Ubuntu24.04.3 LTS, Linux7.0.0-38-generic
- NVIDIA GPU(s), UUID(s), driver: RTX4080 / GPU-51738121-20bd-1cf6-a1b4-6671c7413cc6 /580.173.02
- `nvidia-smi`, driver CUDA compatibility: PASS; driver advertises13.0 capability; actual Torch build is11.8
- Python / Torch / Torch CUDA / torchvision: Python3.10.22 /2.5.1+cu118 /11.8 /0.20.1+cu118; NumPy1.24.4
- COLMAP version / image model support: 3.9.1 CPU build; genuine SfM/undistortion; final PINHOLE/SIMPLE_PINHOLE validated
- Disk free: initial496GiB; >470GiB after runtime backup/rebuild and real outputs
- Native Object-Aware extension import: PASS before and after SAM and fresh install; actual CUDA forward/backward + optimizer
- Genuine SAM3.1 image and propagation: PASS real positive/negative,3 contiguous frames,16 registered views and bounded local propagation

## Acceptance matrix

| ID | Status | Evidence path / command / findings |
|---|---|---|
| ENV-01 | PASS | `cold-install-setup.log`, `cold-smoke-suite.log`: exact anchor and real native CUDA |
| ENV-02 | PASS | `sam31-cold-smoke/result.json`, complete1623 key/shape match, genuine +/− masks |
| ENV-03 | PASS | `sam31-cold-smoke/frames.json`, actual3 propagation PNGs and stable ID1 |
| ENV-04 | PASS | `train-smoke-100.log`, full30K UI log, `train-cold-100.log` after fresh install |
| UI-01 | PASS | `app-release-start.log`, `ui-mesh-final.jpg`; static bundled local UI |
| UI-02 | PASS | actual server/cold restart + completed artifact audit; durable27-test suite |
| IMP-01 | PASS | actual16-image file chooser import; EXIF/Hangul/spaces/duplicates unit tests |
| IMP-02 | PASS | per-file invalid import tests, immutable raw snapshot hash checks in `e2e-release.json` |
| CLM-01 | PASS | `colmap-final-cold.log` + native CLI log: real17 photos,16 registered |
| CLM-02 | PASS | real2 components/1 unrelated excluded + synthetic matched-but-unregistered fixture; no union |
| CLM-03 | PASS | original scene loader in100/30K train; physical dimensions/PINHOLE and finite sparse points validated |
| SAM-01 | PASS | `frontend-tests-release.log`2 zoom/pan mapping tests + actual UI pixel click metadata |
| SAM-02 | PASS | actual UI16 registered-only predictions in `app-data/.../runs/ee4f5f69-f1f2-4278-bc96-908ec4e74852/` |
| SAM-03 | PASS | camera jump/coverage warnings; actual local3-view inference; empty/nonbinary/missing negative tests; no accuracy guarantee |
| REV-01 | PASS | actual erase→undo→redo→save→next→previous, persisted manual PNG and UI reload |
| REV-02 | PASS | actual15 skipped +1 manual; missing/invalid skip blocked by tests |
| REV-03 | PASS | all16 uint8 L/0,255/stem/physical-size checks in `e2e-release.json` |
| REV-04 | PASS | 27-test invalidation + actual post-training negative fixture edit leaves train/mesh pending (`missing-mask-ui-result.json`) |
| TRN-01 | PASS | full30K real RTX4080 worker log, nvidia-smi; cold API UUID mapping; `gpu-queue-cancel.json` |
| TRN-02 | PASS | `scientific-source-diff.log` empty; pinned defaults and numeric original loss-gradient tests; full30K pruning run |
| TRN-03 | PASS | 30000 iterations,437838 finite Gaussian vertices including objectmark_score; real UI progress/loss |
| TRN-04 | PASS | actual GPU stop after50 iterations; actual allocator-quota CUDA OOM; real process faults; trusted self-generated checkpoint100→110 CLI resume |
| MSH-01 | PASS | original1024 TSDF full30K result:383475 finite vertices/704258 triangles, `e2e-release.json` |
| MSH-02 | PASS | actual browser triangle viewer rotate/zoom/fit/wireframe; `ui-mesh-final.jpg` |
| MSH-03 | PASS | browser PLY/GLB download hashes equal originals; GLB loaded back,704258 faces, colors retained |
| OPS-01 | PASS | actual server death/child cleanup, GPU queue cancel, GPU train stop; orphan fixture for all stages; restart artifact revalidation; `sse-shutdown.json`10.25s |
| OPS-02 | PASS | Host/Origin/token, UUID/path/symlink/request quota, literal argv tests, real loopback bind |
| OPS-03 | PASS | retained original/native/SAM licenses and runtime frontend notices; SOURCES.json; Git ignores weights/data/evidence; no push |
| E2E-01 | PASS | Cycle7 actual UI16-photo import→COLMAP→SAM3.1→manual/skip→original30K→original1024 TSDF→viewer/export; `e2e-full-verified.json`; 2026-10-16 independent re-audit `recovery-e2e-audit-2026-10-16.json` |

## Loop log (append newest cycle; never invent)

### Cycle 0 — pending on local machine
- Objective: inspect workspace, upstream code, checkpoints and GPU compatibility.
- Files changed: documentation only (prepared outside user machine).
- Test commands/exit codes: NOT RUN.
- Known blockers: Object-Aware vs SAM3.1 officially documented environment mismatch; actual local checkpoint contents unknown until inspected.
- Next action: run preflight as described in `AGENTS.md` and `docs/LOOP_PLAN.md`.

### Cycle 1 — 2026-10-15, actual Phase 0 inventory
- Read every root instruction and every Markdown file in `docs/` in full. Initial root had only specifications and `models/`; no application or Git repository. Preserved all existing files.
- Initialized Git, fetched original source, checked out `studio/phase-0` at `3221821b165865dc77b7636598e55675043b87f4`. Fetch did not set `origin/HEAD`; checked out verified `origin/main` instead. No push/merge.
- Recursive upstream modules: rasterizer `e0ed0207b3e0669960cfad70852200a4a5847f61`, simple-knn `86710c2d4b46680c02301765dd79e465819c8f19`, GLM `5c46b9c07008ae65cb81ab79cd677ecc1934b903`.
- Official SAM added as pinned submodule `vendor/sam3`, SHA `7f473cfd983d5eb43040ff608f66bff0d7bdcb53`. Inspected actual model builders, point request API, notebook, frame loader, release notes and licenses.
- Host: Ubuntu 24.04.3, kernel 7.0.0-38, RTX 4080 16376MiB, driver 580.173.02 (driver advertises CUDA 13.0; this is NOT Torch build CUDA). RAM 62GiB; free disk initially 496GiB. `nvcc` on PATH is 12.0; verified `/usr/local/cuda-11.8/bin/nvcc` is 11.8.89. GCC 11 available alongside system GCC 13. COLMAP 3.9.1 without CUDA; CPU SfM remains usable. Node 22.23.2 / npm 9.2.0.
- Local checkpoint `sam3.1_multiplex.pt`, 3502755717 bytes, SHA256 `0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6`. Checkpoint README identifies SAM3.1, but tensor/model identity still NOT RUN pending safe load. Source and checkpoint SAM license retained in `licenses/`; original noncommercial GS licenses retained unchanged.
- Implemented read-only `studio/doctor.py`, `scripts/doctor.sh`; command arrays, timeout/error preservation, SHA256 inventory and atomic JSON output. `.gitignore` excludes runtime, models, user data and evidence.
- PASS: `python3 -m unittest discover -s studio/tests -v` (3 tests, 0.131s). This is diagnostic unit coverage, NOT inference/E2E proof.
- FAIL as expected before installation: `./scripts/doctor.sh --output evidence/phase0-before-setup.json` returned 1; Torch/native probes raise `ModuleNotFoundError: torch`. Logs: `evidence/phase0-before-setup.log`.
- Existing base/openvpr/panovggt/pyslam/viewer environments untouched. Created project-local `.runtime` Python 3.10 using existing Conda; anchor Torch 2.5.1/cu118 installation in progress.
- Next: finish pinned runtime, compile both native extensions with CUDA11.8/GCC11, run original CLI/import/GPU smoke, safely inspect checkpoint tensor keys and genuine SAM3.1 inference in SAME runtime. No UI/training/SAM/mesh acceptance marked PASS.

### Cycle 2 — anchor build and genuine SAM debugging (2026-10-15)
- PASS: private Python3.10 + `torch 2.5.1+cu118`, torchvision0.20.1, numpy1.24.4 installed. Real CUDA allocation/reduction on RTX4080 succeeds. All existing environments untouched.
- Initial native wheel build FAIL (`evidence/build-native.log`): `sh: 1: cicc: not found`. Root cause: `/usr/local/cuda-11.8` contained only a symlink to cached nvcc, no full toolkit. Installed exact cached CUDA11.8.89 nvcc/cudart/dev/cccl/driver-dev packages offline INTO `.runtime` only. Rebuild with `CUDA_HOME=$PWD/.runtime CC=/usr/bin/gcc-11 CXX=/usr/bin/g++-11 MAX_JOBS=4 TORCH_CUDA_ARCH_LIST=8.9` succeeds for both original extensions (`evidence/build-native-fixed-toolkit.log`). No scientific source changes.
- Safe checkpoint inventory PASS: `.runtime/bin/python -m studio.checkpoint models/sam3.1/sam3.1_multiplex.pt --output evidence/sam31-checkpoint.json`; 1623 tensors / 874365676 elements, tracker457 + detector1166, float32/complex64. No arbitrary pickle execution.
- Genuine SAM model construction PASS in anchor runtime, complete final model/checkpoint key AND shape match for all 1623 tensors. `use_fa3=False`, `use_rope_real=False`, compile/warmup disabled using official supported flags. Preliminary tracker loader prints many missing/unexpected keys because it receives the merged checkpoint before final assembly; final assembled model match is complete (independently asserted).
- First real inference attempt FAIL before session: upstream `Sam3BasePredictor.start_session` passes `offload_state_to_cpu` unsupported by multiplex init_state. Repro log `evidence/sam31-smoke-first.log`. Minimal patch `patches/sam3/0001-session-init-option.patch` omits unsupported FALSE default, explicitly rejects unsupported TRUE. Regression tests preserve original model's supported offload.
- Next real attempt FAIL: first point returned empty object IDs despite inference. Actual upstream `_build_sam2_output` returns `{}` before merging a newly prompted mask when no detector cache exists. Minimal `0002-first-point-output.patch` retains genuine refined tracker output on initial uncached frame; no fabricated masks, no architecture/loss changes. Repro log `evidence/sam31-smoke-session-fix.log`. Rerun pending.
- PASS 6 diagnostic/session unit tests (`evidence/unit-cycle2.log`, exit0). This does NOT prove inference.
- Prepared official SAM video frames0–2 under ignored evidence; compatibility smoke uses positive pixel760,550 and negative560,450, preserves frame hashes. Downloaded official COLMAP South Building sample for later real reconstruction, no precomputed camera model/database used. No product E2E claim.
- Next: complete CUDA renderer forward/backward baseline, finish genuine positive/negative + propagation; then original training smoke in same runtime. Phase1 remains IN PROGRESS.

### Cycle 3 — genuine SAM3.1 point/propagation PASS on RTX4080 (2026-10-15)
- Phase0 inventory EXIT satisfied: original code/submodules preserved, working branch, reproducible doctor after installation returns0; train.py/render.py `-h` both execute (logs `evidence/train-help.log`, `evidence/render-help.log`). Native renderer real CUDA output/backward/optimizer PASS.
- Native fixture initial FAIL was a smoke harness error: original Camera stores RGB on CPU; original training explicitly calls `.cuda()`. Fixed harness to follow original behavior. Scientific code unchanged. PASS loss0.8145586, all geometry/opacity/ObjectMark gradients finite and nonzero (`evidence/native-smoke-baseline.log`).
- Real initial SAM masks now work after two documented upstream API/cache patches: positive area94079 px, after negative area93899 px. A propagation call without explicit start fails because official detector state has no text/box outputs in a point-only session. Fixed adapter call to provide documented `start_frame_index=0`; no third scientific patch required.
- PASS `.runtime/bin/python -u scripts/smoke_sam31.py --checkpoint models/sam3.1/sam3.1_multiplex.pt --frames evidence/sam31-frames --positive 760 550 --negative 560 450 --output evidence/sam31-smoke` with `CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=4`. Exit0. Exact log: `evidence/sam31-smoke-explicit-start.log`; result/frames JSON and 5 actual masks under `evidence/sam31-smoke/`. Propagation areas93568,91423,89701; all720×1280 binary nonempty, ID1. Full checkpoint key/shape equality1623. Python3.10.22 / Torch2.5.1+cu118, RTX4080. This is a contiguous video compatibility check, NOT registered multiview/E2E proof.
- Implemented `studio/process.py` safe literal argv/logging/process groups/cancel/timeout and `studio/colmap.py` genuine extraction→matching→mapper→undistorter, original binary model readers, per-image verified matching vs selected registration, coherent camera/image validation. Real16-photo COLMAP integration running from raw South Building images; no imported database/poses.
- Added first-click/cache-preservation regression tests. `scripts/apply_sam_patches.py` idempotent. Runtime package freeze saved `evidence/runtime-freeze.txt`.
- Phase1 NOT yet complete: original train.py smoke after SAM is still pending genuine reconstructed scene + valid masks. Product UI and full E2E remain NOT RUN. Next: finish actual COLMAP sample, run SAM on registered subset, original training then native recheck; proceed to durable application slices.

### Cycle 4 — original train.py GPU smoke PASS; Phase1 EXIT (2026-10-15)
- PASS actual COLMAP3.9.1 CPU pipeline on16 raw photographed views from official South Building sample. Rebuilt database from scratch;104 verified pairs;16/16 registered in one component. Undistorted physical photo sizes match parsed PINHOLE cameras. `OMP_NUM_THREADS=4 .runtime/bin/python -m studio.colmap datasets/south-building-sample/images evidence/colmap-real-1` exit0; full CLI logs and report retained. No precomputed poses used.
- Added real registered-only `studio/sam31.py`: original official SAM3.1 model, full weight key/shape check, camera-center/direction nearest traversal, reversible mapping, viewpoint jump warnings, per-image padding/crop preserving exact pixels for mixed camera sizes, binary validation. Genuine SAM outputs produced for all16 registered views (coverage0.057–0.174). Metadata/logs `evidence/sam31-registered-1/`, `evidence/sam31-registered-1.log`; request records exact test prompts. This is an adapter test with test-selected building region, not user product target approval.
- PASS16 mask dimension/stem/uint8/0,255/nonempty integrity checks; copied only validated SAM masks into scene/mask for explicit scientific smoke (`evidence/training-mask-preflight.json`).
- PASS original `CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=4 .runtime/bin/python -u train.py -s evidence/colmap-real-1/scene -m evidence/train-smoke-100 --iterations 100 --checkpoint_iterations 100 --port 6017`, exit0. Original default losses/pruning untouched.2763 Gaussian vertices,100 iterations, loss0.79910 at finish, real PLY and chkpnt100.pth written. Explicit100-iteration SMOKE ONLY, not30K convergence. `evidence/train-smoke-100.log`.
- PASS original native renderer after SAM (same Python/runtime/GPU), exact same fixture loss0.8145586. `evidence/native-smoke-after-sam.log`.
- PASS11 focused tests: doctor, real subprocess fail/timeout/cancel, independent matching vs registration, two SAM defect regressions (`evidence/unit-cycle4.log`). Synthetic database fixtures are not GPU evidence.
- Current: original render.py TSDF smoke is running at explicit test mesh_res128; not yet PASS. Phase2 durable app starts next. All UI acceptance remains NOT RUN. One environment compatibility is empirically established on this host for exercised paths; no general GPU/version guarantee.

### Cycle 5 — durable app + import/review/training API + built local UI (2026-10-15)
- Implemented SQLite/WAL project documents, unique active-job index, durable events and JSON manifest snapshots; per-project edit locks, revision invalidation, orphan reconciliation. Foreground Python worker launches genuine adapters; serial GPU locks and per-job `CUDA_VISIBLE_DEVICES`; cancellation preserves logs/artifacts. Linux parent-death wrapper prevents abandoned scientific child processes on backend/worker death. Native scientific files unchanged.
- Safe file upload/import: immutable raw snapshot, EXIF transpose, source/normalized SHA256, canonical naming, thumbnails, duplicate reporting/exclusion from SfM, per-file corrupt reports, size/pixel/file-count/disk bounds. No arbitrary input path API. Added localhost Host/Origin and unpredictable CSRF header checks; project artifact traversal/symlink protection.
- Implemented registered-only prompting, explicit first-mask preview confirmation, mask propagation, review/skip gating, binary/aligned manual mask save, original train approval/preflight, auto original TSDF after training, parsed mesh/GLB load-back validation and native exports.
- React/TS/Vite Korean UI includes six persistent stages, real import thumbnails, matched/registered diagnostics, +/− points, brush/erase, overlay, zoom/pan, undo/redo, previous/next, save/approve and explicit skip. Three.js GLB triangle viewer is dynamically loaded; orbit/pan/zoom/fit/wireframe and native PLY/GLB export. No CDN or cloud runtime dependency. React checklist applied (typed props, hook cleanup, viewer resource disposal, independent lazy chunk).
- PASS frontend `npm run build --prefix frontend` (TypeScript and static build; mesh chunk586KB warning retained, already lazy). PASS17 focused API/state/process/SAM tests (`evidence/unit-cycle5.log`, `unit-cycle6.log`), includes original-file preservation, EXIF/Unicode, duplicate/corrupt handling, explicit train approval, missing-mask skip block, manual invalidation, stale worker and path/origin failures. These synthetic API fixtures do NOT count as GPU E2E.
- PASS original render.py real TSDF on100-iteration smoke, `--skip_train --skip_test --mesh_res 128`; generated actual fuse.ply + fuse_post.ply. Parsed finite mesh9659 vertices, valid triangles; GLB export reload matches face count (`evidence/mesh-smoke-validated/mesh_report.json`). This is a coarse smoke result, not converged reconstruction quality.
- Added `scripts/setup.sh`, `scripts/start.sh`, `scripts/smoke.sh` and pinned API deps. Running actual local service loopback8765 with test-specific storage `evidence/app-data`; `evidence/app-launch.log`. Browser opened actual built UI, created project and began importing16 real photos through file chooser. UI E2E remains IN PROGRESS until actual complete interaction and screenshot validation.
- Next: browser COLMAP→click preview→propagate→manual edit/skip→explicit training→automatic mesh viewer/export; test interruption/reopen and finish remaining gaps. Phase2/3 implemented, not yet acceptance-complete pending browser and regression evidence.

### Cycle 6 — browser E2E and worker lifetime fix (2026-10-15)
- Browser created `cba71418-86e9-4d0b-9e74-c3bbacf70839` (South Building 실제 GPU 검증), uploaded16 real JPGs through file chooser, verified canonical thumbnails and initiated genuine COLMAP via UI.
- Initial UI COLMAP run CANCELLED unexpectedly after matching. Root cause: Linux PR_SET_PDEATHSIG binds the creating thread; FastAPI request thread retirement falsely terminated the worker although the server process remained alive. Removed PDEATHSIG from API→worker dispatch; worker now monitors server PID+start time. Retained PDEATHSIG for stable worker→scientific child to prevent orphaned CUDA. Retry after actual server restart finished16/16 registration, proving work/input persistence.
- UI actual +point380.206,349.493 and −point868.402,300.854 map correctly to undistorted1009×753 image. Genuine preview confirmed, then actual16-frame propagation completed. UI erase stroke→undo→redo→save, next→previous verified persisted `manual` mask. Explicit remaining-review skip records15 masks as `skipped`, leaves manual correction intact. Target/preview and all mask validity gates respected.
- Default30K original train launched through actual UI explicit confirmation on physical GPU0/RTX4080. Log `evidence/app-data/projects/cba71418-86e9-4d0b-9e74-c3bbacf70839/logs/8bbc506c-5dd4-4120-966b-b09b59569db7.log`; currently RUNNING, not PASS until completion/artifact verification. Native losses/pruning defaults unchanged; pruning regime reached. Auto TSDF follows successful training.
- Real partial-registration test:17 photographs including unrelated SAM truck asset → components0(2 cameras) and1(16 cameras), selected largest1. Unrelated photo has2780 features but NO verified match/pose, excluded from final scene. `evidence/colmap-partial-real/`; explicit selected-component re-undistortion passed (`evidence/colmap-component-selected/`). Initially requested component0 expecting16 was correctly rejected by then-min3 guard; corrected test selected actual reported component1. Aligned import/scene minimum to architecture's2 distinct registered views (UI recommends3+); no blind component numbering assumptions.
- Added soft project archive/restore (files retained), matching-mode/component selection, resolution setting with explicit user choice and original default-1, GPU OOM guidance, request-body bounds, cancel-before-worker-start flag, first-unfinished-stage reopen and prompt restoration. Fixed thumbnail flex shrink discovered in actual desktop screenshot. All edits require new build/restart before final UI verification.
- Regression expanded to original masked-loss gradients/defaults, point-cloud rejection and mesh loadback, exact zoom/pan click coordinate mapping. Initial point-cloud validator raised AttributeError instead of controlled ValueError; fixed explicit triangle-mesh type check.22 tests then PASS (`evidence/unit-cycle8-fixed.log`); latest expanded suite pending.
- SAM NumPy metadata lower bound locally adapted to1.24.4 AFTER real SAM+Object-Aware passes; patch0003 retained. `pip check` now exit0 (`evidence/pip-check-final.log`), without upgrading anchor NumPy/Torch. Production npm audit0 known vulnerabilities. No push/merge.
- Next: finish default30K→automatic1024 TSDF, validate/view/export in browser, full regression, cold private install reproduction, restart and security fault checks, final docs/license audit.

### Cycle 7 — full 30K E2E, genuine mesh, exports and cold installation PASS (2026-10-15)
- Full UI project `cba71418-86e9-4d0b-9e74-c3bbacf70839` completed all6 stages. Original30K train produced437838 finite Gaussians with ObjectMark scores. Original render.py at default1024 produced post mesh383475 vertices /704258 triangles. PLY SHA256 `908958e0a9011414949158e5ca39745e731cc7afb927395fd65bcc634b5d7c1d`; GLB SHA256 `26f4e739d4e55b79a8a5dbf4265dc27aa6a1379b7e6b047b4c55dc2140d897a7`.
- Actual browser displayed real triangular geometry; rotate/zoom/fit/wireframe checked. Native PLY/GLB downloaded to Downloads and byte hashes match originals; GLB loadback face count matches. Screenshot `evidence/ui-mesh-final.jpg`. This is a real partial building surface with occlusion/holes, not a claim of complete/watertight geometry or paper benchmark quality.
- All primary artifacts independently re-read and hashed: `scripts/verify_project.py ... --output evidence/e2e-full-verified.json`.16 selected registered names equal mask set;1 manual,15 explicitly skipped; binary/size/stem integrity; finite Gaussian fields and real mesh triangles.
- Private environment, Node modules, UI dist and native build outputs moved (not deleted) into `evidence/cold-install-backup/`. `./scripts/setup.sh` recreated a fresh `.runtime`, installed exact anchor + private full CUDA11.8 toolkit, rebuilt native extensions and static UI, applied SAM patches idempotently. Exit0 (`evidence/cold-install-setup.log`). Existing global Conda/system environments unchanged. This is a fresh application environment on the inspected host, not a factory-reset OS or different-GPU certification.
- Fresh runtime PASS:27 Python tests,2 frontend coordinate tests, TypeScript/Vite build, original CUDA renderer backward/optimizer, genuine SAM positive/negative+3 propagation (`sam31-cold-smoke`), original100 train (`train-cold-100.log`), trusted own checkpoint resume100→110 (`train-resume-110.log`), pip check0 broken requirements. Native fixture loss identical0.8145586 before/after. Source scientific diff against original remains EMPTY.
- Real cold-runtime local registered propagation with radius2 produced only3 expected frames (`sam31-local-cold`). Cold API repeat fixture reuses genuine calibrated16-view scene/masks from the full E2E, rather than inventing poses/inference. It ran genuine preview/local propagation, retained approved/manual and outside-interval masks, explicitly approved100 training, automatic128 TSDF, verified export hash and soft archive (`cold-api-result.json`). This repeat is a smoke, separate from the original browser full30K run.
- Local correction now offers bounded neighboring unchecked views; previously approved/manual/skipped masks remain protected. Default scientific losses unchanged. Periodic original checkpoint saves every5000/end add recoverable files without changing optimization; UI retry starts a separate run, no unverified cross-run resume claim.

### Cycle 8 — real failure/recovery checks and release audit (2026-10-15)
- Actual CPU-worker tests PASS: short-lived request thread no longer cancels worker; native COLMAP nonzero exit records failed; startup cancellation records cancelled; killing owning test server stops its real COLMAP child. `evidence/fault-integration-1/results.json`. No fake subprocess success.
- Actual CUDA OOM generated by0.002 PER-PROCESS Torch allocator quota while running unchanged original train.py, without exhausting global VRAM. Genuine `torch.OutOfMemoryError` trace, failed job and Korean guidance; no completed100 artifact (`evidence/oom-real-cold/`).
- Actual shared physical-GPU OS lock test PASS: worker waits, no scientific child is launched while locked; waiting job cancels (`gpu-queue-cancel.json`). Actual original GPU training stopped after50 real iterations; nvidia-smi confirmed child GPU allocation, child exited, config/log preserved and no false30000 artifact (`gpu-training-cancel.json`).
- Actual open-SSE graceful shutdown initially waited indefinitely. Added uvicorn10s shutdown deadline; measured10.25s with an open SSE stream, exit confirmed (`sse-shutdown.json`). No active work was lost in this shutdown test.
- Startup audits actual completed camera/sparse, mask, training and mesh files; corrupted/deleted fixtures invalidate downstream stages instead of retaining false success. Schema v1, cancellation-start flag, soft archive/restore and private project permissions included.
- Negative browser fixture found failed-mask decode could prevent full photo display. Fixed fallback: photo remains visible, invalid mask can be re-prompted/restored/painted; empty masks still blocked. Actual browser recovered original candidate and saved manual mask; previous real training/mesh remain pending after edit (`missing-mask-ui-result.json`, `ui-missing-mask-recovery.jpg`). Initial mask preview allows point prompts; brush/save become available during real candidate review. Clearing old error metadata and COLMAP stale preview state covered in regression.
- Final Python suite27 PASS (`evidence/tests-final-freeze.log`, then latest `tests-last.log`); frontend2 PASS and release build PASS. Build reports a ~587KB lazy Three.js chunk; it is loaded only for mesh view. Runtime production npm audit0 known vulnerabilities; no CDN or cloud requests required. Root research files/native sources unchanged, pins/patch hashes in `SOURCES.json`.
- Genuine full30K project copied, without overwriting any existing project, to normal default storage: `/home/m4ml/.local/share/object-aware-studio/projects/cba71418-86e9-4d0b-9e74-c3bbacf70839`. Files independently audited there (`evidence/e2e-release.json`). Logs preserve original execution locations. A normal `./scripts/start.sh` can reopen the result; test-only negative projects remain under ignored evidence storage.
- No hard external blocker remains on this host. Limits: only this RTX4080/Ubuntu stack physically certified; unordered wide-baseline propagation may fail and needs review; demo partial/occluded views produce partial surfaces; mesh completeness/watertightness not guaranteed; source licenses remain noncommercial research/evaluation. GUI training resume is not exposed; trusted original CLI resume was smoke-tested.
- Next: user imports their own suitable object photographs; future changes must preserve this evidence baseline and rerun affected gates. No automatic push/merge.

### Cycle 9 — interrupted-session recovery and release verification (2026-10-16)
- Re-read AGENTS.md, CODEX_PROMPT.md and every docs Markdown file; inspected full filesystem inventory (`evidence/recovery-file-inventory.txt`), branch/remotes/submodule pins, recent commits, uncommitted source and two running local servers. Preserved runtime, checkpoints, data, all previous logs and original scientific source. Last unfinished work was release verification/Git preservation, not a missing scientific pipeline phase; did not rebuild completed phases or rerun the entire30K unnecessarily.
- Found an inconsistent acceptance row: E2E-01 still read NOT RUN despite the original physical run and Cycle7 artifact evidence. Corrected only after independent current-file verification. This recovery re-audits the existing30K run; it is not a claim of a second30K run.
- PASS (exit0): `./scripts/smoke.sh > evidence/recovery-smoke-2026-10-16.log 2>&1`:27 Python tests,2 frontend mapping tests, TypeScript/Vite production build, actual original CUDA renderer forward/backward/optimizer. Native loss0.8145585656 matches baseline. The lazy Three.js bundle warning remains (~587KB); actual viewer loads successfully.
- PASS (exit0): `./scripts/doctor.sh --output evidence/recovery-doctor-2026-10-16.json`; current RTX4080/driver580.173.02, private Python3.10.22/Torch2.5.1+cu118, native extensions and checkpoint identity. Original source and patch SHA256 checks match SOURCES.json; `git diff origin/main -- train.py render.py arguments scene gaussian_renderer utils` is empty. `pip check` reports no broken requirements. Idempotent SAM patch application reports all3 already applied.
- PASS (exit0): `CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=4 .runtime/bin/python -u scripts/smoke_sam31.py --checkpoint models/sam3.1/sam3.1_multiplex.pt --frames evidence/sam31-frames --positive 760 550 --negative 560 450 --output evidence/recovery-sam31-2026-10-16`. Real checkpoint load/all1623 keys and shapes; positive area94079, refined93899; propagated93568/91423/89701 pixels,720×1280, stable object1. Log `evidence/recovery-sam31-2026-10-16.log`. This is an actual GPU compatibility smoke, separate from the prior registered16-view E2E.
- PASS (exit0): `.runtime/bin/python scripts/verify_project.py --data /home/m4ml/.local/share/object-aware-studio --project cba71418-86e9-4d0b-9e74-c3bbacf70839 --output evidence/recovery-e2e-audit-2026-10-16.json`. Re-read raw/normalized hashes, all16 calibrated registered images and binary masks (1 manual,15 skipped),437838 finite Gaussian vertices at30000,383475 mesh vertices/704258 triangles; PLY/GLB hashes match Cycle7.
- Confirmed neither server had an active job, gracefully stopped only our old8765/8766 servers, then launched current code with `./scripts/start.sh > evidence/app-final-start-2026-10-16.log 2>&1`. Default user store reopened all6 completed stages after actual artifact audit. Test-only8766 service remains stopped. Browser on8765 displays genuine mesh; compact768px test has no horizontal overflow. Temporary viewport reset; wireframe/fit controls pass and browser console reports no errors. Screenshots: `evidence/ui-recovery-768-2026-10-16.jpg`, `evidence/ui-recovery-final-2026-10-16.jpg`.
- Release staging contains source/docs/licenses only (68 entries before .gitattributes), no checkpoint/data/log artifacts. Initial staged whitespace check flagged a Markdown hard break and required blank context lines inside literal patch files. Removed the unnecessary Markdown spaces and recorded `.gitattributes` for patch-context whitespace; compatibility patch bytes and SOURCES hashes remain unchanged. Rechecked staged diff before commit.
- Remaining technical blockers: none identified on this host. Keep Cycle8 quality/platform/license limits: the mesh is a partial occluded building surface, not a watertight/complete-object quality claim; other GPUs are unverified. No dataset/checkpoint/log artifacts are committed, no push/merge. SAM submodule's3 local compatibility edits are intentionally retained and reproducible from tracked parent patches; its Git pin remains the official upstream revision.
- Resume commands: `cd /home/m4ml/Desktop/Object-Aware && ./scripts/start.sh`; open `http://127.0.0.1:8765/?project=cba71418-86e9-4d0b-9e74-c3bbacf70839`. For future changes run `./scripts/smoke.sh`, then affected real adapter checks. Next work is a new user dataset, not an unimplemented Phase.
