# Architecture decision and compatibility log

Use this as an append-only ADR. Every deviation from requirements or recommended architecture must specify evidence, scientific implications, trade-offs, test outcome and date. Do not make silent substitutions.

## ADR-000: Requirements baseline (2026-10-15)

- **Decision:** Local Ubuntu/Linux NVIDIA-GPU app with React/Vite, local FastAPI, persistent SQLite, subprocess-based scientific adapters, genuine COLMAP, SAM 3.1, existing Object-Aware training/mesh extraction.
- **Reason:** local-only UX, independent robust long-running processes, restart/recovery and inspectable model provenance.
- **Hard constraint:** Object-Aware environment is anchor; SAM 3.1 code adapted where technically feasible; no silent dependency upgrade that breaks native GS, no alternative mask/GS model.
- **Known uncertainty:** actual hardware, checkpoint identity, upstream runtime/API compatibility must be tested on user workstation.
- **Status:** PROPOSED pending empirical verification.

## ADR-001: Mask propagation on general still images (2026-10-15)

- **Decision:** use genuine SAM 3.1 propagation on capture-ordered / camera-adjacent registered frames; mark discontinuities and review all predictions or explicitly skip valid candidates.
- **Reason:** video-style tracking does not guarantee accurate masks across wide-baseline unordered still photos.
- **Result:** requires correctness checks and human revision; no unsupported accuracy claims.
- **Status:** DESIGN.

## ADR-002: COLMAP success definition (2026-10-15)

- **Decision:** matched pairs and registered cameras are independent properties; only one selected coordinate-consistent registered component may be used for training.
- **Reason:** successful feature matching does not provide calibrated poses to GS.
- **Status:** DESIGN.

## ADR template (append for material changes)

### ADR-NNN: Title (YYYY-MM-DD)
- Context / observations:
- Options considered:
- Decision:
- Impact on algorithm/API/UI:
- Evidence/tests:
- Reversibility and follow-up:

### ADR-003: Preserve existing workspace and use a private anchor runtime (2026-10-15)
- Observed root contained instructions and a 3.50GB checkpoint but no Git/source/application. Existing Conda environments do not supply the requested Python3.10 anchor.
- Integrated original source into root via Git fetch/checkout without overwriting files. Pinned official SAM as a Git submodule for audit and reproducible compatibility patches.
- Use `.runtime/` inside this project with Python3.10, Torch2.5.1/cu118 and torchvision0.20.1. No system/global environment changes, no second GPU backend, no algorithm changes. Use installed CUDA11.8/GCC11 explicitly rather than PATH CUDA12/GCC13.
- COLMAP installed binary is CPU-only 3.9.1. Use its genuine CPU feature/matching path; GPU remains required for SAM/Object-Aware. This does not alter reconstruction algorithms.
- Tests: doctor unit tests 3/3 PASS; pre-install Torch probes FAIL, recorded honestly. Native/inference gates remain NOT RUN.

### ADR-004: Repair incomplete toolkit path and pin SAM compatibility patches (2026-10-15)
- Actual CUDA11.8 path was only an nvcc symlink, causing `cicc: not found`. Private `.runtime` now includes CUDA11.8 compiler/headers/libcudart from exact cached NVIDIA packages. Setup uses that location and GCC11. Existing system toolkit remains unchanged.
- Official SAM3.1 source has reproducible session-init and first-click output-cache API defects. Preserve upstream SHA and maintain small `patches/sam3/*.patch` applied idempotently by `scripts/apply_sam_patches.py`; retain submodule working diff for inspection. No site-packages edits or substituted model.
- SAM installed with `--no-deps` because upstream NumPy>=1.26 metadata conflicts with original NumPy1.24.4 pin. Import, full checkpoint model shape/key matching PASS in anchor runtime; actual inference still gating. No compatibility declaration until full smoke completes.
- Tests/evidence: `evidence/build-native-fixed-toolkit.log`, `evidence/sam31-smoke-first.log`, `evidence/sam31-smoke-session-fix.log`, `evidence/unit-cycle2.log`.

### ADR-005: Explicit start for point-only SAM3.1 propagation (2026-10-15)
- Empirical upstream API: point-only prompts update tracker state while `_get_processing_order` default inspects detector outputs. Calling with no start raises `No prompts are received` even after valid point inference.
- Adapter sends the known prompted `start_frame_index` explicitly using the official request schema, with both-direction propagation. No synthetic detector outputs, no model replacement, no inference math change.
- Actual GPU evidence: positive/negative and all3 frames PASS in `evidence/sam31-smoke-explicit-start.log` and `result.json`. Native renderer also passes in same runtime. Full original training remains a separate gate.

