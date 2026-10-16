# Architecture — locally packaged, reliable, real inference

## A. Suggested stack (may change via documented ADR)

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

## B. Recommended repository structure

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

## C. Durable project structure + manifest contract

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

## D. Formal workflow finite-state machine

Allowed top-level stage states: `pending`, `running`, `waiting_for_user`, `review_required`, `completed`, `failed`, `cancelled`, `blocked`. State transitions must be validated in service, transactional, evented, and recoverable; `completed` requires artifacts and automated validators (not child exit code alone). On restart detect orphaned jobs, reconcile PID and outputs, offer resume/retry; never claim an old process is still alive without checking. Only one GPU-intensive SAM/training/render workload at a time per selected device by default.

Stage gates:
- IMPORT completed => valid manifest and >=2 distinct valid images (advise more images for reliable geometry).
- COLMAP completed => consistent camera poses + sparse scene; show registered subset and excluded reasons (warn for low coverage); not success just because matcher exited with 0.
- SAM completed => candidate mask or actionable failure for **every** registered frame; if any failed, move to review and block approval until corrected.
- REVIEW completed => all masks valid/aligned. `skip remaining review` accepts unreviewed valid *candidates*, never missing/empty data; log explicit skip decision.
- TRAIN completed => exit status 0 AND expected output exists, valid point cloud + config/iteration evidence.
- MESH completed => expected mesh exists AND parsed geometry has >0 vertices and >0 triangles; valid viewer preview.

## E. COLMAP correct classification

Keep `input` original file set immutable. In COLMAP database, inspect image IDs and (verified) matching pairs; mapping registration from selected sparse model requires pose and intrinsics. Per image show booleans `features_extracted`, `has_verified_match`, `registered`, `selected_component` plus primary `reason` and optional camera diagnostics. Define a 'matched' pair as geometrically verified match where data permits (not mere extracted descriptors), and show uncertainty if using only weaker data. Excluded images cannot enter mask/train scene. When N sparse models exist, support component selection; never union incompatible frames.

Workflow: `feature_extractor` -> chosen `matcher` -> `mapper` -> inspect models -> choose model -> `image_undistorter` -> validate image/model agreement -> construct `scene`. Fail UI with details for empty `sparse` or unsupported cameras. Perform bounded subprocess execution with configurable threads/VRAM and logs; implement safe retry without corrupting previous result. Existing `convert.py` gives a baseline implementation reference, not safe direct use for shell-injected filenames.

## F. SAM image init and cross-view pipeline

- Inspect official SAM 3.1 checkpoint and exact upstream API (`sam3/model_builder.py`, `examples/sam3.1_video_predictor_example.ipynb`, `sam3_base_predictor.py`) before coding. `start_session`, `add_prompt(points, point_labels)`, `propagate_in_video` are documented request concepts; **exact shape / point-coordinate convention must be inferred from actual current code/tests**.
- UI click coordinates in full-resolution image pixels are mapped correctly through zoom/pan, resizing and any SAM image normalization; negative clicks labeled 0, positive 1 after verification. Store coordinate system and transform for reproducibility.
- Choose best first frame by quality/visibility (offer user choice) and obtain **user confirmed** object mask. Use a deterministic traversal based on known capture order or COLMAP camera center/rotation nearest-neighbor graph, with view jumps flagged. Propagate in chunks across ordered registered views, maintaining frame-name ↔ prediction index map and checkpointed progress.
- In review edits, use genuine interactive predictor or object-mask correction, not arbitrary RGB color segmentation. Separate `auto_mask`, `approved_mask`, `manual_edit_mask`, `prompts` so rerun never overwrites approved data. On re-propagation, skip approved masks unless explicit `replace` confirmation. Validity = grayscale binary 0/255, right dimensions, nonempty finite, not whole image for typical object (full image is warn/block only if genuinely invalid).
- Optional reprojection consistency check uses COLMAP correspondences: project sparse tracks into paired registered views, compare object-vs-background classifications where visible, aggregate warnings with overlap confidence, avoid treating occlusion/confidence noise as certainty.

## G. Training and CUDA device selection

