# Architecture — M4ML Studio 0.3 (+ desktop editor)

> Current, implemented architecture. The original 0.1–0.2 design notes are preserved
> unchanged in the appendix at the end of this file; ADRs live in `docs/DECISIONS.md`.

## 1. Overview

```text
 Desktop shell  studio/desktop (PySide6 + QtWebEngine; launched by scripts/launch.py)
   │  native window/dialogs/downloads via QWebChannel; spawns the API on a free loopback
   │  port with a per-launch token (injected into the page only); stops it on close
   │  (developer mode: scripts/launch.py --browser → system browser on STUDIO_PORT)
 React + TypeScript + Vite UI (static build, served by the API)
   │  HTTP JSON + SSE (per-project event stream), CSRF token header, Host/Origin checks
 FastAPI service  studio/api.py   (loopback only; never imports torch/CUDA)
   │  project/job bookkeeping (SQLite WAL, studio/store.py) · validation gates
   │  live object selection queue (studio/live_prompt.py, latest-wins)
   │  persistent selection sessions (studio/segmentation_session.py)  ───┐
   │                                                                      │ stdin/stdout JSON
   ├── one worker process per job  studio/worker.py  (orchestration only) │
   │      └── capability providers  studio/providers/*  (engine adapters)  │
   │             ├─ camera        → bundled CUDA COLMAP 4.2.1  runtime/colmap/bin/colmap
   │             ├─ segmentation  → official SAM 3.1 (studio/sam31.py, child process)
   │             ├─ training      → ORIGINAL Object-Aware train.py (child process)
   │             ├─ mesh          → ORIGINAL 2DGS render.py TSDF (child process)
   │             ├─ export        → PLY vertex RGB → linear COLOR_0 GLB (studio/mesh.py)
   │             └─ rendering     → live Gaussian view (API-side session, see below)
   └── studio/sam31_session.py  (model kept loaded on one GPU; ≈0.2 s per click) ◄──┘
 Per-GPU OS lock  studio/gpu_lock.py  shared by workers and selection sessions
 Data   $XDG_DATA_HOME/m4ml-studio (or legacy object-aware-studio)/projects/<uuid>/
 Config $XDG_CONFIG_HOME/m4ml-studio/settings.json (schema v2, migrated with backup)
```

Responsibilities are split so that:

* the **UI** knows only capabilities (카메라 정합, 객체 선택, 마스크 생성/검토, 3D 재구성,
  3D 모델 생성/보기). Engine names appear only in Settings › 고급 정보 (`GET /api/engines`);
* the **API process** validates requests, persists state, schedules jobs and owns the live
  selection sessions, but never runs GPU code itself;
* the **worker** turns a job record into provider calls, owns the GPU lock, cancellation,
  invalidation of downstream stages and durable job state;
* **providers** wrap one engine each and return plain data contracts.

## 2. Capability provider interfaces (`studio/providers/base.py`)

| Capability | Interface | Methods | Current implementation |
|---|---|---|---|
| Camera reconstruction | `CameraProvider` | `reconstruct(ctx, images, work, request)`, `select_component(...)`, `validate_scene(scene)` | `ColmapCameraProvider` (`camera_colmap.py`) |
| Object segmentation + propagation | `SegmentationProvider` | `predict(ctx, request)`, `propagate(ctx, request)`, `session_command()` | `Sam31SegmentationProvider` (`segmentation_sam31.py`) |
| Reconstruction training | `TrainingProvider` | `validate_dataset`, `train(ctx, scene, model, request)` (incl. resume), `parse_progress(line)`, `checkpoints(model)` | `ObjectAwareTrainingProvider` (`training_object_aware.py`) |
| Mesh extraction | `MeshProvider` | `extract(ctx, scene, model, iterations, output, request)` | `ObjectAwareTSDFMeshProvider` (`mesh_tsdf.py`) |
| Visualization / export | `ExportProvider` | `validate_and_preview(mesh, output)` | `VertexColorGlbExportProvider` (`export_glb.py`) |

Common to all: `info()` (name, version, paths, verification, license — advanced UI only)
and `requires_gpu(request)` (worker takes the per-GPU lock only when true).

**Execution contract.** Long methods run in the worker process, receive a `JobContext`
(`root`, `output`, `log`, `env` with `CUDA_VISIBLE_DEVICES`, `cancel` event, `progress()`,
`run()`/`python()` for literal-argv child processes with process-group cancellation and
durable logs). Providers must not choose a GPU, mutate the project document, or show raw
tracebacks; they raise Korean `ValueError`/`RuntimeError` messages and the worker records
the traceback in the job log. `studio.process.Cancelled` signals cooperative cancellation.

