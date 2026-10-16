# Product Requirements — Object-Aware Reconstruction Studio

## 1. Goal, platform, users

Local-first desktop-class experience served on `127.0.0.1` for researchers/creators with **Ubuntu or supported Linux + NVIDIA GPU**. Input is unordered or sequential **multi-view still images of one target object**. Output is a real Object-Aware Loss reconstruction mesh. No cloud signup, no remote inference, no remote upload, no background service required after app closes. GPU training needs compatible CUDA device; fail clearly if unavailable.

**Research implementation identity:** use repository `WooSungHyun03/object-aware-loss`, original paper and `facebookresearch/sam3` with **SAM 3.1** checkpoint in `models/sam3.1/`. Do not silently change algorithms.

## 2. Six-step user journey

| # | Visible step | Initiation | Completion | User-facing outputs |
|---|---|---|---|---|
| 1 | 이미지 불러오기 | Select folder(s) or drag/drop | Valid images imported, normalized with source provenance | count, thumbnail grid, file errors, duplicate summary |
| 2 | COLMAP 재구성 | Automatic after explicit project start | Verified sparse model and registered image set, or actionable failure | matching progress, counts: total / feature detected / pair matched / **registered** / excluded; per-image reason & retry |
| 3 | SAM 3.1 마스크 생성 | Select one **registered** reference view, click object (+) and optional background (-), preview, confirm | One chosen object propagated across selected registered views; every view has candidate or a flagged failure | initial overlay, progress, confidence/QA flags, generated/failed |
| 4 | 마스크 확인·수정 | Automatic review screen | All registered views have valid masks and review has been completed or explicitly skipped | 이전 / 다음 / **남은 검토 모두 건너뛰기**, overlay, click refine, brush/erase, undo/redo, accept, status |
| 5 | Object-Aware 학습 | After mask preflight and explicit start | Original `train.py` finishes with verified output checkpoint/point cloud | model settings, chosen GPU, iterations, losses, ETA when credible, resume/retry/stop |
| 6 | Object Mesh 확인 | Automatic after successful training | Original `render.py` TSDF completes and valid mesh passes sanity check | interactive 3D mesh, orbit/pan/zoom, wireframe, export `.ply` (optional `.obj`/`.glb`) |

Persistent stage indicator: `대기 / 실행 중 / 사용자 작업 필요 / 검토 필요 / 완료 / 실패 / 취소됨`. Previous completed steps remain inspectable. Restart returns to last verifiably completed stage. Do not automatically train with unconfirmed target object.

### 2.1 Image import and data safety
- Support JPG/JPEG/PNG/TIFF commonly readable by Pillow/OpenCV, multiple selection/folders, Unicode/spaces, and EXIF rotation normalization. Reject invalid/unreadable/corrupt files with specific reasons. Do not mutate originals.
- Copy or safely link sources into per-project immutable input snapshot. Canonical unique names avoid collisions (e.g. `000001_<safe-stem>.png`); preserve mapping to original paths, EXIF, hashing, image dimensions, and insertion/capture order in manifest.
- Show total count, dimensions, estimated storage; flag duplicates and near-duplicates, blur/extreme overlap as advisory (do not silently delete).
- Avoid huge browser uploads: use local file selection strategies compatible with sandboxed browser restrictions; backend must only access project-authorized paths.

### 2.2 COLMAP / camera registration
- Use **real COLMAP** feature extraction, matching, mapping, image undistortion. Prefer original repo's `convert.py` semantics but reimplement orchestration safely if necessary (its `os.system()` usage is not appropriate for arbitrary UI file paths).
- Preserve intermediate database/sparse models and logs. Default matching mode based on provenance: `sequential_matcher` for actual ordered captures, `exhaustive_matcher` for modest unordered sets; scalable vocab/spatial strategies only with tested configuration. Never claim that simply invoking matching creates valid poses.
- Enumerate every original image: `미매칭`, `매칭되었으나 카메라 등록 실패`, `다른 재구성 그룹`, `등록 성공`, `잘못된 파일`, with explicit evidence/counters. A *registered* image is in the selected COLMAP sparse model and has verified camera pose and intrinsics. If multiple models are reconstructed, select largest suitable connected model by default; allow explicit selection and display exclusions. Never combine unrelated coordinate systems blindly.
- `scene/images`, `scene/sparse/0`, undistorted pinhole intrinsics must be mutually consistent; the accepted image list comes from final sparse model, not just database feature pairs. Train/mask only this set.
- If sparse reconstruction is inadequate, display diagnostics and safe retry choices (matching option, camera model) instead of advancing. Provide stage-specific cancel/retry.

