# Task settings — M4ML Studio

Feature track: `codex/task-settings-artifact-import`, separate from the preceding Quality Harness. Scientific source files and formulas are unchanged.

## Definition and execution

`studio/task_settings.py` is the definition/validation layer. Each processing Provider owns `task_settings_schema()`; a replacement Provider can override its definitions. Each field has a stable application ID, native parameter name, literal default, type, bounded range or choices, Korean label/description, section, basic/advanced flag, source, application time and scope. Native model names stay out of UI component logic. `Provider.options` supplies configured defaults for supported fields; unsupported settings are rejected. Presets are actual parameter bundles for the matching Provider, not quality guarantees.

Object-Aware defaults are parsed from the original `arguments/__init__.py` AST without importing CUDA. COLMAP definitions are based on the installed GPU COLMAP4.2.1 help saved in `evidence/settings-artifacts/colmap-*-help.txt`. Scientific parameter ranges are conservative **application input limits**, not experimentally established optimal ranges.

Before a job starts, the API resolves project settings, validates legacy per-run overrides, then freezes IDs and native parameters in `settings_snapshot`. Dispatch uses this snapshot for the worker. Every job is stored with its complete immutable request in SQLite; new worker runs also write `execution_request.json` and `execution_settings.json`. Training and mesh project records retain their snapshots. Automatic mesh extraction receives the mesh settings frozen when training was approved.

The training Provider passes allowlisted parameters to unchanged `train.py`. Camera reconstruction maps parameters to actual feature extraction/matching/Mapper flags. SAM applies official `fill_hole_area` and `sprinkle_removal_area` attributes before inference, without reloading the checkpoint. Offload changes recreate the frame session only. Live prompts still serialize requests and publish only the latest revision. The existing camera-ordered propagation mapping is preserved. `propagation_radius` applies only to the explicit nearby repropagation button.

Mesh extraction passes native TSDF flags to unchanged `render.py`. Each extraction has a unique model workspace with a read-only link to point-cloud input and a safe literal configuration. Native output is written there, validated, then copied to that job's mesh directory. Re-extraction preserves previous meshes and trained Gaussians and requires no new training.

## Persistence and migration

- User preferences: existing XDG settings, theme and window/layout preferences retain their current scope.
- Processing parameters: per-project SQLite document and atomic manifest, under `task_settings = {schema_version:1, values:{"capability:provider_key":{...}}}`.
- Review/view preferences: explicitly **project display overrides**, stored in the same project namespace. A project's loss values never become another project's defaults.
- Execution state: immutable per-job requests/snapshots, separate from editable next-run defaults. GPU selection/UUID is recorded in requests and the project's execution-device record.
- Transient camera orbit, current photo, original comparison and current tool remain viewport/session state. Existing fixed shortcuts are documented in the UI; arbitrary shortcut remapping is not claimed.

Projects without `task_settings` migrate lazily to current Provider defaults; the former `settings.iterations` value is retained. Saving materializes v1 without changing data or stage completion. Legacy iterations remain in effect until the **training Provider namespace** is saved, even if review/view settings were already saved. Explicit training reset materializes the original30000 default. Unknown future versions fail explicitly. Switching Providers selects another namespace; previous values are retained and not applied to the new Provider. A replacement must implement the actual capability execution contract as well as its schema; declaring a schema alone does not implement a new research model.

## Editing and reset

The toolbar opens **세부 설정** (or **표시 설정**) as a compact side panel, with section grouping, a collapsed **고급** area, real defaults/ranges, native input validity and server validation. Individual and current-group reset change the draft first; Save persists, Cancel discards with a dirty-state check. The scope says “현재 그룹”; there is no hidden global reset. Ctrl+S saves the open panel. Project navigation and page close protect unsaved drafts.

Processing settings are blocked during jobs and pending live inference. Unsaved mask edits also block processing changes in the UI. Changing segmentation parameters clears only its stale prediction preview, never approved/manual mask files. Review/view controls affect display immediately after saving; quick controls use a serialized, bounded queue and flush when the workspace closes. Display changes do not invalidate training.

Training runtime mutation is unsupported. A resume must match the full prior training snapshot and the original photograph/camera/mask identity. Mismatches fail before launching a new training process where detectable; the worker rechecks content hashes. The last execution's parameters are visible in the panel and can be loaded into a reviewable draft. Old checkpoints without an execution snapshot are preserved but require a new training run. The intermediate-checkpoint retention policy never prunes checkpoints that existed before the current invocation.

## Viewer boundaries

Mesh resolution scaling changes WebGL pixel ratio/render target only; Gaussian scaling changes the actual requested native CUDA frame dimensions. Targets are capped at4096 per side. UI typography/layout stay at CSS resolution. Screenshot scale is independent of viewport scale and TSDF resolution. Mesh controls include original vertex colours, shaded/wire/normal/point modes, lighting, projection, grid/axes and camera controls. Gaussian supports native RGB/Alpha/Depth/Normal/ObjectMark, perspective FOV/clipping, orbit controls and an optional RGB background tensor. The optional wire-protocol background extension preserves existing clients' default trained background. Mesh-only controls are identified as such and do not simulate Gaussian grid/lighting/orthographic support.