**Interactive sessions.** `SegmentationProvider.session_command()` returns the argv of a
long-lived process speaking a line-delimited JSON protocol (`predict` → mask PNG + stats,
`close`). The API keeps at most one per GPU, holds the GPU lock while it lives, closes it
after `session_idle_seconds` (default 600) or immediately before any GPU job
(`segmentation_session.release(device)`), and the process exits if the API dies.

### 2a. Rendering provider (live Gaussian view, "실시간 렌더")

`RenderingProvider` (`studio/providers/base.py`, registry key `rendering`, default
`gaussian_remote` in `studio/providers/render_gaussian_remote.py`) is driven by the
API-side session manager `studio/live_render.py`, not by the worker, because it is interactive:

```text
GaussianViewer.tsx ─POST /live-render/frame (camera, size, mode)─▶ live_render._Session
   ▲  JPEG (moving) / PNG (still)                                   │ RenderingProvider.render
   │                                                                ▼ SIBR remote wire protocol (loopback, OS port)
   └──────────────────────────────── studio/gaussian_render_server.py (GPU child: original render())
                                       ▲ optional: runtime/sibr/bin/SIBR_remoteGaussian_app attaches here
```

Methods: `locate_model` (validated Gaussian PLY, iterations, cameras, orbit target),
`server_command`, `connect`, `render`, `modes`, `external_viewer_command`. The session holds
the per-GPU lock; GPU jobs and object selection release it; stop/idle/backend death end the
child. Details and measurements: `docs/GAUSSIAN_VIEWER_INTEGRATION.md`.

## 3. Data contracts

Providers exchange plain JSON-serialisable records (dataclasses in `base.py`, all carry
`version`):

* `RegisteredImageSet` — scene dir (`images/`, `sparse/0/`), registered names, coordinate
  system **`colmap-undistorted-pinhole-pixels`**: every mask, click and training image is in
  the pixel frame of the undistorted registered image (never the original photo).
* `CameraReport` — per-image features / verified-match / registered flags + reason, number
  of verified pairs, reconstruction components and the selected one, and `engine` (version,
  CUDA build, per-step `gpu_requested`/`gpu_observed`/`gpu_peak_mb`).
* `MaskResult` — binary uint8 0/255 PNG aligned to its image, area, coverage, sha256,
  warnings (discontinuity, coverage jump), provenance (`generated`/`imported`/`manual`).
* `TrainingProgress`, `TrainingResult` — iteration/total/loss; model dir, Gaussians,
  resumed-from checkpoint.
* `MeshArtifact` — PLY + GLB preview, vertices, triangles, colour presence/statistics,
  colour round-trip error.
* `ProjectManifest` — the project document (`schema_version`), mirrored to
  `projects/<id>/manifest.json` on every update; stage states, provenance, revision.

Engine-specific tensors and file layouts never cross the provider boundary.

## 4. Replacing an engine

1. Implement the interface in a new module under `studio/providers/` (e.g.
   `segmentation_newmodel.py`) with `capability`, `key`, `display_name`, `info()`.
2. Register the class in `studio.engines.registry()`.
3. Select it in configuration — no UI change:
   ```json
   // ~/.config/m4ml-studio/settings.json
   {"schema_version": 2, "engines": {"segmentation": {"provider": "newmodel", "options": {...}}}}
   ```
4. Add a CPU contract test (see `studio/tests/test_engines_providers.py`) and a real
   GPU check before marking it verified.

Defaults and option names are in `studio/engines.py::DEFAULTS`. Projects record which
engine produced each artifact (`training.engine`, `mesh.engine`, `colmap_report.engine`).

## 5. Jobs, processes and GPU memory

* One running job per project (unique SQLite index). Each job = `python -m studio.worker
  <job_id>` started in its own session; scientific programs run under `studio/child.py`
  (PDEATHSIG + process group) so killing the worker kills them.
* Worker monitors the API process identity (`STUDIO_OWNER_PID`/`START`) and cancels if it
  disappears; startup `Store.reconcile()` terminates stale workers, marks interrupted jobs
  cancelled and re-audits completed artifacts (scene, masks, Gaussians, mesh hashes).
* GPU stages (camera on GPU, propagation, training, mesh) take `gpu_lock` for the selected
  device; the live selection session releases first. CUDA OOM becomes a Korean message with
  guidance, the job fails cleanly and inputs/previous results are kept.