### 2.3 SAM 3.1 initiation and propagation
- Show thumbnails **only for registered images**. User clicks positive points on target object; optional right-click/Alt-click negative points on background. Display exact preview and support point edit/reset. Confirm first mask before propagation.
- Load genuine locally present **SAM 3.1** weights and official model code adapted, with validated architecture/version; never substitute another model or fake a SAM output.
- Build a deterministic ordered traversal through registered images (capture order where trustworthy; otherwise camera-pose adjacency + viewing-direction continuity), with reversible mapping to original names. Propagate to every registered view and save confidence/uncertainty signals and failure reasons.
- Any view discontinuity, empty mask, implausible area jump or occlusion must be flagged for review. The system may request additional point corrections on other frames **only during optional human review**. A single prompted frame is the starting workflow, NOT a claim of guaranteed cross-view propagation for arbitrary still photographs.
- A user correction should update that view and offer constrained forward/backward re-propagation to nearby unchecked frames, without silently overwriting reviewed/approved masks. Save positive/negative prompt history and manually edited masks separately from auto predictions.
- No automatic retargeting to a visually similar object: keep stable object identity, support single object for MVP.

### 2.4 Mask validation and review
- Full-size zoom/pan mask editor. Overlay opacity slider, binary/outline/original comparison, thumbnails and per-frame statuses. Low-latency visual updates; async GPU inference with cancellation and progress, no UI freezes.
- Tools: positive/negative clicks, point removal, local brush/eraser/polygon optional, undo/redo, reset to generated, accept/save. Mouse and keyboard shortcuts with accessible hints.
- Actions: **이전**, **다음**, **승인하고 다음**, **남은 검토 모두 건너뛰기**. Last action requires confirmation; it skips interactive review of remaining valid auto masks, marking them `검토 생략(자동 마스크)` not `수동 승인`. Missing, corrupted, entirely empty or dimension-mismatched masks still **block training** until fixed.
- Persist individual masks with one original training-image-aligned **uint8 binary PNG** per registered image; `255=object`, `0=background`, filename stem must match training image stem, use nearest-neighbor for all transforms, validate alpha/mask provenance. Mask saved under `<scene>/mask/<same-stem>.png`. Do not distort masks or use hard-coded alpha semantics.
- Optional QA signals: mask coverage, connected components, abrupt changes along ordered views, sparse tiepoint reprojection agreement. Warnings are advisory except absent/invalid masks.

### 2.5 Object-Aware training
- After review/preflight, show dataset size, mask statistics, GPU model and free VRAM, image resolution, training preset, 30K iterations default, disk estimate and research license warning. Explicit `학습 시작` button.
- Invoke genuine `train.py -s <scene> -m <output>` with repo-standard configuration; preserve loss functions, pruning schedule and default hyperparameters unless user intentionally changes supported options. Study `arguments/__init__.py` before exposing settings.
- Use user-selected NVIDIA GPU physically and verify in worker (`CUDA_VISIBLE_DEVICES` + inside-worker CUDA indexing). Show CUDA device details; resource scheduling must serialize conflicting GPU jobs.
- Stream real iteration, loss, number of Gaussians, log messages, and meaningful errors (e.g., CUDA OOM); cancellation terminates child group safely and retains usable checkpoints. Resume only when original code/checkpoints permit and it has been tested.
- Disk/memory checks, sensible resolution presets and up-front warning; do not automatically change scientific hyperparameters to mask failures. Ensure training mask resolution matches training image after resizing.

### 2.6 Mesh and output
- Invoke genuine source `render.py` TSDF pipeline. Bounded `fuse.ply` / `fuse_post.ply` or unbounded mode only when explicitly selected and supported by scene. Never treat Gaussian point cloud as a triangle mesh.
- Validate nonzero vertices/faces, finite coordinates and optional color; present errors if invalid. Display real triangle mesh in 3D viewport (suggest Three.js / `@react-three/fiber`, Drei), camera orbit/pan/zoom, axes, wireframe, fit model, screenshot where feasible.
- Preserve native PLY; `.obj`/`.glb` conversions via trimesh/Open3D only after data-integrity validation, with transparent notice if material/vertex colors cannot be preserved. Download/export user-selected path; retain reproducibility manifest and logs.

## 3. Project-level experience
- Project homepage: `새 프로젝트`, `최근 작업`, `이어하기`, `환경 진단`.
- Jobs and state survive backend restart; no false completed flags. Each project has an explicit `manifest.json`, timestamps, source SHAs/settings, stage outputs and errors.
- Async progress events via WebSocket or SSE; backed by durable DB/event log so UI reconnect is safe.
- Natural Korean, excellent empty/error/retry screens, screen-reader labels, readable contrast; focus on users unfamiliar with COLMAP, SfM, alpha masks, TSDF.
- Desktop widths primary, support compact laptop screens. Avoid unnecessary account, marketing, cloud features.

## 4. Out of scope / guardrails
- Do not invent camera poses for images that fail COLMAP; do not train them.
- No cloud segmentation/training, commercial license assurance, photogrammetry from one image, multi-object editing, unrelated reconstruction engines, or promised arbitrary-view SAM 3.1 invariance.
- No single-shot fake end-to-end demo that bypasses genuine software; always distinguish unit mocks, fixture tests and physical GPU tests.
