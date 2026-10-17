# Existing 3D results

`studio/result_artifacts.py` inspects content read-only; `studio/project_scan.py` integrates findings with the existing photo/COLMAP/mask analysis. Folder selection remains the only start-mode decision. The result list shows relative name, timestamp, type, validity and reasons. The user may choose several results. Imported results have unique project-owned paths and a source SHA256. Existing sources are not modified.

## Classification

- Mesh PLY: real finite vertices plus valid triangle indices. Optional RGB is preserved by the existing export/preview adapter.
- GLB: self-contained triangle geometry with vertex colours (`COLOR_0`) is supported. Linear glTF colours are converted to sRGB PLY and back to linear preview colours. A material-bearing GLB explicitly receives `ColorVisuals`; assigning colours to Trimesh `TextureVisuals` silently loses them on PLY export. External resources, texture-bearing GLB, nonwhite material colour/opacity factors and colour/vertex count mismatches are rejected with an explanation. Texture/material baking is not implemented; export vertex-coloured PLY/GLB instead.
- Native Object-Aware Gaussian PLY: finite position/SH/opacity/objectmark_score, exactly2 scale and4 rotation properties, consecutive SH coefficients matching degree0–3. Invalid rotations and dangerous scale values are rejected. Original native scales are logarithms activated with `torch.exp`; observed log-scales near −67 are legitimate tiny primitives. Application bounds are asymmetric `[-80,30]`, with finite-value/quaternion/SH checks retained. The original `GaussianModel.load_ply`/CUDA renderer is used, with no alternate Gaussian algorithm or appearance conversion.
- Generic point clouds, 3-scale 3DGS, missing ObjectMark, unsupported SH layouts, OBJ and corrupt/truncated/nonfinite PLY are explained as unsupported or invalid. They are never accepted merely because the suffix is `.ply`.

The walk stays within depth7 and60000 entries, does not follow external symlinks, and analyzes at most64 artifact candidates. PLY headers are capped at4096 lines/256KiB with bounded line lengths. Files above1GiB, more than5million vertices/10million faces, and ASCII PLY above64MiB are rejected. Forged counts and truncated payloads fail before expensive allocation; triangle list lengths are enforced. Actual tested large native input:533800 Gaussians. These are application resource limits, not claims of arbitrary-size support.

## Independent results and dataset association

A native Gaussian does not require Scene construction for this renderer: the GPU server loads the PLY directly. Import creates a typed literal `cfg_args` containing the validated SH degree and display background, and uses robust geometric bounds for initial orbit. Missing camera metadata is represented by an empty camera list; camera selection is unavailable, while free orbit remains functional. No synthetic COLMAP poses or fabricated training history are created.

Both result types are accessible via **실시간 렌더 | 메시**. The result selector activates any imported mesh or Gaussian in the same project. Mesh-only and Gaussian-only projects open directly in the 3D workspace. Training, camera and mask stages remain pending unless independently validated pipeline data was imported. `result_artifacts[].dataset_link = independent` is explicit even when files happen to share a folder with photographs. An independent Gaussian is not eligible for training resume or dataset-dependent TSDF extraction.

The existing matched-training import still checks camera names and centers, and now checks the actual native Gaussian payload. Foreign/unmatched models can be selected as independent artifacts without attaching them as completed training. Checkpoint files are not unpickled while scanning; a zip signature alone does not prove optimizer/model compatibility. External checkpoints without a full validated execution identity are reported but not automatically made resumable. In-app checkpoints with matching settings/content hashes retain actual resume support.

Original `render.py` reads `cfg_args` with eval. To retain the original scientific implementation safely, imported training and extraction workspaces receive only a bounded, AST-literal, typed `Namespace` with supported ModelParams. Executable expressions are rejected. The original config/source bytes remain untouched.

## Evidence and limitations

`evidence/settings-artifacts/browser-verified/result.json`: 12 checks covering folder UI, both real results, actual colour mesh, standalone533800-Gaussian CUDA render, real frame scaling, persistence/reset and source hashes. `variants-color-verified/result.json`: 9 checks covering Gaussian-only, GLB-only, same-size model replacement, mesh switching, and return to matching project training. `native-glb-verified/result.json`: 7 real PySide6/QtWebEngine checks with the repaired GLB and native Gaussian. `glb-color-audit.json`: actual378433-vertex/695561-triangle GLB→PLY→preview, maximum linear RGB error0.0 for this fixture. Unit coverage includes PLY/GLB-only, multiple results, both result types, generic point clouds, unsupported3DGS, corruption, NaN and forged large headers. Prior photo/COLMAP/mask and cross-dataset tests remain in the regression suite.

This feature does not certify reconstruction quality or unrestricted redistribution rights. Prior Quality Harness license/release gates and quality limitations remain unchanged.