* Training checkpoints every 2,500 iterations (newest two kept). Pause = cancel; the worker
  records `training_partial` with an input fingerprint (mask hashes, scene, iterations,
  resolution). Resume runs the original `train.py --start_checkpoint` only if the
  fingerprint is unchanged.

## 6. Configuration layers

| Layer | Location | Contents |
|---|---|---|
| Built-in defaults | `studio/engines.py`, `studio/config.py` | engine selection/options, training defaults |
| User settings | `~/.config/m4ml-studio/settings.json` (schema 2) | engines, model paths; v1 migrated with `settings.v1.json` backup |
| Install record | `~/.config/m4ml-studio/install.json` | app/runtime/COLMAP locations written by the installer |
| Project settings | project document | per-project choices, provenance |
| Environment | `STUDIO_DATA`, `STUDIO_PORT`, `STUDIO_RUNTIME`, `STUDIO_COLMAP`, `STUDIO_SAM_CHECKPOINT`, `STUDIO_SAM_MEMORY_FRACTION` | overrides for tests/advanced users |

COLMAP binary resolution: settings → `STUDIO_COLMAP` → bundled `runtime/colmap/bin/colmap`
→ installer record → `PATH`. GPU jobs require a CUDA build (`colmap help` banner); a CPU run
needs an explicit, confirmed request (`cpu_fallback` + `confirmed`).

## 7. Compatibility and updates

* Project documents carry `schema_version`; the store snapshots the SQLite database before
  the first open by a new release (`backups/`). Artifacts are re-audited on startup;
  incompatible or modified artifacts invalidate downstream stages instead of failing silently.
* Settings migrate forward with a backup (`studio/config.py::migrate`, tested).
* Legacy GLB previews are never overwritten; a corrected preview is written beside them.
* Updating the camera engine (COLMAP 3.9 → 4.2) keeps the model files readable by the
  original loader (verified: `images.bin` from 4.2.1 parses with `scene/colmap_loader.py`);
  extra 4.x files (`rigs.bin`, `frames.bin`) are kept beside the classic three files.
* Releases install side by side under `~/.local/share/m4ml-studio/apps/<version>`; projects
  and the runtime are not touched by install/uninstall.

## 8. UI structure (`frontend/src`)

Editor shell (`App.tsx`): `MenuBar.tsx` (파일·편집·보기·작업·창·도움말, accelerators) →
project bar → workflow tabs → `dock.tsx` layout (Project Explorer | stage viewport |
Inspector, bottom panel; resizable `Splitter`s, persisted `Layout` in the app profile's
localStorage, save/restore/reset) → status bar.

* `ProjectExplorer.tsx` — tree of images, cameras, masks, training, checkpoints, model,
  exports (`/api/projects/{id}/assets`); search, problems-only filter; selection drives the
  `Inspector.tsx`. Stage screens render their own inspector content via `InspectorPortal`.
* `BottomPanel.tsx` — 콘텐츠, 작업 관리자 (jobs, cancel/retry), Console (real job logs),
  GPU Monitor (`/api/gpu-monitor`, nvidia-smi).
* `Welcome.tsx` — 새 프로젝트 (folder → `/api/scan-folder` analysis → `/api/projects/from-folder`)
  and 기존 프로젝트 열기; the analysis itself is `studio/project_scan.py` (UI-independent).
* Stages in `stages/`: `ImagesStage` (search/sort/multi-select/registration filter/lightbox/
  remove), `CameraStage` (+ `SparseViewer.tsx`: real sparse points + camera frustums from
  `/sparse-points`), `MaskStage` + `MaskEditor.tsx`, `TrainStage`, `ModelStage` +
  `MeshViewer.tsx` (6 display modes, view presets, ortho, gizmo, grid/axes, lighting,
  stats, PNG screenshot, reload) and `GaussianViewer.tsx` (실시간 렌더: frames from the
  rendering provider, orbit/pan/zoom, training-camera views, render modes, fullscreen,
  screenshot); `ModelStage` switches 실시간 렌더 | 메시.
* `Dialogs.tsx` — help documents served from `docs/` (`/api/help/{name}`, whitelisted),
  about, save-as; `desktop.ts` — QWebChannel bridge with browser fallbacks.

Styles follow the M4ML design system (`M4ML-Studio-Design/design-system`, tokens in
`style.css`, dark default + light theme).

---

## Appendix — original design notes (0.1–0.2, preserved)

