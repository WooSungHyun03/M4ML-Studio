# Object-Aware Codex Loop Pack — usage

This ZIP contains only Codex instructions, specifications, test plans and a progress template. It **does not implement the application** and does not prove SAM 3.1 / GPU compatibility. Use Codex **on the actual Ubuntu/NVIDIA workstation** to execute the implementation prompt.

## Files

- `AGENTS.md`: persistent root instructions; Codex should read this automatically in the project root.
- `CODEX_PROMPT.md`: copy/paste main task prompt into Codex 6.1 Sol.
- `docs/PRD.md`: complete Korean-facing UX/business rules.
- `docs/ARCHITECTURE.md`: implementation/module/state/data contracts.
- `docs/COMPATIBILITY.md`: verified upstream dependencies, research identity and critical environment gate.
- `docs/LOOP_PLAN.md`: Phase 0–9 iterative execution loops.
- `docs/ACCEPTANCE_TESTS.md`: honest test gates and evidence standards.
- `docs/STATUS.md`: initial state; Codex must maintain while implementing.
- `docs/DECISIONS.md`: architecture and compatibility ADR log.

## Install on target Ubuntu machine

Keep a backup/inspection of any same-named files already in the target directory. These steps never overwrite existing files:

```bash
mkdir -p /home/m4ml/Desktop/Object-Aware
unzip -n Object_Aware_Codex_Loop.zip -d /home/m4ml/Desktop/Object-Aware
cd /home/m4ml/Desktop/Object-Aware
```

Ensure actual `object-aware-loss` repo and its submodules exist at the target root. If the directory is initially empty except these docs, Codex should safely integrate/clone source **without nesting accidentally**. Do not blindly `git clone ... .` into a nonempty directory; follow `AGENTS.md` and inspect first.

Start Codex 6.1 Sol from the target working directory, and paste the complete content of `CODEX_PROMPT.md` as the task. Optionally start by instructing: `Read AGENTS.md and CODEX_PROMPT.md in full and execute Phase 0 immediately.`

## Critical warnings

- `models/sam3.1` is a directory the user says exists, but its **contents have not been inspected** in this remote document-generation environment.
- The Object-Aware `environment.yml` and official SAM3.1 recommended environment are conflicting. The master prompt explicitly demands a genuine same-env compatibility check rather than fabricated compatibility.
- Sparse feature matches are not sufficient for training; require valid registered cameras and undistorted views.
- The original Gaussian-Splatting license is for noncommercial research/evaluation; audit dependencies before distribution.
