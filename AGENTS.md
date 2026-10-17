# AGENTS.md — Object-Aware Local Reconstruction Studio

> This file is the root instruction file for an autonomous Codex implementation loop. Read it first, then read `CODEX_PROMPT.md`, every file under `docs/`, and inspect the **actual local code and hardware** before making decisions. All user-facing UI copy must be natural Korean; code/docs may use English technical terminology.

## Mission and non-negotiables

Build a **real, usable Ubuntu/Linux local NVIDIA-GPU application** covering: multi-view image import → COLMAP SfM and registration audit → SAM **3.1** one-frame positive/negative click initiation with propagation to registered views → live human mask review/correction (previous/next/skip remaining review) → original Object-Aware Loss training → original 2DGS/TSDF object mesh extraction → embedded interactive mesh viewer/export.

Default to unattended operation EXCEPT initial mask prompts, optional interactive mask review/correction, and explicit approval to train. Display the current stage, progress, failures, actions, and files persistently. No fake/placeholder inference, success statuses, training, mesh, or progress.

### Source of truth / precedence
1. User request and this AGENTS.md.
2. `docs/PRD.md` and `docs/ACCEPTANCE_TESTS.md` (observable behaviors).
3. `docs/ARCHITECTURE.md` (proposed implementation; revise with ADR if empirical evidence requires).
4. `docs/COMPATIBILITY.md` (verified repository facts vs. machine-dependent unknowns).
5. `docs/LOOP_PLAN.md`, `docs/STATUS.md`, `docs/DECISIONS.md` (execution and audit).
6. Original upstream Python code and its licenses, inspected *in the local checkout*; do not rewrite scientific methods.

### Absolute paths and repositories
- Target workspace: `<project-root>`
- Original training source: `https://github.com/WooSungHyun03/object-aware-loss.git`
- Original publication: `https://www.mdpi.com/2227-7390/14/17/3221`
- Official SAM implementation: `https://github.com/facebookresearch/sam3`
- Existing checkpoint directory: `<project-root>/models/sam3.1`
- Never presume a checkpoint filename, hash, exact architecture, or full compatibility without inspection.

## Scientific integrity
- Preserve and invoke original Object-Aware `train.py`, `render.py`, `arguments/`, `scene/`, `gaussian_renderer/` and compiled extensions. Maintain masked L1, Alpha Polarization, ObjectMark Polarization, ObjectMark pruning and inherited 2DGS geometric losses. Do not silently switch to baseline 2DGS, other GS methods, or another mask model.
- Original Object-Aware `environment.yml` (Python 3.10 / Torch 2.5.1 / CUDA 11.8) is the **compatibility anchor**. Prefer a **single GPU Python runtime** with adaptation of SAM 3.1 in a locally maintained vendor/compatibility layer, not upgrades that break Object-Aware. The upstream SAM 3.1 documentation asks for Python >=3.12 / Torch >=2.7 / CUDA >=12.6. This is a **hard investigation/test gate**: do not claim compatibility until checkpoint load + positive/negative point inference + propagation pass on hardware. Do not quietly substitute SAM 3.0 or a second environment. If impossible, record reproducible evidence and an honest blocker; propose options without implementing a divergent backend behind the user's back.
- Read and retain upstream license texts and notices. Original GS license restricts noncommercial research/evaluation usage; do not imply unrestricted commercial distribution. Review SAM checkpoint terms separately.
- COLMAP pair matching ≠ camera pose registration. Train and propagate only on images registered in a selected **consistent sparse reconstruction component**, and use **undistorted** COLMAP images/camera parameters. Show feature/match/registration diagnostics independently.
- SAM video propagation assumes a suitable ordered frame sequence; unordered, widely separated multi-view viewpoints can fail. Select meaningful view order; preserve original camera-to-frame mapping, identify discontinuities, and permit review/re-prompt corrections. Never claim mathematically guaranteed multi-view mask consistency from temporal propagation alone.

## Implementation and process rules
- Start by inspecting `pwd`, tree, git status/remote, submodules, licenses, detected GPU(s), drivers, CUDA/PyTorch builds, disk, COLMAP, checkpoint file metadata, and source APIs. Do not delete data, overwrite user changes, modify system/global environments, or use `sudo` casually.
- If root is empty, clone source carefully; if root already contains work, inspect and preserve it. Avoid nesting accidentally. `git pull --ff-only` only if clean and appropriate. Make an isolated working branch when possible. No force push, destructive reset, secrets/checkpoints/datasets committed, or automatic push/merge without authorization.
- Prefer architecture: Python FastAPI **loopback-only** backend + persistent SQLite job state + foreground/subprocess CUDA worker + React/TypeScript/Vite local frontend + Three.js mesh viewer. The build should ship static UI; no external web service required during ordinary use. You may replace a choice when clearly justified in `docs/DECISIONS.md` without violating the requirements.
- **No shell interpolation** of user filenames/paths. Use argument arrays to launch processes, bounded resource use, path validation, atomic writes, content hashes, idempotent stage execution, and cancellation/recovery. Handle Unicode, spaces, EXIF orientation, duplicates, multiple camera models, file permissions, and sparse failures.
- Document the **real** install/run path (ideally `./scripts/setup.sh` and `./scripts/start.sh`) and target non-expert users: Korean stage names, clear error messages, sensible defaults, responsive UI, keyboard/mouse workflows and progress display.
- Build working functionality rather than high-fidelity visual mockups. Tests must exercise real adapters with fixture data when possible. Mocked tests are NOT proof of GPU E2E execution.

## Loop engineering contract
1. Read `docs/STATUS.md`; identify first incomplete gate in `docs/LOOP_PLAN.md`.
2. Plan a small vertical slice with exact file changes, commands, and pass conditions.
3. Implement it **in the repository**, run focused tests, collect logs and evidence, fix failures, rerun; do not stop at planning.
4. Run affected integration/regression checks and, when accessible, actual GPU/device smoke checks.
5. Update `docs/STATUS.md` + `docs/DECISIONS.md` with commands, observed output, failure notes, and next gate. Mark `[x]` ONLY with evidence.
6. Continue to the next slice until all acceptance tests pass or an actual hard external blocker is identified. For recurrent failures, change approach after diagnosing root cause; don't retry blindly.

## Definition of done
- A real user can launch on supported Ubuntu, import photos, see registered/unregistered, create and correct masks using SAM 3.1, review or explicitly skip remaining review, train the *real* Object-Aware implementation on selected NVIDIA GPU, visualize and export a *real* mesh, and reopen the project after a restart.
- The suite in `docs/ACCEPTANCE_TESTS.md` passes, with explicit evidence distinguishing synthetic/CI tests from an actual CUDA E2E run. No critical blockers; no hardcoded local demo files; README and installation work from a clean environment.