### (0.1–0.2) Architecture — locally packaged, reliable, real inference

#### A. Suggested stack (may change via documented ADR)

```text
127.0.0.1 desktop browser tab
  React + TypeScript + Vite + Tailwind + shadcn/ui (or equally maintainable open-source components)
     | HTTP JSON + SSE/WebSocket events
  FastAPI service (loopback only, no cloud service)
     | project & job service, SQLite + job artifacts
     | subprocess manager + cancellation + GPU scheduler
     +-- COLMAP adapter      -> `colmap` genuine CLI
     +-- SAM 3.1 adapter     -> vetted vendor/source + true checkpoint
     +-- Object-Aware runner -> original `train.py`
     +-- Mesh extractor     -> original `render.py` -> PLY
     +-- Mesh conversion    -> optional `trimesh` / `open3d` -> GLB/OBJ
  User home project storage: .local/share/object-aware-studio/projects/<uuid>/
```

`/home/m4ml/Desktop/Object-Aware` is **application/repository root**, not necessarily where huge user datasets should live. Default large artifacts under user data directory; allow configurable project storage. Keep model weights at existing absolute path (configurable; never copy unnecessarily). Web frontend builds to distributable static files and backend serves those files so Node is not needed at runtime. Use Python 3.10-compatible backend packages pinned not to break the source environment.

Prefer installing app/backend into the Object-Aware anchor environment; isolate frontend Node dependencies from Python. Avoid a daemon requiring root; start/stop with one script and desktop shortcut optional. Server on `127.0.0.1` with ephemeral/controlled port; no public binding unless explicitly requested (out of scope). Consider CSRF/origin validation for local mutating endpoints, file picker limitations and safe token/nonce to prevent malicious websites accessing local processes.

#### B. Recommended repository structure

```text
Object-Aware/
├── AGENTS.md, CODEX_PROMPT.md
├── train.py, render.py, arguments/, scene/, gaussian_renderer/, utils/, submodules/  # preserved upstream
├── models/sam3.1/          # local checkpoint, ignored by Git
├── vendor/sam3/            # pinned SAM source or patchset, only if needed
├── studio/
│   ├── api/                # FastAPI routers, schemas, SSE, validation
│   ├── core/               # project model, stage FSM, persistence, recovery, file IO
│   ├── pipelines/          # import, colmap, mask, train, mesh orchestration
│   ├── adapters/           # colmap.py, sam31.py, objectaware.py, mesh.py
│   ├── jobs/               # subprocess runner, GPU allocation, events
│   └── tests/              # deterministic fixtures & process tests
├── frontend/
│   ├── src/features/{projects,import,colmap,masks,training,mesh}/
│   ├── src/components/, src/lib/
│   └── tests/
├── scripts/{setup.sh,start.sh,doctor.sh,smoke.sh}
└── docs/{PRD,ARCHITECTURE,COMPATIBILITY,ACCEPTANCE_TESTS,LOOP_PLAN,STATUS,DECISIONS}.md
```

Avoid making scientific research modules depend on web-framework packages. All `studio/adapters/*` expose typed inputs/outputs and handle upstream errors; no GPU use in HTTP request threads. External commands run in **child processes**, preventing event loop blocking and allowing cancellation. Stage workers use atomic output directory promotion.

#### C. Durable project structure + manifest contract

```text
<project-root>/<project_id>/
├── manifest.json           # schema/version, source checksums, selected scene id, settings
├── logs/{colmap,sam31,train,mesh}.log
├── input/original/         # immutable normalized/canonical photos (do not mutate originals)
├── input/source_map.json   # original -> canonical names, EXIF, hashes, capture order
├── colmap/{database.db,distorted/sparse/*,undistorted/*,model_report.json}
├── scene/
│   ├── images/*.png        # registered, undistorted, canonical stable names
│   ├── mask/*.png          # registered views, same stem as `images`, 0/255
│   └── sparse/0/{cameras.bin,images.bin,points3D.bin,...}
├── masks/{prompts.json,review.json,predictions/*,qa.json}
├── training/{run_id}/{cfg_args,point_cloud,checkpoints,events,...}
└── mesh/{fuse.ply,fuse_post.ply,preview.glb,mesh_report.json}
```

