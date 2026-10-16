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
