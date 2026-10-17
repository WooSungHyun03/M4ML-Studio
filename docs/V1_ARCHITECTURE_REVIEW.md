# v1 architecture and safety review — 2026-10-17

Scope: Ubuntu24.04/X11 trusted single-user workstation, pinned shared Python3.10/Torch2.5.1+cu118 and original scientific source. Root source71694a6 plus bounded v1 fixes; exact candidate source recorded in release manifest. No stack rewrite.

## Responsibilities and measured changes

PySide6 owns native file dialogs/window lifetime/exact-origin WebChannel; React owns workspace/display drafts; FastAPI owns validated commands; SQLite plus atomic manifests owns projects/jobs; child processes own CUDA. Providers bind explicit capabilities and native parameters. Original training/render/loss math/native modules remain byte-identical to3221821b.

Two concrete coupling defects were fixed: file-upload GLB had a second colour-losing converter after folder import was repaired, so both now use one adapter (real multipart and folder regression). SAM startup ownership was outside the registry and release returned before cancellation closed its GPU lock; event publication now occurs after cleanup and rendering waits outside registry guards. Real flock/thread test plus native six-screen transition confirms handover. These are behavioural refactors, not replacement engines.

Native HTTP cache retained old entry HTML across builds, selecting removed/old asset hashes. Native profile NoCache and HTML no-store resolve it while keeping project/layout preferences. Regression and actual previously-cached Qt profile verify new content. Curated engine display DTO removes accidental tensor mappings from UI; explicit diagnostics remain separate and raw checkpoint validation is retained.

## Change-cost scenarios (review estimates, not timed benchmark claims)

| Change | Required seam / expected files | Boundary |
|---|---|---|
| Segmentation engine | Provider subclass, engine registry/config, provider schema, contract/GPU tests | Must supply real inference/session/mask contract; schema alone is insufficient |
| Reconstruction engine | TrainingProvider + compatible extraction/render adapters, engine config and tests | Current native renderer expects Object-Aware2DGS; a foreign representation needs its own adapter |
| Viewer | RenderingProvider/mesh output contract, viewer workspace component and lifecycle tests | GPU ownership, input validation and native UI parity remain mandatory |
| Export format | ExportProvider, allowlisted import/download metadata, roundtrip tests | Formats with material/texture baking are explicitly unsupported currently |
| Training loss option | Original/native model option first, provider-owned schema+allowlisted CLI, fingerprint tests | No invented loss variable or optimizer mutation from UI |
| Earlier project | Existing Store/schema migration + immutable source identity tests | Unknown checkpoint execution identity is retained but not guessed compatible |

App/worker modules remain relatively large; decomposition is a P2 maintenance opportunity. UI does not own native scientific variables. No rewrite is justified by a file-size statistic. PySide6 stays because actual desktop menus/dialog/drop/download/clipboard/security and native NVIDIA render are working; replacing it would duplicate these proven integrations. Prior N1/N3 timings are historical, not an equal-load comparison with another toolkit.

## Safety audit and explicit limits

Safe argv lists, bounded parsers, no eval of untrusted imported cfg, durable cancel intention, PID ownership/pidfd, per-GPU locks, latest-wins prompt identity, protected manual masks, non-destructive output directories and content-bound resume remain. Python suite covers origin/host/token/symlink/traversal, malicious packets/nonfinite cameras, corrupted PLY/checkpoint identities, cancellation and preservation. Native exact-origin/bridge tests must be rerun on the packaged candidate.

HTTP tokens are CSRF/origin protection and are not an OS multiuser authentication boundary. Direct legacy SIBR protocol also has no separate authentication. This is an explicit P2 unsupported shared-host privacy scenario; not a claim of broad security certification. No mandatory P1 is relabelled: UX/cache/handover/GLB defects were reproduced and fixed. External/public release remains blocked by actual rights obligations independently of technical outcomes. Other GPUs/Wayland/OS/overnight/500-photo/novice studies remain unverified.