The Colmap undistorter may produce its own `images/` and `sparse/` layout: assemble the final training `scene/` from one coherent camera model and **selected registered images only**, using atomically copied/symlinked safe files and a machine-readable name map. Preserve same-stem rule and required masks. Ensure COLMAP image names, camera intrinsics and physical pixels agree after renaming/undistorting; if renaming requires manipulating COLMAP models, use tested official COLMAP model converters or readers/writers, not brittle regex edits of binary files. `sparse/0/points3D.ply` may be created by source reader. Explicitly check target dataset loader.

Each job record (SQLite with WAL): `job_id`, `project_id`, `stage`, `state`, `attempt`, `created_at`, `started_at`, `ended_at`, `worker_pid`, `device_physical_id`, `exit_code`, `progress_current`, `progress_total`, `message`, `log_path`, `input_fingerprint`, `artifact_manifest`. Stages depend on artifact **fingerprints**: image changes invalidate COLMAP onward; selected sparse component changes invalidate masks onward; editing a mask invalidates training/mesh; training config changes invalidate training/mesh; failed steps preserve prior valid artifacts. Never reuse stale training after a mask change.

#### D. Formal workflow finite-state machine

Allowed top-level stage states: `pending`, `running`, `waiting_for_user`, `review_required`, `completed`, `failed`, `cancelled`, `blocked`. State transitions must be validated in service, transactional, evented, and recoverable; `completed` requires artifacts and automated validators (not child exit code alone). On restart detect orphaned jobs, reconcile PID and outputs, offer resume/retry; never claim an old process is still alive without checking. Only one GPU-intensive SAM/training/render workload at a time per selected device by default.

Stage gates:
- IMPORT completed => valid manifest and >=2 distinct valid images (advise more images for reliable geometry).
- COLMAP completed => consistent camera poses + sparse scene; show registered subset and excluded reasons (warn for low coverage); not success just because matcher exited with 0.
- SAM completed => candidate mask or actionable failure for **every** registered frame; if any failed, move to review and block approval until corrected.
- REVIEW completed => all masks valid/aligned. `skip remaining review` accepts unreviewed valid *candidates*, never missing/empty data; log explicit skip decision.
- TRAIN completed => exit status 0 AND expected output exists, valid point cloud + config/iteration evidence.
- MESH completed => expected mesh exists AND parsed geometry has >0 vertices and >0 triangles; valid viewer preview.

#### E. COLMAP correct classification

Keep `input` original file set immutable. In COLMAP database, inspect image IDs and (verified) matching pairs; mapping registration from selected sparse model requires pose and intrinsics. Per image show booleans `features_extracted`, `has_verified_match`, `registered`, `selected_component` plus primary `reason` and optional camera diagnostics. Define a 'matched' pair as geometrically verified match where data permits (not mere extracted descriptors), and show uncertainty if using only weaker data. Excluded images cannot enter mask/train scene. When N sparse models exist, support component selection; never union incompatible frames.

Workflow: `feature_extractor` -> chosen `matcher` -> `mapper` -> inspect models -> choose model -> `image_undistorter` -> validate image/model agreement -> construct `scene`. Fail UI with details for empty `sparse` or unsupported cameras. Perform bounded subprocess execution with configurable threads/VRAM and logs; implement safe retry without corrupting previous result. Existing `convert.py` gives a baseline implementation reference, not safe direct use for shell-injected filenames.

#### F. SAM image init and cross-view pipeline

- Inspect official SAM 3.1 checkpoint and exact upstream API (`sam3/model_builder.py`, `examples/sam3.1_video_predictor_example.ipynb`, `sam3_base_predictor.py`) before coding. `start_session`, `add_prompt(points, point_labels)`, `propagate_in_video` are documented request concepts; **exact shape / point-coordinate convention must be inferred from actual current code/tests**.
- UI click coordinates in full-resolution image pixels are mapped correctly through zoom/pan, resizing and any SAM image normalization; negative clicks labeled 0, positive 1 after verification. Store coordinate system and transform for reproducibility.
- Choose best first frame by quality/visibility (offer user choice) and obtain **user confirmed** object mask. Use a deterministic traversal based on known capture order or COLMAP camera center/rotation nearest-neighbor graph, with view jumps flagged. Propagate in chunks across ordered registered views, maintaining frame-name ↔ prediction index map and checkpointed progress.
- In review edits, use genuine interactive predictor or object-mask correction, not arbitrary RGB color segmentation. Separate `auto_mask`, `approved_mask`, `manual_edit_mask`, `prompts` so rerun never overwrites approved data. On re-propagation, skip approved masks unless explicit `replace` confirmation. Validity = grayscale binary 0/255, right dimensions, nonempty finite, not whole image for typical object (full image is warn/block only if genuinely invalid).
- Optional reprojection consistency check uses COLMAP correspondences: project sparse tracks into paired registered views, compare object-vs-background classifications where visible, aggregate warnings with overlap confidence, avoid treating occlusion/confidence noise as certainty.

