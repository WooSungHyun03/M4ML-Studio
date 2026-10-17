# M4ML Studio 1.0.0 — internal candidate verification

2026-10-17. Public/commercial release remains **BLOCKED (G8)**. The final candidate manifest and adjacent `QUALITY_QA.json` identify the exact archive, source commit and post-build checks; no public upload, tag or push is authorized/performed. Final native I/O/window-size checks are still running at this checkpoint.

## Actual environment and installation

Ubuntu24.04 x86_64/X11, RTX4080 16GB, driver580.173.02, Python3.10.22/Torch2.5.1+cu118/NumPy1.24.4; standalone bundled COLMAP4.2.1/CUDA12.6. UID1101 installed candidateA into an empty private runtime without a developer checkout/runtime mount. System dependencies were prepared only inside the owned test container. Existing official SAM3.1 weights and benchmark photos were read-only mounts; the X11 display was delegated only for native QA. CandidateC and final-code candidateD then completed ordinary full setup/reinstallation using that independently installed runtime. This is not a second claim that every later candidate downloaded an empty runtime again.

Actual0.4.0 API created a Korean-named project/photo/checkpoint configuration, then0.4→1.0 upgrade preserved161artifact files,2project documents, settings and Python executable SHA. After native testing, uninstall/reinstall preserved629files/5projects/settings/runtimePython byte-for-byte. Old app copies, projects and checkpoints remain; no developer/user project was replaced.

## Verified results and their scope

| Check | Observed evidence |
|---|---|
| Python source |116tests PASS56.180s; `evidence/v1/python-c-final.log` |
| Installed final-code D |116run:115PASS,1Git-only archive test SKIP47.028s; `install/python-d.log` |
| Frontend |10PASS including real component pending-vs-absent rendering; TypeScript/Vite PASS; large Three.js chunk warning retained |
| Native editor |30checks/27screens, six menus/stages, settings/provider panels, both themes,1024×640/1600×1000 actualQtDPR2, real GPU orbit/pan/zoom/reset;0JS/0network failures; `install/native-wide-verified/result.json` |
| Native final-code mask flow |15PASS: Help6, SaveAs, positive/negative and rapid latest-input inference, brush undo/redo/save, previous/next, original source mask bytes preserved; `install/native-interaction-d/result.json` |
| Native diagnosis |4PASS: pause real health request, show honest pending state, resume actualRTX response; `install/diagnostic-loading-final/result.json` |
| Native training |10PASS: actual100-iteration approval dialog, UI-submitted original GPU training, automaticTSDF256 colour mesh and actual viewer; `install/native-training-d-verified/result.json` |
| Fresh final-code GPU pipeline |New project6f22b4ce-7653-4556-a520-075bad8edcd5: COLMAP16/16, officialSAM3.1 latest revision4 and16-view propagation, manual binary edit/explicit skip, alpha.27/res400, durable100checkpoint cancellation→1000resume, changed-settings422 rejection, automaticTSDF128 colour mesh, CUDA PNG, original photo/checkpoint hashes preserved; `install/gpu-d.json` |
| Actual training loss |100finite EMA samples; first0.97454,last0.22053,min0.14417,max1.0345; `install/loss-d.json`.1000steps is integration evidence, not convergence certification. |
| Actual PLY/GLB download |6441vertices/10844triangles; exact server hashes; sRGB/linear colour roundtrip max5.960464e-8; `install/export-color-d.json` |
| Security/source |Native foreignHTTP/data navigation5PASS;115installed CPU tests include malformed/origin/PID/cancel/data guards. All manifest source hashes match except the exact3reviewed SAM compatibility patches; independently reconstructed patch hashes match. Original train/render/arguments/scene/renderer/utils/extensions diff from3221821b is empty. |
| Additional source regression |Artifact variants9, editor28/console0, standalone camera-free reset4/matrixerror0; original30K/533800-point Gaussian pointer proof is reused provenance, not falsely retrained. |

## Defects fixed and failures retained

World+Y Gaussian navigation/reset, tensor-free bounded engine information, short viewport tool overflow/panel cap, Korean welcome/launcher, stale native HTML cache, cancelledSAM-startup GPU handover, and duplicate multipart GLB colour conversion were fixed. Installed About now uses the archive SHA. Original OFL NotoSansKR is bundled for web/native accounts with no system Korean font. Installer EXDEV retirement publishes a complete hash-verified app backup before removing its owned original; launcher removal follows successful retirement. Initial hardware diagnosis no longer displays false absence before a response.

Default Docker `/dev/shm`64MiB caused actual `ERR_INSUFFICIENT_RESOURCES`, dynamic module/frame fetch failure, Qt capture errors and a capture-triggered139exit. Same installed code with1GiB passes the full native traversal and exits0; host Ubuntu had32GiB. No sandbox/security flags were relaxed. Earlier failed reports remain. QA-only races (old document readiness, image readiness, existingmanual status sampled before save, settings save busy state, obsolete interception IDs) were corrected without fabricating responses or changing research behavior. Native file-dialog automation remains under investigation at this checkpoint.

## Rights and limits

Exact9component catalogue,47bundled library hashes,51original licence-text hashes, original NotoOFL/source SHA, frontend lock and separate build-runtime Python metadata are included in SBOM. Installed dependency freeze is retained separately; weights/driver/data/runtime environments are excluded from the archive. Public/commercial NC rights, SuiteSparse source/relinking/combined distribution and CUDA/Qt/Chromium compliance obligations remain **BLOCKED**; an internal technical candidate is not a distribution waiver.

Supported scope is a trusted single-user workstation. Local API/direct legacy SIBR socket are not OS multiuser authentication. OtherGPUs/OS/Wayland,500photos,overnight stress, external novice usability study and watertight geometry quality are **NOT_RUN/not certified**. Partial coverage can produce holes; no method replacement or quality guarantee is claimed. Texture/material GLB baking is explicitly unsupported; vertex-colour PLY/GLB and native2DGS results are supported.