`NVIDIA` check via `nvidia-smi` / NVML if installed and `torch.cuda.is_available()` from *same active Python environment*. On selected `physical_GPU_ID`, set subprocess environment `CUDA_VISIBLE_DEVICES=<id or UUID>` and inside job expect `torch.cuda.current_device()==0` in restricted visible set. Verify CUDA version, device name/VRAM, native GS rasterizer import. No automatic CPU training fallback. Avoid running COLMAP+SAM+training simultaneously on low-VRAM GPU. GPU OOM: fail visibly, preserve logs and offer user-approved lower-resolution preset; don't tamper with scientific losses. Use standard `--iterations` config and `--checkpoint_iterations`/`-m` as verified; check status/events emission. Can add opt-in JSONL progress instrumentation without changing optimization math. Ensure worker environment has validated PWD, subprocess group, clean termination and timeouts for diagnostics.

## H. Mesh viewer

`render.py -s <scene> -m <training-output> --skip_train --skip_test` (confirm actual flags locally). Locate `.../train/ours_<iter>/fuse.ply` and `_post.ply` after run, copy/link into project output with provenance. Parse via Open3D/trimesh: vertices, triangles, AABB, colors, validity. Generate preview `.glb` for efficient browser loading, original PLY retained. UI: Three.js `OrbitControls`, centered mesh, scale-to-fit, reset camera, axis/grid toggles, smooth/wireframe, vertex-color support. No internet/CDN at runtime. Very large meshes: warn, offer downsampled **preview only** while preserving export original.

## I. Security, robustness and launch

- Strict per-project path ownership/allowed roots, canonicalize `resolve()`, reject path traversal/symlink escape, hard/soft file size quotas. Do not accept remote URL fetches from browser, shell commands, zip traversal, or arbitrary Python execution through APIs.
- Bind only loopback; CORS/origin restricted; CSRF protection appropriate for localhost. Do not run untrusted pickle checkpoints; only allow user's explicit trusted local checkpoint and communicate pickle risks where torch serialization is used.
- All stages are idempotent with atomic files and checksums. Preserve raw inputs and original output paths. Automatic retries only for transient errors; diagnostic error states otherwise.
- Strong `.gitignore`: models weights, datasets, user projects, generated PLY/GLB, environment secrets, logs, caches, database files.
- Setup doctor must print Linux, GPUs, Python/Torch/CUDA, COLMAP, checkpoint status, disk and license acknowledgement; no misleading 'healthy' if SAM 3.1 test cannot run.
- Use `scripts/setup.sh`, `scripts/start.sh`, `scripts/doctor.sh`; build frontend once. Document pinned versions and offline runtime behavior. No `sudo` except explicitly documented necessary OS packages; never modify a globally shared Conda env without user awareness.

## J. Implemented layout and verified lifecycle

The small application uses flat cohesive modules: `studio/api.py` (loopback/token/origin API/static UI), `store.py` (SQLite/WAL/FSM gates/artifact audit), `dispatch.py`/`worker.py`/`process.py`/`child.py` (foreground workers, real subprocess logs, ownership/cancel), `importer.py`, `colmap.py`, `sam31.py`, `mesh.py`. Scientific directories stay unchanged. Frontend uses React/TS/Vite and plain semantic CSS; Three.js is lazy-loaded, with no CDN/fonts at runtime. The proposed deeper subdirectory split is deferred until module size warrants it.

GPU locks are keyed by detected physical UUID under the user's runtime/cache directory, shared across project stores. Workers monitor owner server PID+start time; stable worker main-thread scientific children use PR_SET_PDEATHSIG. API request-thread parent-death signals are explicitly avoided after actual failure evidence. Persistent cancel requests cover early startup races. Uvicorn has a10s graceful deadline for open SSE clients.

Artifacts are promoted into state only after validators pass, retained per run, and revalidated after restart. Import hashes/raw snapshots, selected-camera bundle, mask hashes/review provenance, training revision/input fingerprints, finite Gaussian PLY and triangular PLY/GLB validation remain inspectable. Only original generated checkpoints are saved periodically; retries create new runs. Source point initialization requires finite triangulated points; synthetic test camera fixtures are never substituted into production.