### ADR-006: Scientific workstation UI and application lifecycle (2026-10-15)
- Use prescribed FastAPI/SQLite + React/Vite + Three.js. UI direction follows reconstruction work: persistent left six-step workflow, central photographic canvas, adjacent prompt/review inspector, bottom real logs. Calm blue-gray surfaces (#eaf0f4/#fff), ink#162a39, petrol action#195f78, explicit warning/error states. System Noto CJK/Ubuntu sans fonts; no network font dependency. Marketing/neumorphism recommendations from first skill search rejected as unsuitable; narrower engineering search informed functional light high-contrast layout.
- Node is build-time only. Static UI served by loopback API; GPU computations always subprocesses. OS file locks serialize per physical GPU; workers and scientific processes receive Linux parent-death signal. No source algorithm changes.
- API uploads intentionally expose no arbitrary local directory-reading endpoint. Folder selection uses browser file chooser with per-file immutable copies. Duplicate content remains reported/snapshotted but does not enter SfM. Existing finalized projects retain immutable inputs; additional datasets use a new project.
- GLB is optional viewer/export conversion of validated real triangular PLY, loaded back and face-count checked; original PLY retained. Viewer lazy loaded to keep initial shell small.
- Resume of interrupted training is not exposed until original checkpoint restart has been verified. Retry produces a new run directory and preserves previous evidence.
- Evidence: frontend build,17 focused tests, actual source/SAM/train/mesh logs. Full UI E2E still in progress.

### ADR-007: Worker process ownership cannot follow an API request thread (2026-10-15)
- Actual browser integration proved Linux parent-death signals are unsuitable for API thread-pool-spawned workers: request thread expiry cancelled real COLMAP while server remained healthy.
- Workers monitor owning server process PID AND /proc start time (PID reuse safe), inherited across automatic mesh dispatch. Stable worker main-thread scientific children retain PR_SET_PDEATHSIG. Stop requests persist before signalling so cancellation during startup is distinguished from failure. Shutdown/restart keeps outputs and reconciles interrupted stages.
- Real retry completed COLMAP, SAM preview/propagation and default30K train now running. No fake success or scientific substitutions. Diagnostic/source tests remain separate from actual GPU execution.

### ADR-008: Anchor NumPy compatibility metadata and import minimum (2026-10-15)
- Original SAM metadata requires NumPy>=1.26 but real point/negative/propagation, original native backward and train pass using anchor1.24.4. Retain exact NumPy pin and patch only SAM lower-bound metadata; `pip check` passes. Scope of evidence is exercised inference paths, not every upstream SAM training/text feature.
- Architecture specifies at least2 distinct imports. Corrected initial conservative3-view implementation to2 for import/coherent scene; UI continues recommending3+ photos. Selected sparse components are read from actual reports, never assumed to be ID0; real sample produced2 and16-camera components.

### ADR-009: Release implementation layout and cold-install evidence (2026-10-15)
- Use compact flat modules rather than the initially proposed many nested packages. Actual API/state/import/COLMAP/SAM/train/mesh responsibilities remain separated; Black/Prettier formatting, typed frontend props and focused tests preserve maintainability. Use plain CSS instead of Tailwind/shadcn to avoid unnecessary build/runtime dependencies for a custom canvas workstation.
- Actual full30K browser run and default1024 TSDF pass; actual PLY/GLB hashes, geometry and exports verified. Recreated private Python environment, Node modules and native builds from scratch on inspected host; old runtime preserved only as rollback data. Existing global environments untouched.
- Registered views share a padded SAM canvas with reversible per-camera crop; local radius2 propagation updates only unchecked neighboring frames. Missing masks retain the full photograph for correction. Scientific source/math unchanged.
- Original checkpoint saves every5000/end are artifact I/O only; loss/pruning defaults unchanged. No GUI resume assertion beyond tested trusted original CLI100→110.
- Physical GPU UUID locks shared across stores; real queue, GPU cancellation, allocator OOM and bounded SSE shutdown verified. Default normal storage contains a copied and re-audited genuine completed project, not hardcoded application demo data.
- Evidence and limits: `docs/STATUS.md`, `evidence/e2e-release.json`, cold/fault logs. Other GPUs and reconstruction quality beyond this dataset remain uncertified; original license restrictions remain.

### ADR-010: Recover from verified artifacts rather than replay completed phases (2026-10-16)
- Session interruption left a complete physical30K pipeline but uncommitted application source and an inconsistent E2E acceptance row. Recover from actual sources, hashes, SQLite state and files; preserve prior evidence and do not manufacture another full-run claim.
- Current smoke27+2/build/native CUDA, genuine SAM3.1 click/three-frame GPU smoke, full saved-project audit and latest-server browser restart all pass. Correct the stale acceptance row with explicit original-run versus re-audit dates. Keep official SAM gitlink plus tracked compatibility patches rather than an unpublished submodule commit.
- Scope and algorithm unchanged. Original research source remains byte-identical; actual partial geometry and host-only verification limits remain explicit. Preserve a local release commit; do not push.

### ADR-011: M4ML product scope and color semantics (2026-10-16)
- New product acceptance supersedes earlier completion scope. Preserve historical physical evidence while tracking all new unverified gates separately.
- Actual original TSDF RGB8 PLY and promoted PLY/GLB contain color. Correct Trimesh4.3.2 sRGB-byte export to glTF linear float COLOR_0 with numeric roundtrip; use unlit vertex-color default for accurate color, separate nonmetallic lit shape mode. Do not edit scientific TSDF/loss code or invent colors.
- Retain actual supplied logo, neutral dense desktop workstation layout; generic marketing/neumorphism search output rejected. New project imports use browser-authorized staged files, no unrestricted server-local path read API. Original files remain immutable.

### ADR-012: Durable automatic prompts and validated imported scenes (2026-10-16)
- Prompt changes persist exact positive/negative sets with frame/session/revision. A short180ms debounce coalesces rapid events. One real GPU worker/project and shared physical-GPU lock remain. Old workers may finish but cannot publish stale masks; failure preserves prior genuine preview and approved masks. Empty positive set clears preview rather than fabricating inference. Point undo/redo and brush pixel history are separate.
- B/C imports operate on browser-authorized copied uploads. Official COLMAP model_converter validates bin/txt, image_undistorter executes only when camera distortion exists, selected poses are preserved and names canonicalized. No SfM or camera invention. Distorted C masks support tested OpenCV radial/pinhole mapping with nearest sampling; unsupported mappings block and request pre-undistorted data. Missing/ambiguous/nonbinary masks block C; explicit channel/foreground/normalization and B fallback are available.
- glTF COLOR_0 linear encoding verified against [Khronos specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html). Trimesh4.3.2 geometry loader warns on read-only float color arrays; our independent accessor parser verifies exact color preservation instead of trusting that loader's visual defaults. Three.js consumes native glTF float COLOR_0.
- New mesh retries copy model/config into a new rendering workspace so unchanged upstream render.py cannot overwrite an earlier extraction. Existing source files/checkpoints and geometry are retained.

### ADR-013: Portable per-user distribution and tested limits (2026-10-16)
- Choose a source+offline-UI research tarball with SHA256 manifest, per-user install/desktop launcher and separate XDG runtime/cache. Driver/COLMAP/GCC/Conda are explicit prerequisites; no host sudo, Docker installation or driver change. Bundle excludes weights/user data and preserves original notices. Archive doctor verifies actual original source hashes rather than treating absent Git as a failed installation.
- Actual clean Ubuntu24.04 non-root UID/HOME and read-only app verified in Docker with the same physical GPU; actual native/SAM/train/TSDF pass. CPU-only viewer install is explicit and never substitutes inference. Headless desktop-entry argv/registration/duplicate/shutdown were exercised; GNOME shell/menu pixel interaction and other GPUs remain untested.
- Keep project format1 backward compatible (new fields optional), snapshot existing SQLite before first0.2 opening, preserve legacy XDG data in place, separate versioned app directories. Uninstall archives only owned app integration/artifacts, keeps projects/runtime/checkpoints and uses UUID+atomic rename with narrow permission repair for read-only app root.
- A resource-bound SAM worker may use explicit STUDIO_SAM_MEMORY_FRACTION for reproducible allocator OOM/VRAM limits; default unchanged. Error recovery preserves previous genuine result and pending point input; cancellation/shutdown stop pending inference scheduling.
- Exporter3 uses explicit unlit white-base material and linear vertex colors in GLB; default viewer shows photographic vertex colors without lighting distortion. Shape mode separately uses nonmetallic lighting, wire mode shows topology. Original PLY/legacy GLB remain unchanged; corrected previews are new artifacts.

### ADR-014: Capability providers and persistent point selection (0.3 recovery, 2026-10-16)
- Retain the implemented camera/segmentation/training/mesh/export interfaces (`studio/providers/`) and settings schema2. The UI uses user tasks; engine names, versions and paths are in Settings > 고급 정보. Only existing scientifically verified providers ship; the registry is not permission to substitute research methods.
- Reuse official pinned CUDA COLMAP4.2.1 binary; no redundant rebuild. Private CUDA12.6 runtime is an ELF subprocess, separate from the single Python3.10/Torch2.5.1/cu118 scientific runtime. Original training/render/native sources remain unchanged. RPATH is relative, headless SIFT uses CUDA, mapper/undistorter remain CPU. System GL/X11/glibc/driver requirements are explicitly retained.
- Keep the actual SAM3.1 model and one decoded photo embedding/session on the selected GPU. Serial latest-wins inputs avoid repeated weight loading; release model/physical GPU lock before long GPU jobs, idle timeout and owner-death cleanup bound lifetime. Warm engine inference time is distinct from browser roundtrip including debounce/polling/decoding.
- Existing 0.3 API evidence includes actual2500→6000 checkpoint resume and absolute progress. Checkpoints belong to the same trusted local run and are fingerprint-gated. No untrusted checkpoint upload/alternative trainer.

### ADR-015: Internal research package and release safety (2026-10-16)
- Keep tarball + per-user versioned installation + separate XDG runtime/project storage. Correct stale0.2 uninstall/version/backup constants for0.3. Never overwrite a different same-version install; archive owned application directory on removal while preserving projects/runtime/checkpoints. SQLite snapshots are once per release; older backups retained.
- Bundle existing GPU COLMAP without rebuilding, include actual47-library/static-dependency notices and hash inventory. Public redistribution remains BLOCKED by unresolved corresponding-source/relinking/license-compatibility review, with original noncommercial research restrictions intact. Build requires explicit --internal-research; manifest/NOTICE record no public approval. No weights or user data; no upload/push.
- Browser test must wait for the decoded physical image before deriving click coordinates, then verify exact session/revision and physical pixels. Initial1×1 placeholder is not an inference canvas. Noninteractive HUD labels pass events through, while actual zoom/tool buttons remain interactive. Test failures exit nonzero; empty/invalid masks continue to block skip/train.
- Preserve the supplied53MB design-reference/mockup package and ImageMagick inspection dump locally without adding generated synthetic photos/screenshots/vendor-render bundles to product Git or release. Actual product React/CSS, original Logo and derived app icons are tracked. Scientific artifacts and evidence remain local/ignored.
- Freeze150 GPU Python package versions from the actual fresh0.3 Ubuntu install via `requirements-runtime-constraints.txt`; setup applies it to pip resolution. This is a transitive version constraint, not a claim of signed/hash-locked wheel supply. Viewer-only keeps a separate minimal CPU dependency set.

### ADR-016: Verify current UI failures without bypassing research gates (2026-10-16)
- Actual browser traces distinguished stale automation from product defects: wait for decoded physical pixels, preserve pointer geometry with preventScroll focus, pass noninteractive HUD events through. Repropagation waits for actual running→completed transitions, test failures/console errors are both JSON FAIL and nonzero. Resumption does not repeat image import/SfM when already valid.
- Keep real temporal failures visible.20-view target selection lost12 candidates across occlusion/viewpoint changes; skip remained blocked. Actual per-frame point inference and saved correction exercised recovery. A separate complete16-view raw-photo UI pipeline passed without console errors.100/256 and2000/512 runs are explicitly smoke settings, not changed scientific defaults or quality benchmarks.
- Known-invalid candidates have no PNG, so do not request nonexistent resources. Keep the photograph/correction tools. Wait for actual mask decoding before saving; preserve manual provenance when confirming an already edited frame. Focused real-browser recovery verifies file hash and status.
- Persistent SAM initial-load OOM was physically reproduced under an explicit per-process allocator quota. Parse only the current launch's bounded log range for an actionable Korean memory message; preserve prior preview and points; offer same-input retry. Release a dead cached process's flock before its replacement. Actual OOM/UI retry and52 CPU/contract regressions validate affected paths. No model/loss change.
