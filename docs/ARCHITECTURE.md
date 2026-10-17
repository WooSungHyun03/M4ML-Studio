# Architecture — M4ML Studio

> Current, implemented architecture.

## 1. Overview

```text
 Desktop shell  studio/desktop (PySide6 + QtWebEngine; launched by scripts/launch.py)
   │  native window/dialogs/downloads via QWebChannel; spawns the API on a free loopback
   │  port with a per-launch token (injected into that exact origin only); stops it on close
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

Styles follow the M4ML design tokens (in
`style.css`, dark default + light theme).