#### G. Training and CUDA device selection

`NVIDIA` check via `nvidia-smi` / NVML if installed and `torch.cuda.is_available()` from *same active Python environment*. On selected `physical_GPU_ID`, set subprocess environment `CUDA_VISIBLE_DEVICES=<id or UUID>` and inside job expect `torch.cuda.current_device()==0` in restricted visible set. Verify CUDA version, device name/VRAM, native GS rasterizer import. No automatic CPU training fallback. Avoid running COLMAP+SAM+training simultaneously on low-VRAM GPU. GPU OOM: fail visibly, preserve logs and offer user-approved lower-resolution preset; don't tamper with scientific losses. Use standard `--iterations` config and `--checkpoint_iterations`/`-m` as verified; check status/events emission. Can add opt-in JSONL progress instrumentation without changing optimization math. Ensure worker environment has validated PWD, subprocess group, clean termination and timeouts for diagnostics.

#### H. Mesh viewer

`render.py -s <scene> -m <training-output> --skip_train --skip_test` (confirm actual flags locally). Locate `.../train/ours_<iter>/fuse.ply` and `_post.ply` after run, copy/link into project output with provenance. Parse via Open3D/trimesh: vertices, triangles, AABB, colors, validity. Generate preview `.glb` for efficient browser loading, original PLY retained. UI: Three.js `OrbitControls`, centered mesh, scale-to-fit, reset camera, axis/grid toggles, smooth/wireframe, vertex-color support. No internet/CDN at runtime. Very large meshes: warn, offer downsampled **preview only** while preserving export original.

#### I. Security, robustness and launch

- Strict per-project path ownership/allowed roots, canonicalize `resolve()`, reject path traversal/symlink escape, hard/soft file size quotas. Do not accept remote URL fetches from browser, shell commands, zip traversal, or arbitrary Python execution through APIs.
- Bind only loopback; CORS/origin restricted; CSRF protection appropriate for localhost. Do not run untrusted pickle checkpoints; only allow user's explicit trusted local checkpoint and communicate pickle risks where torch serialization is used.
- All stages are idempotent with atomic files and checksums. Preserve raw inputs and original output paths. Automatic retries only for transient errors; diagnostic error states otherwise.
- Strong `.gitignore`: models weights, datasets, user projects, generated PLY/GLB, environment secrets, logs, caches, database files.
- Setup doctor must print Linux, GPUs, Python/Torch/CUDA, COLMAP, checkpoint status, disk and license acknowledgement; no misleading 'healthy' if SAM 3.1 test cannot run.
- Use `scripts/setup.sh`, `scripts/start.sh`, `scripts/doctor.sh`; build frontend once. Document pinned versions and offline runtime behavior. No `sudo` except explicitly documented necessary OS packages; never modify a globally shared Conda env without user awareness.

#### J. Implemented layout and verified lifecycle

The small application uses flat cohesive modules: `studio/api.py` (loopback/token/origin API/static UI), `store.py` (SQLite/WAL/FSM gates/artifact audit), `dispatch.py`/`worker.py`/`process.py`/`child.py` (foreground workers, real subprocess logs, ownership/cancel), `importer.py`, `colmap.py`, `sam31.py`, `mesh.py`. Scientific directories stay unchanged. Frontend uses React/TS/Vite and plain semantic CSS; Three.js is lazy-loaded, with no CDN/fonts at runtime. The proposed deeper subdirectory split is deferred until module size warrants it.

GPU locks are keyed by detected physical UUID under the user's runtime/cache directory, shared across project stores. Workers monitor owner server PID+start time; stable worker main-thread scientific children use PR_SET_PDEATHSIG. API request-thread parent-death signals are explicitly avoided after actual failure evidence. Persistent cancel requests cover early startup races. Uvicorn has a10s graceful deadline for open SSE clients.

Artifacts are promoted into state only after validators pass, retained per run, and revalidated after restart. Import hashes/raw snapshots, selected-camera bundle, mask hashes/review provenance, training revision/input fingerprints, finite Gaussian PLY and triangular PLY/GLB validation remain inspectable. Only original generated checkpoints are saved periodically; retries create new runs. Source point initialization requires finite triangulated points; synthetic test camera fixtures are never substituted into production.
